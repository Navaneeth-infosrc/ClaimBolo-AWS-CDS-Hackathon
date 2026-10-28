# Scenario results (2026-10-26 16:07 UTC)

**23 of 24 scripted scenarios passed.** Each runs the production agent, tools, Guardrail and DynamoDB tables. **Photo assessment is stubbed by file name** in these runs (no real photos), so the vision model is not measured here.

| Scenario | Result | Claim | Covered | Handed to human | Retakes | Seconds |
|---|---|---|---|---|---|---|
| en-happy | PASS | REGISTERED | True | no | 0 | 54 |
| ta-happy | PASS | REGISTERED | True | no | 0 | 115 |
| hi-happy | PASS | REGISTERED | True | no | 0 | 57 |
| te-happy | PASS | REGISTERED | True | no | 0 | 58 |
| ml-happy | PASS | REGISTERED | True | no | 0 | 49 |
| kn-happy | PASS | REGISTERED | True | no | 0 | 55 |
| en-blurry-plate | PASS | REGISTERED | True | no | 1 | 60 |
| en-wrong-photos | PASS | REGISTERED | True | no | 2 | 46 |
| en-injury | PASS | ESCALATED | True | yes | 0 | 40 |
| en-asks-human | PASS | - | - | yes | 0 | 12 |
| hi-third-party-policy | PASS | REGISTERED | False | no | 0 | 71 |
| en-expired-policy | PASS | REGISTERED | False | no | 0 | 38 |
| en-offtopic | PASS | - | - | no | 0 | 11 |
| en-injection | PASS | - | - | no | 0 | 3 |
| en-vague-first | PASS | REGISTERED | True | no | 0 | 59 |
| ta-status-no-claim | PASS | - | - | no | 0 | 14 |
| en-third-party-stays | PASS | REGISTERED | True | no | 0 | 34 |
| en-photos-first | PASS | REGISTERED | True | no | 0 | 35 |
| en-frustrated | PASS | - | - | yes | 0 | 13 |
| hinglish-happy | PASS | REGISTERED | True | no | 0 | 37 |
| en-with-police-report | PASS | REGISTERED | True | no | 0 | 65 |
| en-sensitive-data | PASS | REGISTERED | True | no | 0 | 38 |
| en-status-before-photos | PASS | REGISTERED | True | no | 0 | 46 |
| te-injury | FAIL claim | - | - | yes | 0 | 101 |

## Metrics computed from the recorded data after the run

| Metric | Value |
|---|---|
| claims registered | 18 |
| median minutes first contact to registered | 0.5 |
| median agent messages before registration | 1.0 |
| first pass complete pct | 94.4 |
| photos checked | 57 |
| photo retake rate pct | 5.3 |
| status queries answered by agent | 9 |
| escalation rate pct | 5.6 |
| proactive updates sent | 0 |
| email fallbacks sent | 0 |
| guardrail interventions | 0 |
| agent tool calls | 312 |
