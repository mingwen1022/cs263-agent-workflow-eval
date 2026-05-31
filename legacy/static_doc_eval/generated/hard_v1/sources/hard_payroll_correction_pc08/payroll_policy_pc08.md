# Payroll Correction Policy

## Eligible Corrections

Corrections must belong to the current batch ID and to the employee under review.
Entries from prior batches or different employees must be excluded before
processing the correction.

Duplicate entries for the same employee, pay period, and correction type must
be identified and removed before calculating the net correction.

## Eligible Correction Types

The following types are eligible for retroactive correction:
- overtime: retroactive rate corrections
- bonus: omitted discretionary bonuses that have documented approval
- expense_reimbursement: approved reimbursements not processed in the original run

The following types are not eligible for retroactive correction in this batch:
- commission: handled by a separate commission reconciliation process
- equity_adjustment: requires a separate equity review sign-off

## Tax Adjustment

When gross pay increases due to corrections, apply the marginal tax rate for the
employee's pay grade. For L4 employees, the marginal rate is 22%. For L3, it is
20%. The tax adjustment is the additional tax owed on the net correction amount.

Apply the tax adjustment only to overtime and bonus corrections. Expense
reimbursements are not subject to income tax.

## Additional Approval

If the total net correction for a single employee in a batch exceeds $1,000,
a second sign-off from the Payroll Director is required before disbursement.
