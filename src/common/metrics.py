"""Impact metrics computed from what the system actually recorded (claims, conversation log, audit trail)."""
import statistics
from datetime import datetime

from common.util import table, to_jsonable


def _scan(name: str) -> list:
    t, items, kwargs = table(name), [], {}
    while True:
        page = t.scan(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.split("#")[0])


def compute() -> dict:
    claims = [to_jsonable(c) for c in _scan("CLAIMS_TABLE") if str(c["claim_id"]).startswith("CLM-")]
    conversations = [to_jsonable(c) for c in _scan("CONVERSATIONS_TABLE")]
    audit = [to_jsonable(a) for a in _scan("AUDIT_TABLE")]

    out_by_phone = {}
    for row in conversations:
        if row["direction"] == "OUT" and not row.get("proactive"):
            out_by_phone.setdefault(row["phone"], []).append(row["ts"])

    durations, followups = [], []
    for c in claims:
        start, end = c.get("first_contact_at"), c.get("registered_at")
        if not (start and end):
            continue
        durations.append((_ts(end) - _ts(start)).total_seconds())
        followups.append(sum(1 for ts in out_by_phone.get(c["phone"], [])
                             if _ts(start) <= _ts(ts) <= _ts(end)))

    photos = [p.get("assessment", {}) for c in claims for p in c.get("photos", [])]
    unusable = sum(1 for a in photos if not a.get("usable"))
    tools_used = [a.get("tool") for a in audit if a.get("action") == "tool_call"]
    total = len(claims)

    def pct(n, d):
        return round(100 * n / d, 1) if d else None

    return {
        "claims_registered": total,
        "median_minutes_first_contact_to_registered": round(statistics.median(durations) / 60, 1) if durations else None,
        "median_agent_messages_before_registration": statistics.median(followups) if followups else None,
        "first_pass_complete_pct": pct(sum(1 for f in followups if f <= 2), len(followups)),
        "photos_checked": len(photos),
        "photo_retake_rate_pct": pct(unusable, len(photos)),
        "status_queries_answered_by_agent": tools_used.count("get_claim_status"),
        "escalation_rate_pct": pct(sum(1 for c in claims if c.get("status") == "ESCALATED"), total),
        "proactive_updates_sent": sum(1 for a in audit if a.get("action") == "proactive_update_sent"),
        "email_fallbacks_sent": sum(1 for a in audit if a.get("action") == "email_fallback_sent"),
        "guardrail_interventions": sum(1 for a in audit if str(a.get("action", "")).startswith("guardrail_blocked")),
        "agent_tool_calls": len(tools_used),
    }
