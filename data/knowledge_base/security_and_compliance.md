# Security, Privacy & Compliance

## Encryption & Data Residency
- All data in transit is encrypted with TLS 1.3; data at rest uses AES-256 encryption with per-tenant KMS keys.
- Regional data residency options include India (Mumbai ap-south-1), EU (Frankfurt), and US (Virginia).
- Zero-retention LLM inference guarantees: customer transcripts and CRM fields are never used to train foundation models.

## Compliance Certifications
- SOC 2 Type II audited annually and ISO 27001 certified.
- GDPR and India DPDP Act 2023 compliant with automated PII redaction (emails, card numbers, Aadhaar/PAN masking) before logging.
- Role-Based Access Control (RBAC), audit trails for every API call, and SAML 2.0 SSO (Okta, Azure AD, Google Workspace).
