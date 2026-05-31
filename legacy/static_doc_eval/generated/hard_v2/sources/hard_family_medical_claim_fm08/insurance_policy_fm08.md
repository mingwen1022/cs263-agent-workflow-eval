# Family Health Insurance Policy — Plan FM-08

## Coverage Year

This plan covers the 2026 plan year, starting 2026-01-01.
Claims with a service date before 2026-01-01 belong to a separate prior-year
review and are not processed in this review.

## Eligible Members

Only family members listed as `covered_under_policy = yes` in the family
members register may receive benefits under this policy. Claims submitted
for non-covered individuals are excluded from this review (not denied).

## Deductible

- Family annual deductible: $2,000.00
- Once the family has paid $2,000.00 total toward the deductible in a plan
  year, the deductible is met and coinsurance applies to subsequent claims.
- Preventive care claims do NOT apply toward the deductible.

The deductible is applied to non-preventive claims in claim-ID order.

## Coinsurance (applies after deductible is met)

- In-network medical service: insurance pays 80%, member pays 20%.
- Out-of-network medical service WITH a written referral on file:
  insurance pays 60%.
- Out-of-network medical service WITHOUT a written referral: NOT COVERED
  (insurance pays 0%, claim is denied).

## Always-Covered Categories (no deductible)

- Preventive care: insurance pays 100% (annual physicals, routine vaccines,
  routine screenings). These do not apply toward the deductible.

## Non-Covered Categories (always denied)

These categories are never covered under Plan FM-08:
- Dental care (a separate dental policy is required).
- Cosmetic procedures.

## Mental Health

- In-network mental health: 80% coinsurance after deductible.
- Out-of-network mental health: not covered.

## Duplicate Claims

If two or more claims have the same member, same provider, same service
date, and the same billed amount, only the first (lowest claim_id) is
processed. Subsequent identical claims are denied as duplicates.

## Reimbursement Formula

For each approved claim:
- If preventive: reimbursement = billed_amount × 100%
- If subject to deductible and deductible not yet met:
  - amount_to_deductible = min(billed_amount, remaining_deductible)
  - amount_subject_to_coinsurance = billed_amount − amount_to_deductible
  - reimbursement = amount_subject_to_coinsurance × coinsurance_rate
- If subject to deductible and deductible already met:
  - reimbursement = billed_amount × coinsurance_rate

Coinsurance rate is 80% for in-network, 60% for out-of-network with referral.

## Total Approved Amount

`total_approved_amount` = sum of reimbursement values for all approved claims.
