"""Amazon Bedrock AgentCore Memory: continuity across conversations.

Every message is written as an event. AgentCore extracts durable facts (language, preferences) and
per-session summaries in the background, and the agent reads them back at the start of a new
conversation. A memory failure must never break a claim, so every call is best-effort.
"""
import logging
import os
from datetime import datetime, timezone

import boto3

from common.util import digits

log = logging.getLogger()
_client = boto3.client("bedrock-agentcore")
MEMORY_ID = os.environ.get("MEMORY_ID", "")


def _session(phone: str) -> str:
    return f"{digits(phone)}-{datetime.now(timezone.utc):%Y%m%d}"


def record(phone: str, role: str, text: str) -> None:
    """role is 'USER' or 'ASSISTANT'."""
    if not MEMORY_ID or not text.strip():
        return
    try:
        _client.create_event(
            memoryId=MEMORY_ID,
            actorId=digits(phone),
            sessionId=_session(phone),
            eventTimestamp=datetime.now(timezone.utc),
            payload=[{"conversational": {"role": role, "content": {"text": text[:9000]}}}],
        )
    except Exception as err:
        log.warning("memory record failed: %s", err)


def recall(phone: str, query: str, top_k: int = 4) -> list:
    """Facts remembered about this customer from earlier conversations."""
    if not MEMORY_ID:
        return []
    actor, found = digits(phone), []
    namespaces = [f"/users/{actor}/preferences"]
    try:  # retrieval needs exact namespaces, so add the summary namespace of each recent session
        sessions = _client.list_sessions(memoryId=MEMORY_ID, actorId=actor, maxResults=3)["sessionSummaries"]
        namespaces += [f"/summaries/{actor}/{s['sessionId']}" for s in sessions]
    except Exception as err:
        log.warning("memory list_sessions failed: %s", err)
    for namespace in namespaces:
        try:
            resp = _client.retrieve_memory_records(
                memoryId=MEMORY_ID, namespace=namespace,
                searchCriteria={"searchQuery": query[:500] or "customer", "topK": top_k})
            found += [r["content"]["text"] for r in resp.get("memoryRecordSummaries", [])]
        except Exception as err:
            log.warning("memory recall failed for %s: %s", namespace, err)
    return found
