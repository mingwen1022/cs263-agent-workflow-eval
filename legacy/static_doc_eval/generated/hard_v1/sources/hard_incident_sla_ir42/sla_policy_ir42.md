# Incident SLA policy

## Scope

This policy applies to production incidents tied to customer-facing services.
Staging alerts, sandbox alerts, and unrelated dashboard warnings do not start the
SLA clock. Use the first qualifying production alert for the incident under review.

For Gold customers:

- Acknowledgement must occur within 10 minutes of the first qualifying production alert.
- If acknowledgement is more than 15 minutes late beyond the acknowledgement SLA,
  each affected Gold customer receives a 250.00 service credit.
- The public status page should be updated within 30 minutes of the first qualifying alert.

For Silver customers:

- Acknowledgement must occur within 30 minutes.
- No automatic service credit applies for acknowledgement delays under 60 minutes.

For Bronze customers:

- No automatic acknowledgement credit applies. Support may still communicate with
  Bronze customers, but the credit rule does not apply.

Exclusions and notes:

- Suspended accounts are excluded from automatic credits until account status is
  restored.
- Quarterly uptime credits are calculated by a separate process and should not be
  included in an acknowledgement SLA review.
- Public status-page delay is a risk flag but does not add to the acknowledgement
  credit amount in this review.
