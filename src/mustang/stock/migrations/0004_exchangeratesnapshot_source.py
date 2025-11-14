from django.db import migrations, models


def set_default_source(apps, schema_editor):
    Snapshot = apps.get_model("stock", "ExchangeRateSnapshot")
    Snapshot.objects.filter(source="").update(source="AUTOMATIC")


class Migration(migrations.Migration):

    dependencies = [
        ("stock", "0003_exchangeratesnapshot_custom"),
    ]

    operations = [
        migrations.AddField(
            model_name="exchangeratesnapshot",
            name="source",
            field=models.CharField(choices=[("AUTOMATIC", "Automatic"), ("MANUAL", "Manual")], default="AUTOMATIC", help_text="Whether the snapshot was created automatically or manually.", max_length=16),
        ),
        migrations.RunPython(set_default_source, migrations.RunPython.noop),
    ]
