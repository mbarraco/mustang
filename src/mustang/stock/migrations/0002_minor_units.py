from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations, models


def _to_cents(value):
    if value in (None, ""):
        return None
    return int(
        (Decimal(value) * Decimal("100")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def convert_prices_to_cents(apps, schema_editor):
    StockInstrumentSnapshot = apps.get_model("stock", "StockInstrumentSnapshot")
    ExchangeRateSnapshot = apps.get_model("stock", "ExchangeRateSnapshot")

    for snapshot in StockInstrumentSnapshot.objects.all().iterator():
        updated = False
        for field in ("price", "open_price", "day_high", "day_low"):
            value = getattr(snapshot, field, None)
            if value in (None, ""):
                continue
            cents = _to_cents(value)
            setattr(snapshot, field, cents)
            updated = True
        if updated:
            snapshot.save(update_fields=["price", "open_price", "day_high", "day_low"])

    for snapshot in ExchangeRateSnapshot.objects.all().iterator():
        updated = False
        for field in ("official", "mep", "blue"):
            value = getattr(snapshot, field, None)
            if value in (None, ""):
                continue
            cents = _to_cents(value)
            setattr(snapshot, field, cents)
            updated = True
        if updated:
            snapshot.save(update_fields=["official", "mep", "blue"])


class Migration(migrations.Migration):

    dependencies = [
        ("stock", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(convert_prices_to_cents, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="exchangeratesnapshot",
            name="blue",
            field=models.BigIntegerField(help_text="Blue USD/ARS rate in minor units."),
        ),
        migrations.AlterField(
            model_name="exchangeratesnapshot",
            name="mep",
            field=models.BigIntegerField(help_text="MEP USD/ARS rate in minor units."),
        ),
        migrations.AlterField(
            model_name="exchangeratesnapshot",
            name="official",
            field=models.BigIntegerField(help_text="Official USD/ARS rate in minor units."),
        ),
        migrations.AlterField(
            model_name="stockinstrumentsnapshot",
            name="day_high",
            field=models.BigIntegerField(blank=True, help_text="Session high price in minor units.", null=True),
        ),
        migrations.AlterField(
            model_name="stockinstrumentsnapshot",
            name="day_low",
            field=models.BigIntegerField(blank=True, help_text="Session low price in minor units.", null=True),
        ),
        migrations.AlterField(
            model_name="stockinstrumentsnapshot",
            name="open_price",
            field=models.BigIntegerField(blank=True, help_text="Opening price in minor units.", null=True),
        ),
        migrations.AlterField(
            model_name="stockinstrumentsnapshot",
            name="price",
            field=models.BigIntegerField(help_text="Most recent trade price expressed in minor currency units (e.g. cents)."),
        ),
    ]
