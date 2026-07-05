# Feature: daily cumulative transfer-limit validation (greenfield)

## Stack & interface
- Python 3, pytest. Source in `transferapp/`; acceptance tests in
  `tests/acceptance/`.
- Contract: `transferapp.transfer.transfer(amount, daily_total, tier_limit,
  audit_log) -> "OK"`, raising `transferapp.transfer.LimitExceeded` when the
  transfer is blocked. All monetary values are `decimal.Decimal`.

## Summary
Before a transfer, check whether the customer's cumulative daily transfer
amount plus this transfer exceeds their tier limit; if so, block it and audit
the block.

## Acceptance criteria
- AC-1: when daily_total + amount <= tier_limit, the transfer is allowed and
  returns "OK".
- AC-2: when daily_total + amount > tier_limit, LimitExceeded is raised.
- AC-3: the exact-equal case (daily_total + amount == tier_limit) is ALLOWED.
- AC-4: an allowed transfer appends ("transfer", amount) to audit_log; a
  blocked one appends ("blocked", amount) before raising.

## Applicable constitution clauses
§1 (money is Decimal), §3 (money movement is audited), §5 (fail closed).

> There is deliberately no `tests/` directory in this repo: run with
> `--gate synthesize` so the loop authors its own acceptance gate from this
> spec before implementing.
