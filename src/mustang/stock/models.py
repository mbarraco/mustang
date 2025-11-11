from decimal import Decimal, ROUND_HALF_UP

from django.db import models

from mustang.common.models import BaseModel

from .enums import Currency, InstrumentType, OperationType


class StockInstrument(BaseModel):
    symbol = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=255)
    instrument_type = models.CharField(
        max_length=16,
        choices=InstrumentType.choices,
        default=InstrumentType.STOCK,
    )
    currency = models.CharField(
        max_length=8,
        choices=Currency.choices,
        default=Currency.ARS,
    )
    exchange = models.CharField(max_length=64)

    class Meta:
        ordering = ["symbol"]
        verbose_name = "Stock instrument"
        verbose_name_plural = "Stock instruments"

    def __str__(self) -> str:
        return f"{self.symbol} ({self.exchange})"


class StockOperation(BaseModel):
    instrument = models.ForeignKey(
        StockInstrument,
        on_delete=models.PROTECT,
        related_name="operations",
    )
    timestamp = models.DateTimeField()
    operation_type = models.CharField(
        max_length=4,
        choices=OperationType.choices,
    )
    quantity = models.DecimalField(max_digits=20, decimal_places=4)
    price = models.BigIntegerField(
        help_text="Price per unit expressed in minor currency units (e.g. cents)."
    )
    currency = models.CharField(
        max_length=8,
        choices=Currency.choices,
        default=Currency.ARS,
    )
    fees = models.BigIntegerField(
        default=0,
        help_text="Total fees in minor units (e.g. cents).",
    )
    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Stock operation"
        verbose_name_plural = "Stock operations"

    def __str__(self) -> str:
        return f"{self.get_operation_type_display()} {self.quantity} {self.instrument.symbol}"

    @property
    def total_value(self) -> int:
        subtotal = (self.quantity * Decimal(self.price)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
        return int(subtotal) + self.fees


class ExchangeRateSnapshot(BaseModel):
    timestamp = models.DateTimeField()
    currency = models.CharField(
        max_length=8,
        choices=Currency.choices,
        default=Currency.USD,
        help_text="Currency quoted against ARS (e.g. USD/ARS).",
    )
    official = models.DecimalField(max_digits=18, decimal_places=6)
    mep = models.DecimalField(max_digits=18, decimal_places=6)
    blue = models.DecimalField(max_digits=18, decimal_places=6)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Exchange rate snapshot"
        verbose_name_plural = "Exchange rate snapshots"
        unique_together = ("timestamp", "currency")

    def __str__(self) -> str:
        return f"{self.currency} @ {self.timestamp:%Y-%m-%d %H:%M}"
