# RadFlow Data Security Gap Assessment

Last updated: 2026-04-02
Owner: Product/Engineering
Status: Working assessment

## Purpose
This document summarizes the current data security position of RadFlow, identifies the main gaps, and outlines the priority actions required before handling live patient-identifiable data at production scale.

It is intended as a practical internal assessment, not as formal legal, regulatory, or clinical safety sign-off.

## 1. Executive Summary
RadFlow currently has a reasonable prototype-level security baseline, but it is not yet at a mature healthcare-production standard for live patient-identifiable workflows.

Strengths already present:
- Password hashing with PBKDF2-HMAC-SHA256 and per-user salts.
- Session timeout and role-based access control.
- Azure Blob / Azure PostgreSQL compatible deployment model.
- Basic audit/event concepts in the application data model.

Current risk position:
- Suitable for controlled development, demo, and pilot hardening work.
- Not yet suitable to position as fully security-hardened for live NHS-scale patient data use without remediation.

## 2. Current Security Baseline
### Authentication and access
- Passwords are hashed using PBKDF2-HMAC-SHA256.
- Session-based authentication is implemented.
- Session timeout is configured for 20 minutes of inactivity.
- Role-based access checks exist for admin, radiologist, and superuser paths.

### Data storage
- Database can run on SQLite locally or PostgreSQL in hosted environments.
- Attachments can be stored locally or in Azure Blob Storage.
- Basic retention handling exists for uploaded referral files.

### Email and transport
- SMTP supports STARTTLS when configured.
- Azure hosting can provide HTTPS/TLS externally if configured correctly.

### Auditability
- Case events and audit log tables exist in the schema.
- Timeline and export capabilities exist for case history output.

## 3. Key Security Gaps
### Critical / high-priority gaps
- Production secret fallback remains unsafe. `APP_SECRET` defaults to `dev-secret-change-me` if not set.
- Owner admin bootstrap uses a default fallback password (`Polonez1`) if the environment variable is missing.
- Diagnostic schema endpoint is exposed and leaks internal structure.
- If SMTP is not configured, email content may be printed to logs.

### Data protection gaps
- No application-level encryption for patient identifiers or attachments.
- Local filesystem fallback for attachments is not an appropriate production pattern for sensitive healthcare data.
- No documented field-level encryption strategy for especially sensitive values.
- No formal key management approach is documented in the repository.

### Web/application hardening gaps
- Session cookie hardening is incomplete; secure-cookie enforcement is not clearly enabled.
- No clear HTTPS redirect / HSTS enforcement is implemented in app code.
- No explicit CSRF protection is present for form submissions.
- Rate limiting is in-memory only and not suitable as a robust cloud control.

### Governance and assurance gaps
- No formal DPIA in the repository.
- No formal data flow map or Record of Processing Activities in the repository.
- No documented incident response, breach response, or security operations runbook.
- No completed clinical safety evidence set is present for DCB0129.
- No completed DTAC evidence pack is present.

## 4. Encryption Position Today
### Passwords
- Passwords are hashed, not encrypted.
- This is correct for credentials.

### Data in transit
- Browser-to-app encryption depends on Azure/App Service configuration rather than strong application enforcement.
- SMTP uses STARTTLS when configured, but email is not itself a safe primary exchange mechanism for patient data unless the end-to-end secure email standard is met.

### Data at rest
- Azure PostgreSQL and Azure Blob Storage normally provide platform encryption at rest when used in production.
- Local SQLite and local file storage are still available in the app and are not an acceptable long-term production model for sensitive live healthcare data.

### Application-level encryption
- There is no evidence of:
- field-level encryption for patient identifiers
- document encryption before storage
- envelope encryption with managed keys
- key rotation policy in code or documentation

## 5. How the User-Supplied Encryption Requirements Apply
The requirements provided are broadly sensible, but they mix US/HIPAA language with more general security practice. For a UK/NHS-facing product, the principles still largely apply, but the legal framing is different.

### Encryption at rest
Applies strongly to RadFlow.
- Patient data in the database and attachments in storage should be encrypted at rest.
- In Azure, this should be achieved through managed services and documented configuration.
- For high-risk data, consider field-level encryption in addition to platform encryption.

### Encryption in transit
Applies strongly to RadFlow.
- All browser, API, admin, and integration traffic should use TLS 1.2+.
- HTTPS should be mandatory in production.
- Email intake should only be used where the mailbox and service path meet the NHS secure email standard.

### Cryptographic standards
Applies strongly to RadFlow.
- Use modern TLS only.
- Use current NIST-aligned / industry-standard cryptography through platform services.
- Avoid older protocols and weak ciphers.

### Key management
Applies strongly to RadFlow.
- Secrets and keys should not live in code defaults.
- Keys and secrets should be stored in Azure Key Vault or equivalent.
- Rotation, access control, and audit should be defined.

### Database encryption / TDE
Applies in principle.
- In Azure PostgreSQL, platform-managed encryption at rest is the relevant control rather than RadFlow implementing raw cryptography itself.
- The important point is to document the production database encryption model and key management approach.

### Secure API and application
Applies strongly to RadFlow.
- HTTPS everywhere is essential.
- Stronger auth should be added, ideally MFA for admin and clinical users.
- OAuth 2.0 may be appropriate for future API integrations, though the current app is still session-based.

### Role-based access control
Already partially implemented.
- RadFlow does have RBAC.
- It needs hardening, broader authorization testing, and better tenant/scope assurance.

### Audit logging
Applies strongly to RadFlow.
- Logging should cover access, modification, approval, export, and security-relevant events.
- Sensitive content should not be written into logs.

### Breach safe harbor
This is primarily a US HIPAA framing.
- In the UK, encryption is still highly important and can materially reduce regulatory and practical risk.
- However, the legal analysis is under UK GDPR / Data Protection Act 2018, not HIPAA safe-harbor language.

### BAA
This is a US HIPAA concept and is not the UK equivalent.
- In the UK, the closer equivalent is a controller-processor contract under Article 28 UK GDPR.
- For NHS-facing use, you also need NHS assurance expectations such as DSPT / DTAC, depending on context.

### Documentation
Applies strongly to RadFlow.
- Security decisions, encryption approach, key handling, retention, and access controls all need formal documentation.

## 6. UK / NHS Requirements Most Likely To Matter
The exact requirement set depends on product scope and intended use, but for a UK healthcare workflow product like RadFlow, the main national requirements likely to matter are:

### UK GDPR and Data Protection Act 2018
If RadFlow processes patient-identifiable or health data, it will be handling special category personal data and must implement appropriate technical and organisational measures.

Practical implications:
- privacy notice and lawful basis
- controller / processor role clarity
- Article 28 processor contract where applicable
- DPIA
- breach management
- access controls, minimization, retention, and accountability

### Data Security and Protection Toolkit (DSPT)
Organisations with access to NHS patient data and systems must use the DSPT to provide assurance that they are practising good data security.

Practical implications:
- your organisation will likely need DSPT participation if handling NHS patient data
- buyers will expect evidence of this

### DTAC
DTAC is the NHS baseline assessment framework for digital health technologies used by buyers and providers.

Practical implications:
- expect NHS customers to ask for DTAC evidence
- the product should be prepared across:
- clinical safety
- data protection
- technical security
- interoperability
- usability and accessibility

### Clinical safety standard DCB0129
Manufacturers of Health IT systems within scope must evidence clinical risk management.

Practical implications:
- appoint a Clinical Safety Officer
- maintain hazard log, clinical risk management file, and safety case report
- assess whether product behaviour could contribute to clinical risk

### DCB0160
Deploying organisations must manage clinical risk in deployment and use.

Practical implication:
- RadFlow should support customers with the material they need for local deployment safety review.

### Secure email standard DCB1596
If patient information is exchanged by email, the email path must meet the NHS secure email standard.

Practical implications:
- do not treat ordinary email as automatically acceptable
- referral-by-email should be limited to compliant mail routes and governed workflows

### Medical device / SaMD considerations
If RadFlow’s intended use goes beyond workflow administration and starts influencing clinical decisions, prioritisation, or recommendations in a way that could affect patient care, medical device regulation may become relevant.

Practical implication:
- intended use wording matters a lot
- if the product is SaMD, MHRA / UKCA obligations may apply

## 7. Immediate Remediation Plan
### Phase 1: Stop obvious exposure
- Remove all unsafe default secrets and passwords.
- Fail application startup in non-development environments if secure settings are absent.
- Disable or restrict `/diag/schema`.
- Remove SMTP fallback that prints message bodies.

### Phase 2: Production security baseline
- Force HTTPS in production.
- Enable secure session cookies and stronger cookie policy.
- Add HSTS.
- Move production data to Azure PostgreSQL and Azure Blob only.
- Store secrets in Azure Key Vault.

### Phase 3: Healthcare hardening
- Add CSRF protection.
- Add MFA for privileged users.
- Replace in-memory rate limiting with a production-grade shared control.
- Add structured audit logging and security monitoring.
- Define backup, restore, retention, and deletion controls.

### Phase 4: Assurance package
- Complete DPIA.
- Complete DTAC evidence pack.
- Complete DCB0129 clinical safety documentation if in scope.
- Produce customer-facing security architecture and data flow documentation.
- Put Article 28 data processing terms in place.

## 8. Recommended Positioning Today
Suggested current wording:

"RadFlow has a foundational security model including hashed passwords, role-based access, session controls, and compatibility with Azure managed hosting and storage. Before live use with patient-identifiable healthcare data, additional hardening and formal assurance work is required, including secure secret handling, production-only encrypted managed storage, stronger application security controls, and completion of NHS / UK governance documentation."

Suggested wording to avoid today:
- fully compliant
- NHS-ready
- secure for live patient data
- production-grade healthcare security

unless the remediation and assurance work has actually been completed.

## 9. Open Questions To Resolve
- Will RadFlow process identifiable patient data or only limited referral metadata?
- Will it be sold as workflow/admin software only, or could it be interpreted as influencing clinical decisions?
- Will referral intake use secure email, portal-only workflows, or direct system integration?
- Will customers expect UK-only hosting and support?
- Will Lumos Lab act only as processor, or also determine purposes/means for some processing?

## 10. Useful Official References
- NHS DTAC overview: https://transform.england.nhs.uk/key-tools-and-info/digital-technology-assessment-criteria-dtac/
- DTAC assessed criteria: https://transform.england.nhs.uk/key-tools-and-info/digital-technology-assessment-criteria-dtac/assessment-criteria-assessed-section/
- DSPT: https://www.dsptoolkit.nhs.uk/
- DCB0129: https://standards.nhs.uk/published-standards/clinical-risk-management-its-application-in-the-manufacture-of-health-it-systems
- DCB0160: https://standards.nhs.uk/published-standards/clinical-risk-management-its-application-in-the-deployment-and-use-of-health-it-systems
- Secure email standard DCB1596: https://www.standards.nhs.uk/published-standards/secure-email
- ICO encryption guidance: https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/security/encryption/encryption-and-data-protection/
- ICO controller-processor contracts: https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/accountability-and-governance/contracts-and-liabilities-between-controllers-and-processors-multi/what-needs-to-be-included-in-the-contract/
- MHRA medical devices guidance: https://www.gov.uk/guidance/regulating-medical-devices-in-the-uk
