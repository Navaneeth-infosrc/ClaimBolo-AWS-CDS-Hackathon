"""Clear one customer's conversation, draft and claims so a demo or test starts from a clean state.

Usage: python scripts/reset_demo.py +919000000000
Deletes rows for that phone number only. The audit trail is kept.
"""
import sys

import boto3

from settings import PREFIX, REGION

phone = "+" + "".join(c for c in sys.argv[1] if c.isdigit())
ddb = boto3.resource("dynamodb", region_name=REGION)

conversations = ddb.Table(f"{PREFIX}-conversations")
rows = conversations.query(KeyConditionExpression="phone = :p", ExpressionAttributeValues={":p": phone})["Items"]
for r in rows:
    conversations.delete_item(Key={"phone": r["phone"], "ts": r["ts"]})

claims = ddb.Table(f"{PREFIX}-claims")
items = claims.query(IndexName="phone-index", KeyConditionExpression="phone = :p",
                     ExpressionAttributeValues={":p": phone})["Items"]
for c in items:
    claims.delete_item(Key={"claim_id": c["claim_id"]})
print(f"{phone}: removed {len(rows)} messages and {len(items)} claim/draft records")
