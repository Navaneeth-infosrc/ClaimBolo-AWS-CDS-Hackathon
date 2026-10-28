"""WhatsApp channel via AWS End User Messaging Social (boto3 client: socialmessaging)."""
import json
import os

import boto3

META_API_VERSION = "v20.0"

_client = boto3.client("socialmessaging", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def to_e164(number: str) -> str:
    """SendWhatsAppMessage rejects bare digits; recipients must carry a leading '+'."""
    return "+" + "".join(c for c in number if c.isdigit())


def _send(phone_number_id: str, payload: dict) -> str:
    resp = _client.send_whatsapp_message(
        originationPhoneNumberId=phone_number_id,
        message=json.dumps(payload).encode("utf-8"),
        metaApiVersion=META_API_VERSION,
    )
    return resp["messageId"]


def send_text(phone_number_id: str, to: str, body: str) -> str:
    """Free-form text. Only delivered inside the 24-hour window after the customer last wrote."""
    return _send(phone_number_id, {
        "messaging_product": "whatsapp",
        "to": to_e164(to),
        "type": "text",
        "text": {"body": body},
    })


def send_buttons(phone_number_id: str, to: str, body: str, buttons: list) -> str:
    """Interactive reply buttons: buttons is [(id, title), ...], at most 3, titles up to 20 characters."""
    return _send(phone_number_id, {
        "messaging_product": "whatsapp",
        "to": to_e164(to),
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {"buttons": [{"type": "reply", "reply": {"id": i, "title": t[:20]}} for i, t in buttons[:3]]},
        },
    })


def send_template(phone_number_id: str, to: str, name: str, language: str, params: list) -> str:
    """Pre-approved template. The only message type allowed outside the 24-hour window."""
    return _send(phone_number_id, {
        "messaging_product": "whatsapp",
        "to": to_e164(to),
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": language},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in params]}],
        },
    })


def download_media(phone_number_id: str, media_id: str, bucket: str, key_prefix: str) -> dict:
    """Copy an inbound voice note or photo into S3.

    The service appends '<media_id>.<extension>' to the key it is given, so pass a prefix
    ending in '/' and look the object up afterwards.
    """
    return _client.get_whatsapp_message_media(
        mediaId=media_id,
        originationPhoneNumberId=phone_number_id,
        destinationS3File={"bucketName": bucket, "key": key_prefix},
    )
