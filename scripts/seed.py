"""Seed fictional policies for the demo and the scenario tests (fictional insurer, fictional people).

Usage: python scripts/seed.py
  SEED_EMAIL  email stored on the policies (claim summaries go there)
  DEMO_PHONE  your own WhatsApp test number in E.164 form, to attach the comprehensive demo policy to it
"""
import os

import boto3

from settings import PREFIX, REGION
EMAIL = os.environ.get("SEED_EMAIL", "customer@example.com")
DEMO_PHONE = os.environ.get("DEMO_PHONE", "+919000000000")

POLICIES = [
    # The live demo customer: comprehensive, in force
    dict(phone=DEMO_PHONE, policy_no="KGI-MTR-2026-4821", holder_name="Murugan", vehicle="Maruti Swift",
         reg_no="TN09AB1234", cover_type="comprehensive", deductible=1000,
         valid_from="2026-01-01", valid_to="2026-12-31", email=EMAIL, preferred_lang="ta"),
    # Scenario-test customers
    dict(phone="+919000000001", policy_no="KGI-MTR-2026-1001", holder_name="Test One", vehicle="Hyundai i20",
         reg_no="KA01AA0001", cover_type="comprehensive", deductible=2000,
         valid_from="2026-01-01", valid_to="2026-12-31", email=EMAIL, preferred_lang="en"),
    dict(phone="+919000000002", policy_no="KGI-MTR-2026-1002", holder_name="Test Two", vehicle="Tata Nexon",
         reg_no="MH12BB0002", cover_type="third_party", deductible=0,
         valid_from="2026-01-01", valid_to="2026-12-31", email=EMAIL, preferred_lang="hi"),
    dict(phone="+919000000003", policy_no="KGI-MTR-2025-1003", holder_name="Test Three", vehicle="Honda City",
         reg_no="DL08CC0003", cover_type="comprehensive", deductible=1500,
         valid_from="2025-01-01", valid_to="2025-12-31", email=EMAIL, preferred_lang="en"),
]

table = boto3.resource("dynamodb", region_name=REGION).Table(f"{PREFIX}-policies")
for p in POLICIES:
    table.put_item(Item=p)
    print("seeded", p["phone"], p["holder_name"], p["cover_type"])
