# Feature: daily cumulative transfer-limit validation

## Summary
Before a transfer, check whether the customer's cumulative daily transfer amount
plus this transfer exceeds their tier limit; if so, block it and audit the block.

## Acceptance criteria
- AC-1: when daily_total + amount <= tier_limit, the transfer is allowed.
- AC-2: when daily_total + amount > tier_limit, raise LimitExceeded.
- AC-3: the exact-equal case (daily_total + amount == tier_limit) is ALLOWED.
- AC-4: a blocked transfer MUST append a ("blocked", amount) audit entry. (§3)
- AC-5: all monetary arithmetic uses Decimal, never float. (§1)

## Applicable constitution clauses
§1 (money is Decimal), §3 (money movement is audited), §5 (fail closed).
