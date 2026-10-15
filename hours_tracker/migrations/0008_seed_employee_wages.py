"""Give every existing employee their current wage as their first dated wage.

It starts in the month they joined, and a person's first wage also covers any earlier month
(see wages.wage_for), so every past figure stays exactly what it was before dated wages.
"""
from django.db import migrations


def seed(apps, schema_editor):
    CustomUser = apps.get_model('hours_tracker', 'CustomUser')
    EmployeeWage = apps.get_model('hours_tracker', 'EmployeeWage')
    for user in CustomUser.objects.all():
        if not (user.is_employee or user.hourly_wage) or EmployeeWage.objects.filter(user=user).exists():
            continue
        EmployeeWage.objects.create(
            user=user, effective_from=user.date_joined.date().replace(day=1), hourly_wage=user.hourly_wage,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('hours_tracker', '0007_employee_wages'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
