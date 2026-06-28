# Engineering Constitution

> Version-controlled rule set. Every change produced by the agent loop is checked
> against these clauses by the Security Critic before convergence.
> This file is READ-ONLY to the coding agent (the Actor).

## §1 — Money is never floating point
All monetary amounts MUST use a fixed-point decimal type (e.g. `Decimal`),
never `float` or `double`. This includes intermediate calculations.

## §2 — Validate all external input
Any value originating outside the service MUST be validated before use.

## §3 — Every money movement leaves an audit trail
Any operation that moves, holds, or limits funds MUST write an audit record
(who, what, amount, timestamp, outcome). A blocked operation MUST also be audited.

## §4 — No customer PII in logs
Account numbers, names, balances MUST NOT be written to application logs.

## §5 — Fail closed on limits and authorization
When a limit or authorization check cannot be completed, the operation MUST be denied.
