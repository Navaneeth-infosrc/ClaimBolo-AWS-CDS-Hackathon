"""Entry point of the ClaimBolo agent on Amazon Bedrock AgentCore Runtime.

AgentCore Runtime starts this file and speaks HTTP on port 8080:
  GET  /ping         -> health
  POST /invocations  -> {"phone": "...", "messages": [...]}  ->  {"reply": "...", "flags": {...}, ...}

The runtime hosts the reasoning: input/output Guardrail checks, the Bedrock tool-use loop and all claim tools.
The Lambda that owns the WhatsApp channel calls it with InvokeAgentRuntime.
"""
import json
import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent import guardrail
from agent.agent import run_agent
from common.util import audit, e164
from tools.claims import ClaimTools

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("claimbolo.runtime")


def invoke(payload: dict) -> dict:
    phone = e164(payload["phone"])
    messages = payload["messages"]
    last_user_text = messages[-1]["content"][0]["text"]
    tools = ClaimTools(phone)
    blocked = None
    if not guardrail.allowed("INPUT", last_user_text):
        audit(tools.draft_id, "system", "guardrail_blocked_input", detail={"text": last_user_text[:200]})
        reply, blocked = guardrail.safe_reply(), "input"
    else:
        reply = run_agent(tools, messages)
        if reply and not guardrail.allowed("OUTPUT", reply):
            audit(tools.draft_id, "system", "guardrail_blocked_output", detail={"text": reply[:200]})
            reply, blocked = guardrail.safe_reply(), "output"
    return {"reply": reply, "flags": tools.flags, "draft_id": tools.draft_id, "blocked": blocked}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/ping":
            self._send(200, {"status": "Healthy", "time_of_last_update": int(time.time())})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/invocations":
            return self._send(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            self._send(200, invoke(json.loads(self.rfile.read(length))))
        except Exception as err:  # the Lambda falls back to its local path on any failure
            log.exception("invocation failed")
            self._send(500, {"error": f"{type(err).__name__}: {err}"})

    def log_message(self, fmt, *args):
        log.info(fmt, *args)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
