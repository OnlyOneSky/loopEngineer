"""Daily transfer limit — NOT implemented, and this repo has NO tests/.

This is the self-authored-gate demo: the loop first turns the approved spec
into acceptance tests (phase 0, --gate synthesize), freezes them, and only
then implements this function against them."""
from decimal import Decimal


class LimitExceeded(Exception):
    pass


def transfer(amount: Decimal, daily_total: Decimal, tier_limit: Decimal,
             audit_log: list) -> str:
    """Allow or block a transfer against the daily tier limit."""
    raise NotImplementedError
