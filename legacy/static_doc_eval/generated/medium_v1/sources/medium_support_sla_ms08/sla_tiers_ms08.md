# Support SLA Tiers

## Response time targets

Priority 1 (P1): first response within 30 minutes.
Priority 2 (P2): first response within 60 minutes.
Priority 3 (P3): first response within 4 hours (240 minutes).

Internal tickets (P4) are excluded from customer SLA tracking.

## Breach definition

A breach occurs when first_response_time - opened_time exceeds the target
for the ticket's priority.

## Escalation

Any P1 breach requires immediate escalation to the on-call manager.
Breached P2 or P3 tickets should be flagged for team lead review.
