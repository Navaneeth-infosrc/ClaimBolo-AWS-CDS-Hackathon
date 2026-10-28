"""Runs the claims agent for one customer and sends the reply on WhatsApp."""
import json
import logging
import os
import time

import boto3
from botocore.config import Config

from agent import guardrail, memory
from agent.agent import build_history, run_agent
from cds import whatsapp
from common.util import audit, e164, put_conversation, table
from tools.claims import ClaimTools

log = logging.getLogger()
log.setLevel(logging.INFO)

PHONE_NUMBER_ID = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
RUNTIME_ARN = os.environ.get("AGENT_RUNTIME_ARN", "")
_agentcore = boto3.client("bedrock-agentcore", config=Config(read_timeout=140, retries={"max_attempts": 1}))
DEBOUNCE_SECONDS = float(os.environ.get("DEBOUNCE_SECONDS", "3"))
BUTTONS = {
    "en": [("status", "Check status"), ("human", "Talk to a person")],
    "ta": [("status", "நிலையை அறிய"), ("human", "நபருடன் பேச")],
    "hi": [("status", "स्थिति देखें"), ("human", "व्यक्ति से बात")],
    "te": [("status", "స్థితి తెలుసుకోండి"), ("human", "సహాయం కావాలి")],
    "ml": [("status", "നില അറിയാൻ"), ("human", "ആളോട് സംസാരിക്കാൻ")],
    "kn": [("status", "ಸ್ಥಿತಿ ತಿಳಿಯಿರಿ"), ("human", "ಸಹಾಯ ಬೇಕು")],
}
FALLBACK = ("Sorry, something went wrong on our side. An adjuster has been notified and will contact you. "
            "மன்னிக்கவும், எங்கள் பக்கத்தில் சிறு தொழில்நுட்பக் கோளாறு ஏற்பட்டுள்ளது. காப்பீட்டு நிறுவன அலுவலர் உங்களைத் தொடர்பு கொள்வார்.")


def _via_runtime(phone: str, messages: list):
    """Run the agent on Amazon Bedrock AgentCore Runtime. Returns None if the runtime call fails."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    session = f"claimbolo-{digits}-{time.strftime('%Y%m%d')}".ljust(40, "0")  # session ids need 33+ characters
    try:
        resp = _agentcore.invoke_agent_runtime(
            agentRuntimeArn=RUNTIME_ARN, runtimeSessionId=session,
            payload=json.dumps({"phone": phone, "messages": messages}, ensure_ascii=False).encode("utf-8"))
        result = json.loads(resp["response"].read())
        if "error" in result:
            raise RuntimeError(result["error"])
        log.info("agent ran on AgentCore Runtime")
        return result
    except Exception:
        log.exception("AgentCore Runtime call failed, falling back to the local agent")
        return None


def _locally(tools: ClaimTools, messages: list, last_user_text: str) -> dict:
    blocked = None
    if not guardrail.allowed("INPUT", last_user_text):
        audit(tools.draft_id, "system", "guardrail_blocked_input", detail={"text": last_user_text[:200]})
        reply, blocked = guardrail.safe_reply(), "input"
    else:
        reply = run_agent(tools, messages)
        if reply and not guardrail.allowed("OUTPUT", reply):
            audit(tools.draft_id, "system", "guardrail_blocked_output", detail={"text": reply[:200]})
            reply, blocked = guardrail.safe_reply(), "output"
    return {"reply": reply, "flags": tools.flags, "blocked": blocked}


def _latest_inbound_ts(phone: str):
    rows = table("CONVERSATIONS_TABLE").query(
        KeyConditionExpression="phone = :p", ExpressionAttributeValues={":p": phone},
        ScanIndexForward=False, Limit=15)["Items"]
    return next((r["ts"] for r in rows if r["direction"] == "IN"), None)


def handler(event, context):
    phone = e164(event["phone"])
    # Several photos in a row each trigger this function; only the newest one answers.
    time.sleep(DEBOUNCE_SECONDS)
    if _latest_inbound_ts(phone) != event["trigger_ts"]:
        log.info("newer message exists, skipping")
        return {"skipped": True}

    messages = build_history(phone)
    if not messages or messages[-1]["role"] != "user":
        return {"skipped": "nothing to answer"}

    tools = ClaimTools(phone)
    last_user_text = messages[-1]["content"][0]["text"]
    flags = tools.flags
    try:
        result = _via_runtime(phone, messages) if RUNTIME_ARN else None
        if result is None:  # runtime not configured or unavailable: run the same agent code locally
            result = _locally(tools, messages, last_user_text)
        reply = result["reply"] or FALLBACK
        flags = result["flags"]
    except Exception:
        log.exception("agent failed")
        audit(tools.draft_id, "system", "agent_error")
        ClaimTools(phone).call("escalate_to_adjuster", {"reason": "automatic: agent error"})
        reply = FALLBACK

    claim_id = flags["claim_created"]
    if claim_id:
        language = flags.get("language", "en")
        message_id = whatsapp.send_buttons(PHONE_NUMBER_ID, phone, reply[:1024],
                                           BUTTONS.get(language, BUTTONS["en"]))
        kind = "interactive"
    else:
        message_id = whatsapp.send_text(PHONE_NUMBER_ID, phone, reply)
        kind = "text"
    put_conversation(phone, "OUT", kind, reply, message_id=message_id)
    memory.record(phone, "USER", last_user_text)
    memory.record(phone, "ASSISTANT", reply)
    return {"sent": True, "claim_id": claim_id}
