"""Proactive updates. Triggered by EventBridge when a human changes a claim's status.

Inside the 24-hour window: free-form WhatsApp text. Outside it: an approved template.
If WhatsApp fails or later reports a delivery failure: email through SES.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

from cds import email as ses_email
from cds import whatsapp
from common.util import audit, e164, put_conversation, table

log = logging.getLogger()
log.setLevel(logging.INFO)

PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WINDOW = timedelta(hours=23)  # WhatsApp allows 24h; keep a margin

TEXT = {
    "SURVEY_SCHEDULED": {
        "en": "Your claim {claim_id}: the surveyor visit is scheduled for {date} at {time}. Please keep your vehicle and documents ready.",
        "ta": "உங்கள் காப்பீட்டுக் கோரிக்கை {claim_id}: சர்வேயர் வருகை {date} அன்று {time} மணிக்குத் திட்டமிடப்பட்டுள்ளது. வாகனத்தையும் ஆவணங்களையும் தயாராக வைத்திருக்கவும்.",
        "hi": "आपका क्लेम {claim_id}: सर्वेयर की विज़िट {date} को {time} बजे तय हुई है। कृपया वाहन और दस्तावेज़ तैयार रखें।",
        "te": "మీ క్లెయిమ్ {claim_id}: సర్వేయర్ సందర్శన {date} న {time} కి నిర్ణయించబడింది. దయచేసి మీ వాహనం మరియు పత్రాలను సిద్ధంగా ఉంచండి.",
        "ml": "നിങ്ങളുടെ ക്ലെയിം {claim_id}: സർവേയർ സന്ദർശനം {date} ന് {time} ന് നിശ്ചയിച്ചിരിക്കുന്നു. ദയവായി നിങ്ങളുടെ വാഹനവും രേഖകളും തയ്യാറാക്കി വയ്ക്കുക.",
        "kn": "ನಿಮ್ಮ ಕ್ಲೇಮ್ {claim_id}: ಸರ್ವೇಯರ್ ಭೇಟಿಯನ್ನು {date} ರಂದು {time} ಕ್ಕೆ ನಿಗದಿಪಡಿಸಲಾಗಿದೆ. ದಯವಿಟ್ಟು ನಿಮ್ಮ ವಾಹನ ಮತ್ತು ದಾಖಲೆಗಳನ್ನು ಸಿದ್ಧವಾಗಿಡಿ.",
    },
    "CLOSED": {
        "en": "Your claim {claim_id} has been closed. Thank you for your patience.",
        "ta": "உங்கள் காப்பீட்டுக் கோரிக்கை {claim_id} முடிவுக்கு வந்தது. உங்கள் ஒத்துழைப்புக்கு நன்றி.",
        "hi": "आपका क्लेम {claim_id} बंद कर दिया गया है। धैर्य के लिए धन्यवाद।",
        "te": "మీ క్లెయిమ్ {claim_id} ముగించబడింది. మీ సహనానికి ధన్యవాదాలు.",
        "ml": "നിങ്ങളുടെ ക്ലെയിം {claim_id} അവസാനിപ്പിച്ചിരിക്കുന്നു. ക്ഷമയ്ക്ക് നന്ദി.",
        "kn": "ನಿಮ್ಮ ಕ್ಲೇಮ್ {claim_id} ಮುಕ್ತಾಯಗೊಂಡಿದೆ. ನಿಮ್ಮ ತಾಳ್ಮೆಗೆ ಧನ್ಯವಾದಗಳು.",
    },
}


def _text(detail: dict) -> str:
    templates = TEXT.get(detail["status"])
    lang = detail.get("language", "en")
    if not templates:
        return f"Update on your claim {detail['claim_id']}: the status is now {detail['status'].replace('_', ' ').lower()}."
    return templates.get(lang, templates["en"]).format(
        claim_id=detail["claim_id"], date=detail.get("survey_date", ""), time=detail.get("survey_time", ""))


def _in_window(phone: str) -> bool:
    rows = table("CONVERSATIONS_TABLE").query(
        KeyConditionExpression="phone = :p", ExpressionAttributeValues={":p": phone},
        ScanIndexForward=False, Limit=15)["Items"]
    last_in = next((r["ts"] for r in rows if r["direction"] == "IN"), None)
    if not last_in:
        return False
    return datetime.now(timezone.utc) - datetime.fromisoformat(last_in.split("#")[0]) < WINDOW


def _send_template(detail: dict, phone: str) -> str:
    lang = detail.get("language", "en")
    if detail["status"] == "SURVEY_SCHEDULED":
        language = "ta" if lang == "ta" else "en"
        return whatsapp.send_template(PHONE_NUMBER_ID, phone, "survey_scheduled", language,
                                      [detail["claim_id"], detail.get("survey_date", ""), detail.get("survey_time", "")])
    status = detail["status"].replace("_", " ").lower()
    return whatsapp.send_template(PHONE_NUMBER_ID, phone, "claim_status_update", "en",
                                  [detail["claim_id"], status, "we will keep you updated here"])


def handler(event, context):
    detail = event["detail"]
    phone = e164(detail["phone"])
    text = _text(detail)
    try:
        if _in_window(phone):
            message_id, kind = whatsapp.send_text(PHONE_NUMBER_ID, phone, text), "text"
        else:
            message_id, kind = _send_template(detail, phone), "template"
        put_conversation(phone, "OUT", kind, text, message_id=message_id, proactive=True)
        audit(detail["claim_id"], "system", "proactive_update_sent", kind, {"status": detail["status"]})
        return {"sent": kind}
    except Exception as err:
        log.exception("WhatsApp send failed, falling back to email")
        audit(detail["claim_id"], "system", "whatsapp_failed", detail={"error": str(err)})
        email_fallback(phone, f"Update on claim {detail['claim_id']}: {text}")
        return {"sent": "email"}


def email_fallback(phone: str, text: str) -> None:
    """Email the customer about their latest claim when WhatsApp could not deliver."""
    sender = os.environ.get("SES_SENDER")
    phone = e164(phone)
    claims = table("CLAIMS_TABLE").query(
        IndexName="phone-index", KeyConditionExpression="phone = :p",
        ExpressionAttributeValues={":p": phone}, ScanIndexForward=False)["Items"]
    claim = next((c for c in claims if c.get("status") != "DRAFT"), None)
    if not (sender and claim and claim.get("email")):
        return
    ses_email.send_email(claim["email"], f"Update on your claim {claim['claim_id']}",
                         f"<p>{text}</p>", sender, os.environ.get("SES_CONFIG_SET", ""))
    audit(claim["claim_id"], "system", "email_fallback_sent", "send_email", {"to": claim["email"]})
