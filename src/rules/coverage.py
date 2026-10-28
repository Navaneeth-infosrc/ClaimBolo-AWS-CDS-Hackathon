"""Deterministic coverage rules. The model explains the result; it never decides it."""
from datetime import date


def _parse(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def check_coverage(policy: dict, facts: dict) -> dict:
    """Return {covered, deductible, conditions, escalate, escalation_reasons, fast_track_eligible, reasons}.

    covered is None when the facts needed to decide are missing.
    """
    reasons, conditions, escalation = [], [], []
    incident = _parse(facts.get("incident_date"))
    valid_from, valid_to = _parse(policy.get("valid_from")), _parse(policy.get("valid_to"))

    if incident is None:
        return {"covered": None, "reasons": ["incident date is missing or unreadable"],
                "conditions": [], "escalate": False, "escalation_reasons": [],
                "fast_track_eligible": False, "deductible": policy.get("deductible")}

    covered = True
    if valid_from and valid_to and not (valid_from <= incident <= valid_to):
        covered = False
        reasons.append("the policy was not in force on the incident date")
    if policy.get("cover_type") != "comprehensive":
        covered = False
        reasons.append("own-damage cover is not part of this policy (third-party only)")

    if covered:
        conditions.append("subject to the surveyor's assessment")
        conditions.append("the deductible applies")

    if facts.get("injuries") is True:
        escalation.append("injury reported")
    if facts.get("third_party_involved") is True:
        # Registered as normal; the surveyor is told so they can note the other party's details
        conditions.append("third party involved: the surveyor will record the other party's details")
    if facts.get("police_report") is True:
        conditions.append("keep a copy of the police report for the surveyor")

    return {
        "covered": covered,
        "deductible": policy.get("deductible"),
        "conditions": conditions,
        "reasons": reasons,
        "escalate": bool(escalation),
        "escalation_reasons": escalation,
        "fast_track_eligible": covered and not escalation,
    }


REQUIRED_FACTS = ("incident_date", "location", "description")
REQUIRED_ANSWERS = ("injuries", "third_party_involved")
MIN_DAMAGE_PHOTOS = 2
MIN_PLATE_PHOTOS = 1


def find_missing(facts: dict, photos: list) -> list:
    """List what is still needed before a claim can be registered."""
    missing = [f for f in REQUIRED_FACTS if not facts.get(f)]
    missing += [f for f in REQUIRED_ANSWERS if facts.get(f) is None]
    good = [p["assessment"] for p in photos if p.get("assessment", {}).get("usable")]
    damage = sum(1 for a in good if a.get("damage_visible"))
    plate = sum(1 for a in good if a.get("plate_readable"))
    if damage < MIN_DAMAGE_PHOTOS:
        missing.append(f"damage_photos (need {MIN_DAMAGE_PHOTOS - damage} more clear photo(s) of the damage)")
    if plate < MIN_PLATE_PHOTOS:
        missing.append("number_plate_photo (a clear, readable photo of the number plate)")
    return missing
