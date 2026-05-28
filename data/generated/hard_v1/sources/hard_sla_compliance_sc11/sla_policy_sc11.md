# SLA Credit Policy — April 2026 Review Period

## Credit Eligibility

Automatic acknowledgement-delay credits apply only to Gold-tier customers with
active accounts. Silver and Bronze accounts have no automatic credit under this
policy.

## Acknowledgement SLA Calculation

The SLA clock starts at the incident start time. Acknowledgement must occur
within the SLA window defined in the customer contract.
- Breach = ack_time - start_time > contracted SLA minutes

## Credit Trigger and Amount

A breach earns the customer a credit only if the acknowledgement delay exceeds
the contracted SLA. The credit amount per incident is defined in the customer
contract. There is no per-incident cap, but a monthly total cap applies.

Monthly credit cap: No single customer may receive more than $500 in automatic
credits for a single calendar month, regardless of the number of incidents.

## Exclusions

The following incidents are excluded from SLA credit calculations:
- Incidents during a scheduled maintenance window: these are pre-announced and
  SLA obligations are suspended.
- Incidents caused directly by customer misconfiguration: customer-caused
  outages do not generate credits.
- Internal-only incidents with no customer impact.
- Incidents affecting only non-credit-eligible tiers.

## Risk Flags

If the same customer-facing system has two or more P2 breaches in a calendar
month, the account team should flag this for a reliability review.
