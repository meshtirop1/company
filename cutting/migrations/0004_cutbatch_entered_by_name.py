"""Keep who entered each batch as text, so deleting a supervisor's account can't erase it."""
from django.db import migrations, models


def backfill(apps, schema_editor):
    CutBatch = apps.get_model('cutting', 'CutBatch')
    for batch in CutBatch.objects.filter(entered_by__isnull=False, entered_by_name='').select_related('entered_by'):
        user = batch.entered_by
        batch.entered_by_name = f'{user.first_name} {user.last_name}'.strip() or user.username
        batch.save(update_fields=['entered_by_name'])


class Migration(migrations.Migration):

    dependencies = [
        ('cutting', '0003_work_entry'),
    ]

    operations = [
        migrations.AddField(
            model_name='cutbatch',
            name='entered_by_name',
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
