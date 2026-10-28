#!/usr/bin/env python3
"""ClaimBolo CDK app. All settings come from environment variables; see ../.env.example."""
import os

import aws_cdk as cdk

from stacks.foundation_stack import FoundationStack

PREFIX = os.environ.get("CLAIMBOLO_PREFIX", "claimbolo")

app = cdk.App()

FoundationStack(
    app,
    f"{PREFIX}-foundation",
    prefix=PREFIX,
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    ),
    description="ClaimBolo foundation: encryption key, media bucket, WhatsApp event topic, data tables, email events",
)

# Applied to every taggable resource in every stack
for key, value in {
    "Project": PREFIX,
    "Owner": os.environ.get("CLAIMBOLO_OWNER", "claimbolo-team"),
    "Purpose": "aws-cds-hackathon",
    "ExpiresAfter": os.environ.get("CLAIMBOLO_EXPIRES_AFTER", "2026-11-20"),
}.items():
    cdk.Tags.of(app).add(key, value)

app.synth()
