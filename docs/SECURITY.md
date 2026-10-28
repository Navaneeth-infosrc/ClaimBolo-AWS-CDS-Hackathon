# Security notes

- **Data:** fictional only. Tables and the media bucket use a customer-managed KMS key; the media bucket blocks public access and expires objects after 30 days. `processed-messages` entries expire automatically.
- **Access:** one IAM role per Lambda with only the actions it needs. The adjuster page requires a key held in Secrets Manager and uses short-lived pre-signed links for photos.
- **Isolation:** each agent tool is constructed with the sender's phone number; the model cannot choose another customer's number.
- **AI safety:** deterministic coverage rules; the agent may not state approval, rejection or a payout; Bedrock Guardrails block prompt attacks, medical/legal advice and payout promises and mask PII; a human is always offered; injuries, anger, or a request for a person escalate.
- **Audit:** every tool call is stored with actor, tool and arguments.
- **Secrets:** none in this repository. `.env.example` has placeholders only. Run `git secrets --install --register-aws && git secrets --scan && git secrets --scan-history` before publishing.
- **Demo mode** (`DEMO_MODE=true`) gives unknown numbers a fictional policy so judges can try the flow. Disable it in production.
- **Known gaps:** the adjuster page uses a shared key, not user accounts (Cognito is a roadmap item). Sensitive-data masking is verified only by the scripted scenario that sends an Aadhaar and account number.
