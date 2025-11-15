from django.db import migrations

DEFAULT_STOCK_EXCHANGES = [
    ("NASDAQ", "Nasdaq Stock Market", "US"),
    ("NYSE", "New York Stock Exchange", "US"),
    ("NYSEARCA", "NYSE Arca", "US"),
    ("NYSEAMERICAN", "NYSE American", "US"),
    ("BCBA", "Bolsas y Mercados Argentinos (BYMA)", "AR"),
    ("B3", "B3 - Brasil Bolsa Balcão", "BR"),
    ("TSX", "Toronto Stock Exchange", "CA"),
    ("LSE", "London Stock Exchange", "GB"),
    ("EURONEXT", "Euronext", "EU"),
    ("BME", "Bolsa de Madrid", "ES"),
    ("ASX", "Australian Securities Exchange", "AU"),
    ("HKEX", "Hong Kong Stock Exchange", "HK"),
    ("JPX", "Japan Exchange Group (TSE)", "JP"),
    ("SSE", "Shanghai Stock Exchange", "CN"),
    ("SZSE", "Shenzhen Stock Exchange", "CN"),
    ("FWB", "Frankfurt Stock Exchange (Xetra)", "DE"),
    ("SIX", "SIX Swiss Exchange", "CH"),
    ("NSE", "National Stock Exchange of India", "IN"),
    ("BSE", "Bombay Stock Exchange", "IN"),
]


def create_stock_exchanges(apps, schema_editor):
    StockExchange = apps.get_model("stock", "StockExchange")
    for code, name, country in DEFAULT_STOCK_EXCHANGES:
        StockExchange.objects.update_or_create(
            code=code,
            defaults={"name": name, "country": country},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("stock", "0004_exchangeratesnapshot_source"),
    ]

    operations = [
        migrations.RunPython(create_stock_exchanges, migrations.RunPython.noop),
    ]
