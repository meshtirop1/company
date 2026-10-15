"""Seed the price list from the company's printed rate sheet.

The prices are editable on the price-list page afterwards. One value is still unconfirmed:
the sheet has a handwritten note beside 10~11 통포 (printed 6,500), so check that rate.
"""
from datetime import date

from django.db import migrations

SEED_FROM = date(2026, 1, 1)

PRICE_LIST = [
    ('tongpo', [('7', 4000), ('8', 4500), ('9', 5000), ('10~11', 6500), ('12', 7000)]),
    ('tonghalbok', [('4,5,6', 2300), ('7,8', 2400), ('9', 2500), ('10~11', 3000), ('12', 3300), ('13', 3300)]),
]


def seed(apps, schema_editor):
    PriceItem = apps.get_model('cutting', 'PriceItem')
    PriceRate = apps.get_model('cutting', 'PriceRate')
    for style, rows in PRICE_LIST:
        for position, (size, price) in enumerate(rows, start=1):
            item, _ = PriceItem.objects.get_or_create(
                style=style, size=size, defaults={'sort_order': position * 10},
            )
            PriceRate.objects.get_or_create(item=item, effective_from=SEED_FROM, defaults={'unit_price': price})


def unseed(apps, schema_editor):
    """Remove only seed rows that are still exactly as seeded; anything edited since stays."""
    PriceItem = apps.get_model('cutting', 'PriceItem')
    PriceRate = apps.get_model('cutting', 'PriceRate')
    for style, rows in PRICE_LIST:
        for size, price in rows:
            PriceRate.objects.filter(
                item__style=style, item__size=size, effective_from=SEED_FROM, unit_price=price,
            ).delete()
            PriceItem.objects.filter(style=style, size=size, rates__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('cutting', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
