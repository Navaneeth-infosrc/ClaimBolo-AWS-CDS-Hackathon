"""Run one customer message through the real agent and tables, without sending WhatsApp.

Usage: python scripts/chat_local.py +919000000001 "My car was hit from behind this morning"
Needs AWS credentials in the environment and the deployed stack (reads its outputs).
"""
import os
import sys
import time

import boto3

from settings import PREFIX  # noqa: E402
cf = boto3.client("cloudformation", region_name="us-east-1")
fn = boto3.client("lambda", region_name="us-east-1")
cfg = fn.get_function_configuration(FunctionName=f"{PREFIX}-agent")["Environment"]["Variables"]
os.environ.update(cfg)
os.environ["DEBOUNCE_SECONDS"] = "0"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent import guardrail  # noqa: E402
from agent.agent import build_history, run_agent  # noqa: E402
from common.util import e164, now_iso, put_conversation  # noqa: E402
from tools.claims import ClaimTools  # noqa: E402

phone, text = e164(sys.argv[1]), sys.argv[2]
ts = f"{now_iso()}#local{int(time.time()) % 100000}"
from common.util import table  # noqa: E402
table("CONVERSATIONS_TABLE").put_item(Item={"phone": phone, "ts": ts, "direction": "IN", "channel": "local",
                                           "type": "text", "original_text": text})
tools = ClaimTools(phone)
if not guardrail.allowed("INPUT", text):
    reply = guardrail.safe_reply()
else:
    reply = run_agent(tools, build_history(phone))
    if not guardrail.allowed("OUTPUT", reply):
        reply = guardrail.safe_reply()
put_conversation(phone, "OUT", "text", reply)
print(reply)
print("\n[flags]", tools.flags)
