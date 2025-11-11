from django.db import models


class InstrumentType(models.TextChoices):
    STOCK = "STOCK", "Stock"
    BOND = "BOND", "Bond"
    ADR = "ADR", "ADR"
    CEDEAR = "CEDEAR", "CEDEAR"
    ETF = "ETF", "ETF"
    OTHER = "OTHER", "Other"


class Currency(models.TextChoices):
    ARS = "ARS", "ARS"
    USD = "USD", "USD"
    EUR = "EUR", "EUR"
    BRL = "BRL", "BRL"
    OTHER = "OTHER", "Other"


class OperationType(models.TextChoices):
    BUY = "BUY", "Buy"
    SELL = "SELL", "Sell"
