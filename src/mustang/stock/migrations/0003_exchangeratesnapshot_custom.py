from decimal import Decimal

from django.db import migrations, models


def _avg(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return int(sum(values) / len(values))


def set_custom_rate(apps, schema_editor):
    Snapshot = apps.get_model("stock", "ExchangeRateSnapshot")
    for snapshot in Snapshot.objects.all().iterator():
        if snapshot.custom:
            continue
        snapshot.custom = _avg([snapshot.official, snapshot.mep, snapshot.blue])
        snapshot.save(update_fields=["custom"])


class Migration(migrations.Migration):

    dependencies = [
        ("stock", "0002_minor_units"),
    ]

    operations = [
        migrations.AddField(
            model_name="exchangeratesnapshot",
            name="custom",
            field=models.BigIntegerField(blank=True, help_text="User-defined USD/ARS rate in minor units. Defaults to the average of official, mep, and blue.", null=True),
        ),
        migrations.RunPython(set_custom_rate, migrations.RunPython.noop),
    ]
