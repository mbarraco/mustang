from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import models

from common.models import BaseModel

from .enums import Currency, InstrumentType, OperationType


class StockExchange(BaseModel):
    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=255)
    country = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Stock exchange"
        verbose_name_plural = "Stock exchanges"

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class StockInstrument(BaseModel):
    symbol = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=255)
    yahoo_symbol = models.CharField(
        max_length=32,
        blank=True,
        help_text="Override for Yahoo Finance symbol (e.g., YPFD.BA).",
    )
    google_symbol = models.CharField(
        max_length=32,
        blank=True,
        help_text="Override for Google Finance symbol (e.g., YPFD:BCBA).",
    )
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
    exchange = models.ForeignKey(
        StockExchange,
        on_delete=models.PROTECT,
        related_name="instruments",
    )

    class Meta:
        ordering = ["symbol"]
        verbose_name = "Stock instrument"
        verbose_name_plural = "Stock instruments"

    def __str__(self) -> str:
        return f"{self.symbol} ({self.exchange.code})"


class StockOperation(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="stock_operations",
    )
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
        if self.quantity is None or self.price is None:
            return 0
        subtotal = (self.quantity * Decimal(self.price)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
        return int(subtotal) + self.fees


class StockInstrumentSnapshot(BaseModel):
    instrument = models.ForeignKey(
        StockInstrument,
        on_delete=models.PROTECT,
        related_name="snapshots",
    )
    as_of = models.DateTimeField(
        help_text="Timestamp provided by the upstream market data API.",
    )
    price = models.BigIntegerField(
        help_text="Most recent trade price expressed in minor currency units (e.g. cents).",
    )
    open_price = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Opening price in minor units.",
    )
    day_high = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Session high price in minor units.",
    )
    day_low = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Session low price in minor units.",
    )
    volume = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Latest reported traded volume in units/shares.",
    )
    data_source = models.CharField(
        max_length=64,
        blank=True,
        help_text="Identifier for the API or data feed that produced the snapshot.",
    )

    class Meta:
        ordering = ["instrument"]
        verbose_name = "Stock instrument snapshot"
        verbose_name_plural = "Stock instrument snapshots"
        constraints = [
            models.UniqueConstraint(
                fields=["instrument"],
                name="stock_single_snapshot_per_instrument",
            )
        ]

    def __str__(self) -> str:
        return f"{self.instrument.symbol} @ {self.as_of:%Y-%m-%d %H:%M}"


class ExchangeRateSnapshot(BaseModel):
    class Source(models.TextChoices):
        AUTOMATIC = "AUTOMATIC", "Automatic"
        MANUAL = "MANUAL", "Manual"

    timestamp = models.DateTimeField()
    currency = models.CharField(
        max_length=8,
        choices=Currency.choices,
        default=Currency.USD,
        help_text="Currency quoted against ARS (e.g. USD/ARS).",
    )
    official = models.BigIntegerField(help_text="Official USD/ARS rate in minor units.")
    mep = models.BigIntegerField(help_text="MEP USD/ARS rate in minor units.")
    blue = models.BigIntegerField(help_text="Blue USD/ARS rate in minor units.")
    custom = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="User-defined USD/ARS rate in minor units. Defaults to the average of official, mep, and blue.",
    )
    source = models.CharField(
        max_length=16,
        choices=Source.choices,
        default=Source.AUTOMATIC,
        help_text="Whether the snapshot was created automatically or manually.",
    )

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Exchange rate snapshot"
        verbose_name_plural = "Exchange rate snapshots"
        unique_together = ("timestamp", "currency")

    def __str__(self) -> str:
        return f"{self.currency} @ {self.timestamp:%Y-%m-%d %H:%M}"
