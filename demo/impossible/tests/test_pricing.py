"""The deterministic gate for instant-refund. READ-ONLY to the actor.

test_at_limit_allowed and test_at_limit_denied assert OPPOSITE outcomes for the
SAME input (amount == limit). No implementation of refund() can pass both, so
the test gate fails every iteration and the loop escalates at its cap. This is
the intended "broken spec" demo — see specs/instant-refund.md."""
from decimal import Decimal

import pytest

from pricing import refund, RefundDenied


def test_below_limit_allowed():
    assert refund(Decimal("40"), Decimal("100")) == "REFUNDED"


def test_above_limit_denied():
    with pytest.raises(RefundDenied):
        refund(Decimal("140"), Decimal("100"))


def test_at_limit_allowed():
    # AC-3: threshold is inclusive -> allowed.
    assert refund(Decimal("100"), Decimal("100")) == "REFUNDED"


def test_at_limit_denied():
    # AC-4: threshold is a hard ceiling -> denied. Contradicts test_at_limit_allowed.
    with pytest.raises(RefundDenied):
        refund(Decimal("100"), Decimal("100"))
