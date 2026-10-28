"""The agent's tools. One ClaimTools instance is bound to one customer's phone number, so the
model can never read or change another customer's data."""
import json
import os
import re

import boto3

from cds import email as ses_email
from common.util import audit, digits, dumps, e164, now_iso, table, to_jsonable
from rules.coverage import check_coverage, find_missing

_s3 = boto3.client("s3")
_bedrock = boto3.client("bedrock-runtime")
_MODEL_ID = os.environ.get("MODEL_ID", "")

PHOTO_PROMPT = (
    "You check photos for a motor insurance claim. Look at the photo and answer with ONLY a JSON object: "
    '{"usable": bool, "damage_visible": bool, "plate_readable": bool, "plate_text": string or null, '
    '"matches_description": bool or null, "tags": [short strings], "reason": "one short sentence"}. '
    "usable=false if the photo is blurry, too dark, cropped, or not a vehicle. "
    "plate_readable=true only if every character of a number plate can be read. "
    "Claim description given by the customer: {description}"
)


def _obj(properties=None, required=None):
    return {"json": {"type": "object", "properties": properties or {}, "required": required or []}}


TOOL_SPECS = [
    {"toolSpec": {"name": "lookup_policy", "description":
        "Find this customer's motor policy (vehicle, registration, cover type, deductible, validity, language). Call first.",
        "inputSchema": _obj()}},
    {"toolSpec": {"name": "save_claim_facts", "description":
        "Record facts the customer gave about the accident. Only pass fields the customer actually stated. "
        "Dates as YYYY-MM-DD. injuries and third_party_involved are booleans, set only when the customer said so. "
        "Returns the facts so far and what is still missing.",
        "inputSchema": _obj({
            "incident_date": {"type": "string"}, "incident_time": {"type": "string"},
            "location": {"type": "string"}, "description": {"type": "string"},
            "injuries": {"type": "boolean"}, "third_party_involved": {"type": "boolean"},
            "police_report": {"type": "boolean"}})}},
    {"toolSpec": {"name": "find_missing_items", "description":
        "List what is still needed before the claim can be registered (facts, answers, photos).",
        "inputSchema": _obj()}},
    {"toolSpec": {"name": "assess_photo", "description":
        "Check one photo the customer sent (s3_key is given in the message) for quality and content.",
        "inputSchema": _obj({"s3_key": {"type": "string"}}, ["s3_key"])}},
    {"toolSpec": {"name": "check_coverage", "description":
        "Deterministic coverage check for this accident against the policy. Never state coverage without calling this.",
        "inputSchema": _obj()}},
    {"toolSpec": {"name": "create_claim", "description":
        "Register the claim and email the summary. Only works when nothing is missing. Returns the claim id.",
        "inputSchema": _obj()}},
    {"toolSpec": {"name": "get_claim_status", "description":
        "Current status and next step of this customer's most recent claim.",
        "inputSchema": _obj()}},
    {"toolSpec": {"name": "escalate_to_adjuster", "description":
        "Hand the case to a human adjuster, with the reason. Use when the customer asks for a person, is upset, "
        "reports injuries, or you cannot proceed. Not for ordinary third-party involvement.",
        "inputSchema": _obj({"reason": {"type": "string"}}, ["reason"])}},
    {"toolSpec": {"name": "set_language", "description":
        "Remember the customer's language: ta (Tamil), hi (Hindi), en (English), te (Telugu), ml (Malayalam) or kn (Kannada).",
        "inputSchema": _obj({"language": {"type": "string", "enum": ["ta", "hi", "en", "te", "ml", "kn"]}}, ["language"])}},
]


def _norm_plate(text) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


class ClaimTools:
    def __init__(self, phone: str):
        self.phone = e164(phone)
        self.digits = digits(phone)
        self.draft_id = f"DRAFT#{self.digits}"
        self.claims = table("CLAIMS_TABLE")
        self.flags = {"claim_created": None, "escalated": False}

    # ---- plumbing -------------------------------------------------------------------------
    def tool_config(self) -> dict:
        return {"tools": TOOL_SPECS}

    def call(self, name: str, args: dict) -> dict:
        fn = getattr(self, f"t_{name}", None)
        if fn is None:
            return {"error": f"unknown tool {name}"}
        try:
            result = to_jsonable(fn(**(args or {})))
        except Exception as err:  # the model reads the error and can recover
            result = {"error": f"{type(err).__name__}: {err}"}
        audit(self._audit_key(), "agent", "tool_call", name, {"args": args, "result": result})
        return result if isinstance(result, dict) else {"result": result}

    def _audit_key(self) -> str:
        return self.flags["claim_created"] or self.draft_id

    def _draft(self) -> dict:
        item = self.claims.get_item(Key={"claim_id": self.draft_id}).get("Item")
        if item:
            return item
        item = {"claim_id": self.draft_id, "phone": self.phone, "status": "DRAFT", "facts": {},
                "photos": [], "created_at": now_iso()}
        self.claims.put_item(Item=item)
        return item

    def _save_draft(self, draft: dict) -> None:
        self.claims.put_item(Item=draft)

    def _policy(self):
        return table("POLICIES_TABLE").get_item(Key={"phone": self.phone}).get("Item")

    # ---- tools ------------------------------------------------------------------------------
    def _demo_policy(self) -> dict:
        """Demo mode only: anyone who messages the number gets a fictional policy so they can try the flow."""
        policy = {"phone": self.phone, "policy_no": f"KGI-DEMO-{self.digits[-6:]}", "holder_name": "Demo Customer",
                  "vehicle": "Your vehicle (demo policy)", "reg_no": None, "cover_type": "comprehensive",
                  "deductible": 1000, "valid_from": "2026-01-01", "valid_to": "2026-12-31",
                  "email": os.environ.get("ADJUSTER_EMAIL", ""), "preferred_lang": "en", "demo": True}
        table("POLICIES_TABLE").put_item(Item=policy)
        audit(self.draft_id, "system", "demo_policy_created", "lookup_policy")
        return policy

    def t_lookup_policy(self) -> dict:
        policy = self._policy()
        if not policy and os.environ.get("DEMO_MODE") == "true":
            policy = self._demo_policy()
        if not policy:
            return {"found": False}
        return {"found": True, "demo_policy": bool(policy.get("demo")), "holder_name": policy.get("holder_name"), "policy_no_last4": policy["policy_no"][-4:],
                "vehicle": policy.get("vehicle"), "reg_no": policy.get("reg_no"),
                "cover_type": policy.get("cover_type"), "deductible_inr": policy.get("deductible"),
                "valid_from": policy.get("valid_from"), "valid_to": policy.get("valid_to"),
                "preferred_lang": policy.get("preferred_lang")}

    def t_set_language(self, language: str) -> dict:
        draft = self._draft()
        draft["language"] = language
        self._save_draft(draft)
        return {"language": language}

    def t_save_claim_facts(self, **facts) -> dict:
        draft = self._draft()
        allowed = {"incident_date", "incident_time", "location", "description", "injuries",
                   "third_party_involved", "police_report"}
        draft["facts"].update({k: v for k, v in facts.items() if k in allowed and v is not None})
        self._save_draft(draft)
        return {"facts": draft["facts"], "missing": find_missing(draft["facts"], draft["photos"])}

    def t_find_missing_items(self) -> dict:
        draft = self._draft()
        return {"missing": find_missing(draft["facts"], draft["photos"]),
                "photos_checked": len(draft["photos"])}

    def t_assess_photo(self, s3_key: str) -> dict:
        if not s3_key.startswith(f"media/{self.digits}/"):
            return {"error": "that photo does not belong to this customer"}
        draft = self._draft()
        if any(p["s3_key"] == s3_key for p in draft["photos"]):
            return {"already_assessed": True,
                    "assessment": next(p["assessment"] for p in draft["photos"] if p["s3_key"] == s3_key)}
        ext = s3_key.rsplit(".", 1)[-1].lower()
        fmt = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(ext)
        if not fmt:
            return {"error": f"unsupported image type .{ext}"}
        data = _s3.get_object(Bucket=os.environ["MEDIA_BUCKET"], Key=s3_key)["Body"].read()
        prompt = PHOTO_PROMPT.replace("{description}", str(draft["facts"].get("description", "not given yet")))
        resp = _bedrock.converse(
            modelId=_MODEL_ID,
            messages=[{"role": "user", "content": [{"text": prompt},
                                                   {"image": {"format": fmt, "source": {"bytes": data}}}]}],
            inferenceConfig={"maxTokens": 3000},
        )
        text = "".join(b["text"] for b in resp["output"]["message"]["content"] if "text" in b)
        match = re.search(r"\{.*\}", text, re.S)
        assessment = json.loads(match.group(0)) if match else {"usable": False, "reason": "could not read photo"}
        policy = self._policy() or {}
        plate = assessment.get("plate_text")
        # Advisory only: shown to the adjuster, never blocks a claim. Policies created in demo mode are fictional,
        # so their registration number is not compared.
        comparable = plate and policy.get("reg_no") and not policy.get("demo") and os.environ.get("DEMO_MODE") != "true"
        assessment["plate_matches_policy"] = _norm_plate(plate) == _norm_plate(policy.get("reg_no")) if comparable else None
        number = len(draft["photos"]) + 1
        draft["photos"].append({"s3_key": s3_key, "photo_number": number, "assessment": assessment})
        self._save_draft(draft)
        return {"photo_number": number, "assessment": assessment,
                "missing": find_missing(draft["facts"], draft["photos"])}

    def t_check_coverage(self) -> dict:
        policy, draft = self._policy(), self._draft()
        if not policy:
            return {"error": "no policy found for this phone number"}
        result = check_coverage(policy, draft["facts"])
        draft["coverage"] = result
        self._save_draft(draft)
        return result

    def t_create_claim(self) -> dict:
        policy, draft = self._policy(), self._draft()
        if not policy:
            return {"error": "no policy found for this phone number"}
        missing = find_missing(draft["facts"], draft["photos"])
        if missing:
            return {"error": "cannot register yet", "missing": missing}
        if not draft.get("coverage"):
            draft["coverage"] = check_coverage(policy, draft["facts"])
        counter = self.claims.update_item(
            Key={"claim_id": "COUNTER"}, UpdateExpression="ADD n :one",
            ExpressionAttributeValues={":one": 1}, ReturnValues="UPDATED_NEW")["Attributes"]["n"]
        claim_id = f"CLM-{1000 + int(counter)}"
        status = "ESCALATED" if draft["coverage"].get("escalate") else "REGISTERED"
        claim = {**draft, "claim_id": claim_id, "status": status, "policy_no": policy["policy_no"],
                 "holder_name": policy.get("holder_name"), "vehicle": policy.get("vehicle"),
                 "reg_no": policy.get("reg_no"), "email": policy.get("email"),
                 "language": draft.get("language") or policy.get("preferred_lang", "en"),
                 "first_contact_at": draft["created_at"], "created_at": now_iso(), "registered_at": now_iso()}
        self.claims.put_item(Item=claim)
        self.claims.delete_item(Key={"claim_id": self.draft_id})
        self.flags["claim_created"] = claim_id
        self.flags["language"] = claim["language"]
        emailed = self._email_summary(claim, policy)
        audit(claim_id, "agent", "claim_registered", "create_claim", {"status": status})
        return {"claim_id": claim_id, "status": status, "coverage": draft["coverage"],
                "summary_email_sent": emailed,
                "next_step": "a surveyor will contact the customer within 1 working day"}

    def _email_summary(self, claim: dict, policy: dict) -> bool:
        sender = os.environ.get("SES_SENDER")
        if not sender:
            return False
        cov = claim["coverage"]
        facts = claim["facts"]
        rows = "".join(f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in [
            ("Claim", claim["claim_id"]), ("Status", claim["status"]), ("Policy holder", claim.get("holder_name")),
            ("Vehicle", f"{claim.get('vehicle')} ({claim.get('reg_no')})"),
            ("Incident", f"{facts.get('incident_date')} {facts.get('incident_time', '')} at {facts.get('location')}"),
            ("What happened", facts.get("description")),
            ("Covered by policy", cov.get("covered")), ("Deductible (INR)", cov.get("deductible"))])
        html = (f"<h2>Claim {claim['claim_id']} registered</h2><table cellpadding='6'>{rows}</table>"
                "<p>Next step: a surveyor will contact you within 1 working day. "
                "This is a registration record, not an approval of the claim.</p>")
        sent = False
        for to in {policy.get("email"), os.environ.get("ADJUSTER_EMAIL")} - {None, ""}:
            try:
                ses_email.send_email(to, f"Claim {claim['claim_id']} registered", html, sender,
                                     os.environ.get("SES_CONFIG_SET", ""))
                sent = True
            except Exception as err:
                audit(claim["claim_id"], "system", "email_failed", "send_email", {"to": to, "error": str(err)})
        return sent

    def _latest_claim(self):
        items = self.claims.query(
            IndexName="phone-index", KeyConditionExpression="phone = :p",
            ExpressionAttributeValues={":p": self.phone}, ScanIndexForward=False).get("Items", [])
        items = [i for i in items if i.get("status") != "DRAFT"]
        return items[0] if items else None

    def t_get_claim_status(self) -> dict:
        claim = self._latest_claim()
        if not claim:
            return {"found": False}
        nxt = {"REGISTERED": "a surveyor will contact you within 1 working day",
               "SURVEY_SCHEDULED": f"surveyor visit on {claim.get('survey_date')} at {claim.get('survey_time')}",
               "ESCALATED": "an adjuster will call you shortly",
               "CLOSED": "no further action needed"}.get(claim["status"], "we will update you here")
        return {"found": True, "claim_id": claim["claim_id"], "status": claim["status"], "next_step": nxt}

    def t_escalate_to_adjuster(self, reason: str) -> dict:
        claim = self._latest_claim()
        key = claim["claim_id"] if claim else self.draft_id
        if claim:
            self.claims.update_item(Key={"claim_id": key}, UpdateExpression="SET #s = :s, escalation_reason = :r",
                                    ExpressionAttributeNames={"#s": "status"},
                                    ExpressionAttributeValues={":s": "ESCALATED", ":r": reason})
        self.flags["escalated"] = True
        sender, to = os.environ.get("SES_SENDER"), os.environ.get("ADJUSTER_EMAIL")
        if sender and to:
            try:
                ses_email.send_email(to, f"Escalation: {key}", f"<p>Customer {self.phone} needs a person.</p>"
                                     f"<p>Reason: {reason}</p>", sender, os.environ.get("SES_CONFIG_SET", ""))
            except Exception:
                pass
        audit(key, "agent", "escalated", "escalate_to_adjuster", {"reason": reason})
        return {"escalated": True, "claim_id": key if claim else None}
