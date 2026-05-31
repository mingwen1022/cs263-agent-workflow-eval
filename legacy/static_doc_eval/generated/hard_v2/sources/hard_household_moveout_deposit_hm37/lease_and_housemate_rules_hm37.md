# HM-37 Lease and Housemate Settlement Rules

## Current rule set for Unit 4B, lease ending 2026-03-31

Security deposit held by the landlord belongs to the roommates in the same
amounts originally contributed by each person. For HM-37, use the deposit
ledger marked `valid_final`.

Landlord deductions that are confirmed on the final property statement should
be allocated as follows:

1. Shared or unknown-responsibility deductions are allocated by original deposit
   share.
2. Deductions tied to an identified roommate's assigned room or documented
   action are charged to that roommate only.
3. Withdrawn, draft, prior estimate, other-unit, move-in-preexisting, and
   weather-damage lines are excluded.
4. Normal wear and tear is not deductible.

Utilities are not landlord deductions unless the final property statement says
otherwise. For the roommate settlement, utilities through 2026-03-31 are split
equally among Alex, Bri, and Chen after applying any bill-specific rider.

If a final utility bill spans both before and after 2026-03-31, include only
the portion through 2026-03-31 when the source row says to prorate. Count
service days inclusively. For a row marked
`prorate_through_2026_03_31_equal_split`, calculate:

1. total inclusive service days,
2. inclusive service days through 2026-03-31,
3. `total_amount * included_days / total_days`,
4. then split that included amount equally among Alex, Bri, and Chen.

Bill-specific rider for the March 2026 electricity bill:
- The EV charging add-on is Alex's personal charge.
- The remaining electricity amount is split equally.

Internet for March 2026 is a shared household utility. Streaming services,
replacement cables, and post-move-out service periods are personal or excluded
unless all three roommates approved them in writing.

Side adjustments are handled after landlord deductions and utility settlement.
Use only the `final_side_adjustments` sheet in the side-adjustment workbook.
Include rows when `status=final` and `include_in_settlement=yes`. Rows marked
`include_in_settlement=requires_thread_approval` are included only if the final
roommate approval thread shows explicit approval from Alex, Bri, and Chen before
2026-04-06.
For `allocation_rule=equal_split`, split the included amount equally among Alex,
Bri, and Chen. For `allocation_rule=deposit_share`, allocate the responsibility
by the original valid deposit shares. Exclude old draft sheets, draft rows,
voided rows, other-unit rows, personal or personal-subset expenses, duplicates
of landlord deductions, and any side expense without all-roommate approval.

## Obsolete clause, do not use

The 2024 draft housemate agreement split all shared deductions equally. That
draft was replaced by the current rule set above after Bri moved into bedroom B.
Do not use the 2024 equal-deposit split rule for HM-37.
