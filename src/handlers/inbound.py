"""Receives WhatsApp events published to SNS by End User Messaging Social.

Per inbound message: de-duplicate, store the conversation row, copy media to S3, start a
Transcribe job for voice notes, and wake the agent. Delivery failures trigger an email fallback.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from cds import whatsapp
from handlers import proactive

log = logging.getLogger()
log.setLevel(logging.INFO)

_ddb = boto3.resource("dynamodb")
_processed = _ddb.Table(os.environ["PROCESSED_TABLE"])
_conversations = _ddb.Table(os.environ["CONVERSATIONS_TABLE"])
_s3 = boto3.client("s3")
_transcribe = boto3.client("transcribe")
_lambda = boto3.client("lambda")

BUCKET = os.environ["MEDIA_BUCKET"]
PHONE_NUMBER_ID = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
AGENT_FUNCTION = os.environ["AGENT_FUNCTION"]
PROJECT_TAG = os.environ.get("PROJECT_TAG", "")
LANGUAGE_OPTIONS = ["ta-IN", "hi-IN", "en-IN", "te-IN", "ml-IN", "kn-IN"]
MEDIA_TYPES = ("audio", "image", "document", "video")
DEDUPE_TTL_SECONDS = 7 * 24 * 3600
BUTTON_TEXT = {"status": "What is the status of my claim?", "human": "I want to talk to a person"}


def handler(event, context):
    for record in event["Records"]:
        envelope = json.loads(record["Sns"]["Message"])
        entry = json.loads(envelope["whatsAppWebhookEntry"])
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                _process(message)
            for status in value.get("statuses", []):
                _on_status(status)


def _on_status(status: dict) -> None:
    log.info("delivery status: %s", json.dumps(status))
    if status.get("status") == "failed":
        proactive.email_fallback(status.get("recipient_id", ""), "WhatsApp delivery failed")


def _claim(message_id: str) -> bool:
    """True if this is the first time we see message_id. Deliveries can repeat."""
    try:
        _processed.put_item(
            Item={"message_id": message_id, "expires_at": int(time.time()) + DEDUPE_TTL_SECONDS},
            ConditionExpression="attribute_not_exists(message_id)",
        )
        return True
    except ClientError as err:
        if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def _process(message: dict) -> None:
    message_id = message["id"]
    if not _claim(message_id):
        log.info("duplicate delivery ignored: %s", message_id)
        return
    try:
        _store(message)
    except Exception:
        # Release the marker so the SNS retry processes this message again
        _processed.delete_item(Key={"message_id": message_id})
        raise


def _store(message: dict) -> None:
    kind = message["type"]
    digits = "".join(c for c in message["from"] if c.isdigit())
    phone = f"+{digits}"
    sent_at = datetime.fromtimestamp(int(message["timestamp"]), tz=timezone.utc).isoformat()

    row = {
        "phone": phone,
        "ts": f"{sent_at}#{message['id'][-8:]}",
        "direction": "IN",
        "channel": "whatsapp",
        "type": kind,
        "message_id": message["id"],
    }
    wake_agent = False
    if kind == "text":
        row["original_text"] = message["text"]["body"]
        wake_agent = True
    elif kind == "interactive":
        reply = message["interactive"].get("button_reply") or message["interactive"].get("list_reply") or {}
        row["original_text"] = BUTTON_TEXT.get(reply.get("id"), reply.get("title", ""))
        wake_agent = True
    elif kind in MEDIA_TYPES:
        media = message[kind]
        row["media_id"] = media["id"]
        row["mime_type"] = media.get("mime_type", "")
        row["s3_key"] = _download(digits, media["id"])
        if kind == "audio":
            row["transcribe_job"] = _start_transcription(media["id"], row["s3_key"])  # agent wakes after transcription
        elif kind == "image":
            row["original_text"] = f"[Customer sent a photo. s3_key={row['s3_key']}]"
            wake_agent = True
        else:
            row["original_text"] = f"[Customer sent a {kind}, which is not supported]"
            wake_agent = True

    _conversations.put_item(Item=row)
    log.info("stored %s message from %s", kind, phone)
    if wake_agent:
        _lambda.invoke(FunctionName=AGENT_FUNCTION, InvocationType="Event",
                       Payload=json.dumps({"phone": phone, "trigger_ts": row["ts"]}))


def _download(digits: str, media_id: str) -> str:
    prefix = f"media/{digits}/"
    whatsapp.download_media(PHONE_NUMBER_ID, media_id, BUCKET, prefix)
    listing = _s3.list_objects_v2(Bucket=BUCKET, Prefix=f"{prefix}{media_id}")
    return listing["Contents"][0]["Key"]


def _start_transcription(media_id: str, s3_key: str) -> str:
    job = f"claimbolo-{media_id}"
    params = dict(
        TranscriptionJobName=job,
        Media={"MediaFileUri": f"s3://{BUCKET}/{s3_key}"},
        IdentifyLanguage=True,
        LanguageOptions=LANGUAGE_OPTIONS,
    )
    if PROJECT_TAG:
        params["Tags"] = [{"Key": "Project", "Value": PROJECT_TAG}]
    _transcribe.start_transcription_job(**params)
    return job
