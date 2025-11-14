from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def minor_to_major(value):
    if value in (None, ""):
        return None
    raw = str(value)
    decimal_value = Decimal(raw)
    if "." in raw:
        return decimal_value
    return decimal_value / Decimal("100")
