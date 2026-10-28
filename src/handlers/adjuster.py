"""Adjuster web view (Lambda function URL). Humans decide here; the agent only prepares the file."""
import base64
import html
import json
import os
import urllib.parse
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config

from common import metrics
from common.util import audit, now_iso, table, to_jsonable

_events = boto3.client("events")
_s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
_secrets = boto3.client("secretsmanager")
_key_cache = {}

CSS = """body{font-family:system-ui,sans-serif;margin:0;background:#f5f6f8;color:#1c2330}
header{background:#14365d;color:#fff;padding:14px 24px}main{max-width:1000px;margin:0 auto;padding:20px}
table{border-collapse:collapse;width:100%;background:#fff}td,th{padding:8px 10px;border-bottom:1px solid #e3e6eb;text-align:left;vertical-align:top}
.card{background:#fff;border-radius:8px;padding:16px;margin-bottom:16px;box-shadow:0 1px 2px #0002}
.tag{display:inline-block;background:#e8eefc;border-radius:10px;padding:1px 8px;margin:1px;font-size:12px}
.ok{color:#17803d}.bad{color:#b42318}img{max-width:220px;border-radius:6px;margin:4px}
.in{background:#eef3ff}.out{background:#eefaf0}.msg{padding:6px 10px;margin:4px 0;border-radius:6px}
button{background:#14365d;color:#fff;border:0;border-radius:6px;padding:8px 14px;cursor:pointer}a{color:#14365d}"""


IST = timezone(timedelta(hours=5, minutes=30))


def _tomorrow() -> str:
    return (datetime.now(IST) + timedelta(days=1)).strftime("%Y-%m-%d")


def _pretty(date_value: str, time_value: str):
    """Form values (2026-10-27, 10:00) -> customer-friendly (27-10-2026, 10:00 AM)."""
    try:
        d = datetime.strptime(date_value, "%Y-%m-%d").strftime("%d-%m-%Y")
        t = datetime.strptime(time_value, "%H:%M").strftime("%I:%M %p").lstrip("0")
        return d, t
    except ValueError:
        return date_value, time_value


def _e(value) -> str:
    return html.escape(str(value if value is not None else ""))


def _secret() -> str:
    if "k" not in _key_cache:
        _key_cache["k"] = _secrets.get_secret_value(SecretId=os.environ["ADJUSTER_SECRET_ARN"])["SecretString"]
    return _key_cache["k"]


def _page(title: str, body: str, status: int = 200) -> dict:
    doc = (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>{_e(title)}</title><style>{CSS}</style></head><body><header><b>ClaimBolo</b> · adjuster view</header>"
           f"<main>{body}</main></body></html>")
    return {"statusCode": status, "headers": {"content-type": "text/html; charset=utf-8"}, "body": doc}


METRIC_LABELS = [
    ("claims_registered", "Claims registered"),
    ("median_minutes_first_contact_to_registered", "Median minutes, first message to registered claim"),
    ("median_agent_messages_before_registration", "Median agent messages before registration"),
    ("first_pass_complete_pct", "Claims registered within 2 agent messages (%)"),
    ("photos_checked", "Photos checked by the vision model"),
    ("photo_retake_rate_pct", "Photos flagged unusable (%)"),
    ("status_queries_answered_by_agent", "Status questions answered by the agent"),
    ("escalation_rate_pct", "Claims handed to a human (%)"),
    ("proactive_updates_sent", "Proactive updates sent"),
    ("email_fallbacks_sent", "Email fallbacks sent"),
    ("guardrail_interventions", "Guardrail interventions"),
    ("agent_tool_calls", "Agent tool calls (all audited)"),
]


def _metrics(k: str) -> dict:
    data = metrics.compute()
    cards = "".join(f"<div class='card' style='display:inline-block;min-width:200px;margin-right:12px'>"
                    f"<div style='font-size:26px;font-weight:600'>{_e(data[key])}</div><small>{_e(label)}</small></div>"
                    for key, label in METRIC_LABELS)
    return _page("Impact metrics", f"<p><a href='?k={_e(k)}'>&larr; all claims</a></p><h2>Impact metrics</h2>{cards}"
                                   "<p><small>Computed live from the claims, conversation log and audit trail. "
                                   "Includes scripted test runs; see docs/SCENARIO_RESULTS.md for how they were produced.</small></p>")


def _list(k: str) -> dict:
    items = [i for i in table("CLAIMS_TABLE").scan()["Items"] if str(i["claim_id"]).startswith("CLM-")]
    items.sort(key=lambda i: i.get("created_at", ""), reverse=True)
    rows = "".join(
        f"<tr><td><a href='?view=claim&id={_e(i['claim_id'])}&k={_e(k)}'>{_e(i['claim_id'])}</a></td>"
        f"<td>{_e(i.get('holder_name'))}</td><td>{_e(i.get('vehicle'))}</td><td>{_e(i['status'])}</td>"
        f"<td>{_e(i.get('coverage', {}).get('covered'))}</td><td>{_e(i.get('language'))}</td></tr>" for i in items)
    return _page("Claims", f"<p><a href='?view=metrics&k={_e(k)}'>Impact metrics &rarr;</a></p><h2>Claims</h2><table><tr><th>Claim</th><th>Customer</th><th>Vehicle</th>"
                           f"<th>Status</th><th>Covered</th><th>Lang</th></tr>{rows}</table>")


def _detail(claim_id: str, k: str) -> dict:
    claim = table("CLAIMS_TABLE").get_item(Key={"claim_id": claim_id}).get("Item")
    if not claim:
        return _page("Not found", "<p>Claim not found.</p>", 404)
    claim = to_jsonable(claim)
    facts, cov = claim.get("facts", {}), claim.get("coverage", {})
    facts_html = "".join(f"<tr><td><b>{_e(f)}</b></td><td>{_e(v)}</td></tr>" for f, v in facts.items())
    photos = ""
    for p in claim.get("photos", []):
        a = p.get("assessment", {})
        url = _s3.generate_presigned_url("get_object", ExpiresIn=900,
                                         Params={"Bucket": os.environ["MEDIA_BUCKET"], "Key": p["s3_key"]})
        tags = "".join(f"<span class='tag'>{_e(t)}</span>" for t in a.get("tags", []))
        flag = "ok" if a.get("usable") else "bad"
        photos += (f"<div style='display:inline-block;vertical-align:top'><img src='{_e(url)}'><br>"
                   f"<span class='{flag}'>{'usable' if a.get('usable') else 'unusable'}</span> "
                   f"damage={_e(a.get('damage_visible'))} plate={_e(a.get('plate_readable'))} "
                   f"plate matches policy={_e(a.get('plate_matches_policy'))}<br>{tags}<br><small>{_e(a.get('reason'))}</small></div>")
    convo = ""
    for r in table("CONVERSATIONS_TABLE").query(
            KeyConditionExpression=Key("phone").eq(claim["phone"]), ScanIndexForward=False, Limit=40)["Items"][::-1]:
        convo += f"<div class='msg {'in' if r['direction'] == 'IN' else 'out'}'><small>{_e(r['ts'][:19])}</small> {_e(r.get('original_text', '[' + r.get('type', '') + ']'))}</div>"
    trail = ""
    for r in table("AUDIT_TABLE").query(KeyConditionExpression=Key("claim_id").eq(claim_id))["Items"]:
        trail += f"<tr><td>{_e(r['ts'][:19])}</td><td>{_e(r['actor'])}</td><td>{_e(r['action'])}</td><td>{_e(r.get('tool'))}</td></tr>"
    body = (
        f"<p><a href='?k={_e(k)}'>&larr; all claims</a></p><h2>{_e(claim_id)} · {_e(claim['status'])}</h2>"
        f"<div class='card'><b>{_e(claim.get('holder_name'))}</b> · {_e(claim.get('vehicle'))} ({_e(claim.get('reg_no'))}) · "
        f"policy …{_e(str(claim.get('policy_no'))[-4:])} · language {_e(claim.get('language'))}<br>"
        f"Coverage rule result: covered={_e(cov.get('covered'))}, deductible={_e(cov.get('deductible'))}, "
        f"escalate={_e(cov.get('escalate'))} {_e(', '.join(cov.get('escalation_reasons', [])))}<br>"
        f"<small>The agent prepared this file. Coverage comes from deterministic rules. A human decides the claim.</small></div>"
        f"<div class='card'><h3>Facts (English)</h3><table>{facts_html}</table></div>"
        f"<div class='card'><h3>Photos</h3>{photos or 'none'}</div>"
        f"<div class='card'><h3>Actions</h3><form method='post'><input type='hidden' name='k' value='{_e(k)}'>"
        f"<input type='hidden' name='id' value='{_e(claim_id)}'>"
        f"Survey date <input type='date' name='date' value='{_tomorrow()}' required> "
        f"time <input type='time' name='time' value='10:00' required> "
        f"<button name='action' value='schedule'>Schedule survey</button> "
        f"<button name='action' value='close'>Close claim</button></form></div>"
        f"<div class='card'><h3>Conversation</h3>{convo}</div>"
        f"<div class='card'><h3>Audit trail</h3><table>{trail}</table></div>")
    return _page(claim_id, body)


def _act(form: dict) -> dict:
    claim_id, action = form["id"], form["action"]
    claims = table("CLAIMS_TABLE")
    claim = claims.get_item(Key={"claim_id": claim_id})["Item"]
    detail = {"claim_id": claim_id, "phone": claim["phone"], "language": claim.get("language", "en")}
    if action == "schedule":
        survey_date, survey_time = _pretty(form["date"], form["time"])
        claims.update_item(Key={"claim_id": claim_id},
                           UpdateExpression="SET #s = :s, survey_date = :d, survey_time = :t, updated_at = :u",
                           ExpressionAttributeNames={"#s": "status"},
                           ExpressionAttributeValues={":s": "SURVEY_SCHEDULED", ":d": survey_date, ":t": survey_time, ":u": now_iso()})
        detail.update(status="SURVEY_SCHEDULED", survey_date=survey_date, survey_time=survey_time)
    else:
        claims.update_item(Key={"claim_id": claim_id}, UpdateExpression="SET #s = :s, updated_at = :u",
                           ExpressionAttributeNames={"#s": "status"},
                           ExpressionAttributeValues={":s": "CLOSED", ":u": now_iso()})
        detail.update(status="CLOSED")
    audit(claim_id, "human:adjuster", f"status_changed_to_{detail['status']}")
    _events.put_events(Entries=[{"Source": "claimbolo", "DetailType": "ClaimStatusChanged",
                                 "Detail": json.dumps(detail)}])
    return {"statusCode": 303, "headers": {"location": f"?view=claim&id={claim_id}&k={form['k']}"}, "body": ""}


def handler(event, context):
    method = event["requestContext"]["http"]["method"]
    query = event.get("queryStringParameters") or {}
    form = {}
    if method == "POST":
        raw = event.get("body") or ""
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode()
        form = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
    key = form.get("k") or query.get("k", "")
    if key != _secret():
        return _page("Access", "<p>Access key required: add <code>?k=…</code> to the address.</p>", 401)
    if method == "POST":
        return _act(form)
    if query.get("view") == "claim":
        return _detail(query["id"], key)
    if query.get("view") == "metrics":
        return _metrics(key)
    return _list(key)
