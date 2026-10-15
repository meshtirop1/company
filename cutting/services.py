"""Every write to work records goes through these functions.

Keeping them in one place means the controls that come later (locking a paid month,
the audit log of edits and deletions) have exactly one place to hook in.
"""
from django.db import transaction

from .models import CutBatch, CutRecord


class NoRate(Exception):
    """The price list has no rate for this size on the work date."""

    def __init__(self, item, day):
        super().__init__(f'No rate for {item} on {day}')
        self.item = item
        self.day = day


def priced(item, day):
    """The unit price in force for `item` on `day`, or raise NoRate."""
    rate = item.rate_on(day)
    if rate is None:
        raise NoRate(item, day)
    return rate.unit_price


@transaction.atomic
def save_batch(*, work_date, rows, entered_by, token):
    """Save a whole batch — every row or none.

    `rows` is a list of (cutter, item, boxes). Each record snapshots the style, size and
    the rate in force on the work date. A reused `token` raises IntegrityError and rolls
    the whole batch back, so the same form can never be saved twice.
    """
    batch = CutBatch.objects.create(work_date=work_date, entered_by=entered_by, token=token)
    records = []
    for cutter, item, boxes in rows:
        unit_price = priced(item, work_date)
        records.append(CutRecord(
            batch=batch, cutter=cutter, item=item, work_date=work_date,
            style=item.style, size=item.size, boxes=boxes,
            unit_price=unit_price, total=unit_price * boxes,
        ))
    CutRecord.objects.bulk_create(records)
    return batch


@transaction.atomic
def update_record(record, *, item, boxes):
    """Change a record's boxes and/or its style and size.

    Changing only the boxes keeps the price the record was saved with. Moving it to another
    size takes the rate in force for that size on the record's work date.
    """
    if item.pk != record.item_id:
        record.unit_price = priced(item, record.work_date)
        record.item = item
        record.style = item.style
        record.size = item.size
    record.boxes = boxes
    record.total = record.unit_price * boxes
    record.save()
    return record


@transaction.atomic
def delete_record(record):
    """Delete one row; a batch left with no rows goes too."""
    batch = record.batch
    record.delete()
    if not batch.records.exists():
        batch.delete()


@transaction.atomic
def delete_batch(batch):
    batch.delete()
