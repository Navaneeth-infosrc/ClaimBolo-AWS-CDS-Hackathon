import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rules.coverage import check_coverage, find_missing  # noqa: E402

POLICY = {"cover_type": "comprehensive", "deductible": 1000, "valid_from": "2026-01-01", "valid_to": "2026-12-31"}
GOOD = {"assessment": {"usable": True, "damage_visible": True, "plate_readable": True}}


def test_covered_comprehensive():
    r = check_coverage(POLICY, {"incident_date": "2026-10-23", "injuries": False, "third_party_involved": False})
    assert r["covered"] and r["deductible"] == 1000 and r["fast_track_eligible"] and not r["escalate"]


def test_third_party_only_is_not_covered_for_own_damage():
    r = check_coverage({**POLICY, "cover_type": "third_party"}, {"incident_date": "2026-10-23"})
    assert r["covered"] is False


def test_expired_policy():
    r = check_coverage(POLICY, {"incident_date": "2027-02-01"})
    assert r["covered"] is False and "not in force" in r["reasons"][0]


def test_injury_escalates():
    r = check_coverage(POLICY, {"incident_date": "2026-10-23", "injuries": True})
    assert r["escalate"] and not r["fast_track_eligible"]


def test_missing_date_is_undecided():
    assert check_coverage(POLICY, {})["covered"] is None


def test_missing_items_lists_photos_and_answers():
    missing = find_missing({"incident_date": "2026-10-23", "location": "OMR", "description": "x"}, [])
    assert any("damage_photos" in m for m in missing) and "injuries" in missing


def test_complete_claim_has_nothing_missing():
    facts = {"incident_date": "2026-10-23", "location": "OMR", "description": "x",
             "injuries": False, "third_party_involved": False}
    assert find_missing(facts, [GOOD, GOOD]) == []


def test_third_party_is_recorded_but_does_not_escalate():
    r = check_coverage(POLICY, {"incident_date": "2026-10-23", "injuries": False, "third_party_involved": True})
    assert r["covered"] and not r["escalate"] and r["fast_track_eligible"]
    assert any("third party" in c for c in r["conditions"])
