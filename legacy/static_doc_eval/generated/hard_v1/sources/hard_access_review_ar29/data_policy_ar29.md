# Data Access and Security Policy

## Contractor Access Restrictions

Contractors are treated as external parties and may only access systems listed
as explicitly permitted for the contractor role in the role permission matrix.
Any resource showing "none" in the matrix requires a signed Data Access Exception
(DAE) approved by the Security Lead and the department head.

Exception limits: a DAE or production data exception can only be considered when
all other access prerequisites are satisfied. It cannot override an active prior
data-handling violation, and it cannot override a permission category that this
policy marks as never granted.

## PII Access

Customer PII databases are classified as Restricted. Access requires:
1. A business justification approved by the department head
2. Security Lead sign-off
3. No prior data handling violations on record

QA and testing must use anonymized or synthetic data sets, not production PII,
unless a specific production data exception is approved by the Privacy Officer.

## Delete Permissions

Delete-level access to any production database is never granted to contractors
or analysts. This applies regardless of business justification.

## Audit Log Access

Internal audit logs are classified as Confidential. Contractor role access level
is "none" per the role matrix. Debugging access for contractors must be routed
through a supervised session with an on-staff engineer.

## Deployment Pipeline

Write access to the deployment pipeline requires the engineer role or above.
Contractor role does not include deployment write access by default.
