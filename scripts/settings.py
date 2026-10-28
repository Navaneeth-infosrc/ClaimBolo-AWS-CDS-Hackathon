"""Settings shared by the helper scripts. Use the same values you deployed with (see .env.example)."""
import os

PREFIX = os.environ.get("CLAIMBOLO_PREFIX", "claimbolo")
REGION = os.environ.get("AWS_REGION", "us-east-1")
