"""EventBridge: a Transcribe job finished. Attach the transcript to the message and wake the agent."""
import json
import logging
import os
import urllib.request

import boto3

from cds import whatsapp
from common.util import put_conversation, table

log = logging.getLogger()
log.setLevel(logging.INFO)

_transcribe = boto3.client("transcribe")
_lambda = boto3.client("lambda")
PHONE_NUMBER_ID = os.environ["WHATSAPP_PHONE_NUMBER_ID"]


def _find_row(job: str):
    conversations = table("CONVERSATIONS_TABLE")
    kwargs = {"FilterExpression": "transcribe_job = :j", "ExpressionAttributeValues": {":j": job}}
    while True:
        page = conversations.scan(**kwargs)
        if page["Items"]:
            return page["Items"][0]
        if "LastEvaluatedKey" not in page:
            return None
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def handler(event, context):
    detail = event["detail"]
    job = detail["TranscriptionJobName"]
    if not job.startswith("claimbolo-"):
        return
    row = _find_row(job)
    if not row:
        log.warning("no conversation row for %s", job)
        return

    transcript, language = "", ""
    if detail["TranscriptionJobStatus"] == "COMPLETED":
        info = _transcribe.get_transcription_job(TranscriptionJobName=job)["TranscriptionJob"]
        language = info.get("LanguageCode", "")
        with urllib.request.urlopen(info["Transcript"]["TranscriptFileUri"]) as resp:
            transcript = json.load(resp)["results"]["transcripts"][0]["transcript"].strip()

    if not transcript:
        text = "Sorry, I could not understand that voice note. Could you send it again or type your message? " \
               "மன்னிக்கவும், குரல் செய்தியைப் புரிந்துகொள்ள முடியவில்லை. தயவுசெய்து மீண்டும் அனுப்பவும் அல்லது எழுத்து மூலம் தெரிவிக்கவும்."
        message_id = whatsapp.send_text(PHONE_NUMBER_ID, row["phone"], text)
        put_conversation(row["phone"], "OUT", "text", text, message_id=message_id)
        return

    table("CONVERSATIONS_TABLE").update_item(
        Key={"phone": row["phone"], "ts": row["ts"]},
        UpdateExpression="SET original_text = :t, detected_language = :l",
        ExpressionAttributeValues={":t": f"[voice note, language {language}] {transcript}", ":l": language})
    log.info("transcribed %s (%s): %s", job, language, transcript[:120])
    _lambda.invoke(FunctionName=os.environ["AGENT_FUNCTION"], InvocationType="Event",
                   Payload=json.dumps({"phone": row["phone"], "trigger_ts": row["ts"]}))
