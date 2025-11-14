from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Union

MinorValue = Union[int, Decimal, str]


def to_minor_units(value: Optional[MinorValue]) -> Optional[int]:
    if value in (None, ""):
        return None
    decimal_value = Decimal(str(value))
    cents = (decimal_value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def to_major_units(value: Optional[MinorValue]) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    decimal_value = Decimal(str(value))
    return decimal_value / Decimal("100")
