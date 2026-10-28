"""Small helpers shared by the Lambda handlers, the tools and the local scripts."""
import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3

_ddb = boto3.resource("dynamodb")


def table(env_name: str):
    return _ddb.Table(os.environ[env_name])


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def digits(phone: str) -> str:
    return "".join(c for c in phone if c.isdigit())


def e164(phone: str) -> str:
    return "+" + digits(phone)


def to_jsonable(obj):
    """DynamoDB returns Decimal and set; make it safe for JSON and for Converse tool results."""
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]
    return obj


def dumps(obj) -> str:
    return json.dumps(to_jsonable(obj), ensure_ascii=False)


def put_conversation(phone: str, direction: str, kind: str, text: str, **extra) -> str:
    """Append a row to the conversation log. Returns the sort key."""
    ts = f"{now_iso()}#{'out' if direction == 'OUT' else 'sys'}{uuid.uuid4().hex[:6]}"
    item = {"phone": e164(phone), "ts": ts, "direction": direction, "channel": "whatsapp",
            "type": kind, "original_text": text, **{k: v for k, v in extra.items() if v is not None}}
    table("CONVERSATIONS_TABLE").put_item(Item=item)
    return ts


def audit(key: str, actor: str, action: str, tool: str = "", detail=None) -> None:
    """Every agent action and human action is recorded with who did it."""
    table("AUDIT_TABLE").put_item(Item={
        "claim_id": key, "ts": f"{now_iso()}#{uuid.uuid4().hex[:4]}",
        "actor": actor, "action": action, "tool": tool,
        "detail": dumps(detail)[:2000] if detail is not None else "",
    })
