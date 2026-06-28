"""Transfer module. The daily cumulative limit check is NOT yet implemented —
the agent loop must add it to satisfy tests/test_transfer.py."""


class LimitExceeded(Exception):
    pass


def transfer(amount, daily_total, tier_limit, audit_log):
    """Record and 'execute' a transfer. Currently performs no limit check."""
    audit_log.append(("transfer", amount))
    return "OK"
