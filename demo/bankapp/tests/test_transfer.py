from decimal import Decimal
import pytest
from bankapp.transfer import transfer, LimitExceeded


def test_under_limit_allowed():
    log = []
    assert transfer(Decimal("10"), Decimal("0"), Decimal("100"), log) == "OK"


def test_over_limit_blocked():
    log = []
    with pytest.raises(LimitExceeded):
        transfer(Decimal("60"), Decimal("50"), Decimal("100"), log)


def test_exact_equal_boundary_allowed():
    """daily_total + amount == tier_limit must be allowed (>= vs > bug catcher)."""
    log = []
    assert transfer(Decimal("50"), Decimal("50"), Decimal("100"), log) == "OK"


def test_blocked_transfer_is_audited():
    log = []
    with pytest.raises(LimitExceeded):
        transfer(Decimal("60"), Decimal("50"), Decimal("100"), log)
    assert any(entry[0] == "blocked" for entry in log)
