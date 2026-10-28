# ClaimBolo

**Report an insurance claim the way you already talk: a WhatsApp voice note, in your language.**

ClaimBolo is a voice-first, multilingual claims agent for small insurers, TPAs and MGAs. A customer sends a WhatsApp voice note or text describing a motor accident. An AI agent understands it, looks up the policy, asks only for what is missing, checks the photos, registers the claim, emails a formal record, and keeps the customer updated. Adjusters get one complete case file. **Humans decide; the agent prepares.** It never approves, rejects or values a claim.

Built for the AWS Communication Developer Services (CDS) Agentic AI Partner Hackathon. All data in this project is fictional ("Kaveri General Insurance" is a made-up insurer).

## Problem

Small insurers lose time and trust at the first step of every claim. Reporting is phone- or form-based and English-first, so claims arrive incomplete, documents are chased by hand, and customers are left without updates. ClaimBolo lets customers report claims the way they already communicate, while the agent turns that conversation into a complete, verified claim file.

## What it does

| Step | What happens | AWS services |
|---|---|---|
| 1 | Customer sends a WhatsApp voice note, text or photo | **AWS End User Messaging Social (WhatsApp)** → SNS |
| 2 | Voice note is downloaded and transcribed with automatic language detection (Tamil, Hindi, English, Telugu, Malayalam, Kannada) | `GetWhatsAppMessageMedia` → S3 → **Amazon Transcribe** |
| 3 | The agent looks up the policy, extracts facts, and asks only for what is missing | **Amazon Bedrock AgentCore Runtime** hosts the agent (Bedrock tool-use loop), DynamoDB |
| 4 | Each photo is checked for usable damage and a readable number plate; a blurry plate triggers a retake request | **Bedrock vision** |
| 5 | Coverage comes from a **deterministic rules engine**, never the model | Lambda |
| 6 | Claim registered; customer gets the result in their language with a "Talk to a person" button | `SendWhatsAppMessage` (text and interactive) |
| 7 | A formal claim summary is emailed, and the adjuster is notified | **Amazon SES** (`SendEmail`) |
| 8 | Adjuster opens the case file and schedules a survey; the customer gets an unprompted update | EventBridge → WhatsApp (free text inside the 24h window, approved template outside it) → SES fallback |
| 9 | The agent remembers each customer's language and preferences across conversations | **Amazon Bedrock AgentCore Memory** |

Safety: **Bedrock Guardrails** (prompt attacks, medical/legal advice, payout promises, PII), a hard rule set in the agent prompt, automatic escalation (injuries, anger, request for a person, repeated failures), and an audit record of every tool call.

## AWS CDS integration (where to look)

These are the files that import and call the qualifying CDS SDK clients:

| Service | Client | File | Operations used |
|---|---|---|---|
| WhatsApp | `boto3.client("socialmessaging")` | [src/cds/whatsapp.py](src/cds/whatsapp.py) | `send_whatsapp_message` (text, interactive buttons, templates), `get_whatsapp_message_media` |
| Email | `boto3.client("sesv2")` | [src/cds/email.py](src/cds/email.py) | `send_email` (with a configuration set for delivery events) |

Inbound WhatsApp events arrive on an SNS topic and are handled by [src/handlers/inbound.py](src/handlers/inbound.py) (idempotent by message id).

## Architecture

![ClaimBolo architecture](docs/architecture.png)

Details and flows: [docs/architecture.md](docs/architecture.md).

```
WhatsApp ⇄ EUM Social ─► SNS ─► inbound Lambda ─► S3 (KMS) ─► Transcribe ─► transcribe-complete Lambda
                                       │                                          │
                                       └──────────────► agent Lambda ◄────────────┘   (channel I/O, memory)
                                                          │ InvokeAgentRuntime
                                                  AgentCore Runtime: Guardrails + Bedrock tool-use loop
                                                  tools: policy · facts · missing items · photo check · coverage rules
                                                         · create claim · status · escalate     (DynamoDB, audited)
                                                          │                         │
                                       WhatsApp reply ◄───┘                         └──► SES claim email
Adjuster page (Lambda URL) ─► status change ─► EventBridge ─► proactive Lambda ─► WhatsApp / SES fallback
```

Everything is defined in AWS CDK (Python) under [infrastructure/](infrastructure/). Every resource name starts with a configurable prefix (`CLAIMBOLO_PREFIX`) and carries `Project`, `Owner`, `Purpose` and `ExpiresAfter` tags.

## Try it (for judges)

1. Open WhatsApp and message the ClaimBolo demo number given in the Devpost testing instructions. Send "hi", or a voice note, or a typed description of a car accident, in English, Tamil, Hindi, Telugu, Malayalam or Kannada.
2. **Demo mode is on:** a number with no policy automatically receives a fictional comprehensive policy, and the agent says so. Describe the accident (date, place, any injuries, other vehicle), then send **2 photos of vehicle damage and 1 photo of a number plate**.
3. When the claim is registered you get a claim id (`CLM-…`) and a coverage explanation, and an email goes to the demo adjuster inbox.
4. Type "status?" at any time for the current status.
5. The adjuster view is protected by a key shared with judges through the Devpost "testing instructions" field (it is not in this repository).

If WhatsApp is unavailable to you, [docs/SCENARIO_RESULTS.md](docs/SCENARIO_RESULTS.md) lists 24 scripted conversations run through the production agent, and `python scripts/chat_local.py +919000000001 "<message>"` runs a single message through the deployed agent.

## Deploy

Prerequisites: an AWS account (us-east-1), Python 3.11+, Node 20+, AWS credentials in your environment, a WhatsApp Business Account linked in the **End User Messaging Social** console, and a verified Amazon SES sender.

```bash
cd infrastructure
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example ../.env   # fill in WHATSAPP_PHONE_NUMBER_ID, MODEL_ID, SES_SENDER, ... then export the variables
npx aws-cdk@latest bootstrap
npx aws-cdk@latest deploy --require-approval never
```

After deploying:
1. Point the WhatsApp event destination at the SNS topic named `…-whatsapp-inbound` (printed in the stack outputs).
2. Seed demo policies (from the repository root): `python scripts/seed.py`. Set `DEMO_PHONE` to your own WhatsApp test number to attach the demo policy to it.
3. Read the adjuster key from Secrets Manager (`…-adjuster-key`) and open the `AdjusterUrl` output with `?k=<key>`.

Clean up with `npx aws-cdk@latest destroy`. Every resource carries an `ExpiresAfter` tag.

## Testing and measured results

- `python -m pytest tests` runs the coverage-rule unit tests (no AWS needed).
- `python scripts/run_scenarios.py` replays 24 scripted conversations (six languages, blurry and wrong photos, injuries, prompt injection, sensitive data, expired and third-party-only policies) through the real agent, Guardrail and tables, then writes [docs/SCENARIO_RESULTS.md](docs/SCENARIO_RESULTS.md). **Photo assessment is stubbed by file name in these runs**, so they do not measure the vision model.
- The adjuster page has an **Impact metrics** view computed from the recorded claims, conversation log and audit trail.

No impact number in this repository is estimated. Any business-value statement is labelled as a hypothesis.

## Security and privacy

- All data is fictional. Media and tables are encrypted with a customer-managed KMS key; the media bucket is private and files expire after 30 days.
- Least-privilege IAM per Lambda; secrets in Secrets Manager; no credentials in this repository.
- The agent cannot read another customer's data: every tool is bound to the sender's own phone number.
- Coverage decisions are rules, not model output. The agent never states approval, rejection or a payout amount.
- Details: [docs/SECURITY.md](docs/SECURITY.md).

## Known limitations

- Motor own-damage claims only. The policy system is a mock behind a table; a real insurer needs an adapter.
- **WhatsApp message templates were submitted to Meta and were still pending review when this was written**, so the out-of-window path is described, not demonstrated. Inside the 24-hour window the update is sent as free text.
- Languages other than Tamil and English have been tested with typed messages only. Voice in Hindi, Telugu, Malayalam and Kannada is configured but untested. Tamil, Hindi, Telugu, Malayalam and Kannada wording has not been reviewed by native speakers.
- The agent runs on **AgentCore Runtime** (code package, a Bedrock tool-use loop written directly against the Converse API, not the Strands library) and uses **AgentCore Memory**. **AgentCore Gateway is not used**; the tools run inside the runtime. If the runtime call fails, the Lambda runs the same agent code locally as a fallback.
- Built and demonstrated in us-east-1. A Mumbai (ap-south-1) deployment is a design option that has not been test-deployed.
- Demo mode creates a fictional policy for unknown numbers. Turn it off (`DEMO_MODE=false`) for any real use.

## Development and disclosure

Started 15 Oct 2026 (after the 14 Sep start of the submission period). See [docs/DEVELOPMENT_TIMELINE.md](docs/DEVELOPMENT_TIMELINE.md) and [docs/PREEXISTING_CODE_DISCLOSURE.md](docs/PREEXISTING_CODE_DISCLOSURE.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
