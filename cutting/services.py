"""Every write to work records and to cutters' tax and insurance goes through these functions.

That makes this the one place the month lock and the change log apply: a locked month
refuses every change, and every correction, deletion, re-price, rate change, tax/insurance
change and lock is written to the change log (AuditEntry) in the same transaction as the
change itself.

Each write checks the lock inside its transaction. On SQLite (production) only one
transaction can write at a time, so a lock can't slip in between the check and the write.
"""
import hashlib
from datetime import date

from django.db import transaction
from django.utils import timezone

from hours_tracker import deductions

from .models import AuditAction, AuditEntry, CutBatch, CutRecord, CutterDeduction, MonthLock
from .reports import month_bounds


class NoRate(Exception):
    """The price list has no rate for this size on the work date."""

    def __init__(self, item, day):
        super().__init__(f'No rate for {item} on {day}')
        self.item = item
        self.day = day


class MonthLocked(Exception):
    """The work belongs to a month that has been paid and locked."""

    def __init__(self, month):
        super().__init__(f'{month:%Y-%m} is locked')
        self.month = month


class MonthNotOver(Exception):
    """A month can only be locked from its last day on."""

    def __init__(self, month, last_day):
        super().__init__(f'{month:%Y-%m} runs until {last_day}')
        self.month = month
        self.last_day = last_day


def user_label(user):
    """How a supervisor is shown on work records: full name, else username."""
    if user is None:
        return ''
    return user.get_full_name() or user.username


def priced(item, day):
    """The unit price in force for `item` on `day`, or raise NoRate."""
    rate = item.rate_on(day)
    if rate is None:
        raise NoRate(item, day)
    return rate.unit_price


# ─── Month lock ───────────────────────────────────────────────

def month_of(day):
    return day.replace(day=1)


def lock_for(day):
    """The lock on the month `day` falls in, or None."""
    return MonthLock.objects.filter(month=month_of(day)).first()


def ensure_open(day):
    if MonthLock.objects.filter(month=month_of(day)).exists():
        raise MonthLocked(month_of(day))


def can_lock(first_day, today=None):
    """A month can be locked from its last day — once the work it pays for is all in."""
    return (today or timezone.localdate()) >= month_bounds(first_day)[1]


@transaction.atomic
def lock_month(first_day, *, user, today=None):
    """Lock a paid month. Locking a month that is already locked changes nothing."""
    first_day = month_of(first_day)
    existing = MonthLock.objects.filter(month=first_day).first()
    if existing:
        return existing
    if not can_lock(first_day, today):
        raise MonthNotOver(first_day, month_bounds(first_day)[1])
    lock = MonthLock.objects.create(month=first_day, locked_by=user, locked_by_name=user_label(user))
    log(AuditAction.LOCK, user=user, month=first_day)
    return lock


@transaction.atomic
def unlock_month(first_day, *, user, reason):
    """Reopen a locked month. The reason goes into the change log. Returns False if it wasn't locked."""
    lock = MonthLock.objects.filter(month=month_of(first_day)).first()
    if lock is None:
        return False
    before = {'locked_by': lock.locked_by_name, 'locked_at': timezone.localtime(lock.locked_at).isoformat()}
    lock.delete()
    log(AuditAction.UNLOCK, user=user, month=month_of(first_day), before=before, reason=reason)
    return True


# ─── Change log ───────────────────────────────────────────────

def log(action, *, user, month, work_date=None, cutter_name='', record_id=None, batch_id=None,
        before=None, after=None, reason=''):
    return AuditEntry.objects.create(
        action=action, month=month, work_date=work_date, cutter_name=cutter_name,
        record_id=record_id, batch_id=batch_id, before=before, after=after,
        reason=reason, user=user, user_name=user_label(user),
    )


def snapshot(record):
    """What a record held, as plain values the change log can keep."""
    return {
        'style': record.style, 'size': record.size, 'boxes': record.boxes,
        'unit_price': int(record.unit_price), 'total': int(record.total),
    }


def log_record(action, record, *, user, before=None, after=None, reason=''):
    log(
        action, user=user, month=month_of(record.work_date), work_date=record.work_date,
        cutter_name=record.cutter.name, record_id=record.pk, batch_id=record.batch_id,
        before=before, after=after, reason=reason,
    )


def removed(record):
    """A deleted record's snapshot, with who entered it and when."""
    data = snapshot(record)
    data['entered_by'] = record.batch.entered_by_name
    data['saved_at'] = timezone.localtime(record.batch.created_at).isoformat(timespec='minutes')
    return data


def rate_snapshot(rate):
    return {
        'item': str(rate.item), 'unit_price': int(rate.unit_price),
        'effective_from': rate.effective_from.isoformat(),
    }


def log_rate(action, *, user, before=None, after=None):
    """A rate was added, changed or deleted — filed under the month it (now) starts in."""
    day = date.fromisoformat((after or before)['effective_from'])
    log(action, user=user, month=month_of(day), work_date=day, before=before, after=after)


# ─── Tax and health insurance ─────────────────────────────────

def deduction_span_lock(cutter, first_day):
    """The first locked month whose payslip uses the cutter's rate starting `first_day`, or None.

    That rate covers its month and every month until the cutter's next rate starts, so
    adding, changing or deleting it alters all of those payslips.
    """
    later = cutter.deductions.filter(effective_from__gt=first_day).order_by('effective_from').first()
    locks = MonthLock.objects.filter(month__gte=first_day)
    if later is not None:
        locks = locks.filter(month__lt=later.effective_from)
    return locks.order_by('month').first()


@transaction.atomic
def set_deduction(cutter, first_day, values, *, user):
    """Save the cutter's rate from `first_day` (replacing one already starting then).

    `values` holds tax_percent, insurance_mode and insurance_value. Refused with MonthLocked
    if it would alter a locked month's payslip. Saving it unchanged writes nothing.
    """
    lock = deduction_span_lock(cutter, first_day)
    if lock is not None:
        raise MonthLocked(lock.month)
    rate = cutter.deductions.filter(effective_from=first_day).first()
    before = deductions.snapshot(rate) if rate else None
    if rate is None:
        rate = CutterDeduction(cutter=cutter, effective_from=first_day)
    for field, value in values.items():
        setattr(rate, field, value)
    rate.save()
    rate.refresh_from_db()  # the decimals as stored, so an unchanged save compares equal
    after = deductions.snapshot(rate)
    if after != before:
        log(AuditAction.DEDUCTION_SET, user=user, month=first_day, work_date=first_day,
            cutter_name=cutter.name, before=before, after=after)
    return rate


@transaction.atomic
def delete_deduction(rate, *, user):
    """Delete a rate; the months it covered fall back to the cutter's previous rate (or none)."""
    lock = deduction_span_lock(rate.cutter, rate.effective_from)
    if lock is not None:
        raise MonthLocked(lock.month)
    log(AuditAction.DEDUCTION_DELETE, user=user, month=rate.effective_from, work_date=rate.effective_from,
        cutter_name=rate.cutter.name, before=deductions.snapshot(rate))
    rate.delete()


# ─── Work records ─────────────────────────────────────────────

@transaction.atomic
def save_batch(*, work_date, rows, entered_by, token):
    """Save a whole batch — every row or none.

    `rows` is a list of (cutter, item, boxes). Each record snapshots the style, size and
    the rate in force on the work date. A reused `token` raises IntegrityError and rolls
    the whole batch back, so the same form can never be saved twice.
    """
    ensure_open(work_date)
    batch = CutBatch.objects.create(
        work_date=work_date, entered_by=entered_by, entered_by_name=user_label(entered_by), token=token,
    )
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
def update_record(record, *, item, boxes, user=None, reason=''):
    """Change a record's boxes and/or its style and size.

    Changing only the boxes keeps the price the record was saved with. Moving it to another
    size takes the rate in force for that size on the record's work date. Saving it
    unchanged writes nothing, so the change log only shows real changes.
    """
    ensure_open(record.work_date)
    if item.pk == record.item_id and boxes == record.boxes:
        return record
    before = snapshot(record)
    if item.pk != record.item_id:
        record.unit_price = priced(item, record.work_date)
        record.item = item
        record.style = item.style
        record.size = item.size
    record.boxes = boxes
    record.total = record.unit_price * boxes
    record.save()
    log_record(AuditAction.EDIT, record, user=user, before=before, after=snapshot(record), reason=reason)
    return record


@transaction.atomic
def delete_record(record, *, user=None):
    """Delete one row; a batch left with no rows goes too."""
    ensure_open(record.work_date)
    batch = record.batch
    log_record(AuditAction.DELETE_RECORD, record, user=user, before=removed(record))
    record.delete()
    if not batch.records.exists():
        batch.delete()


@transaction.atomic
def delete_batch(batch, *, user=None):
    """Delete a whole entry. Each of its rows gets its own line in the change log."""
    ensure_open(batch.work_date)
    for record in batch.records.select_related('cutter', 'batch'):
        log_record(AuditAction.DELETE_BATCH, record, user=user, before=removed(record))
    batch.delete()


# ─── Re-pricing after a backdated price change ────────────────

def stale_records(first_day):
    """The month's records whose saved price differs from what the price list now gives
    for their work date — left behind when a rate is added, changed or removed after the
    work was recorded. Returns (record, list_price) pairs; list_price is None when no
    rate covers the day any more."""
    first, last = month_bounds(first_day)
    records = (
        CutRecord.objects.filter(work_date__range=(first, last))
        .select_related('cutter', 'item')
        .prefetch_related('item__rates')
        .order_by('work_date', 'cutter__name', 'pk')
    )
    stale = []
    for record in records:
        rate = record.item.rate_on(record.work_date)
        list_price = rate.unit_price if rate else None
        if list_price != record.unit_price:
            stale.append((record, list_price))
    return stale


class PlanChanged(Exception):
    """The price list or the records changed between showing the re-price list and confirming it."""


def repriceable(first_day):
    """The stale records that have a list price to move to, as (record, list_price)."""
    return [(record, price) for record, price in stale_records(first_day) if price is not None]


def plan_token(plan):
    """A fingerprint of a re-price plan — exactly which records, from which price to which."""
    parts = sorted(f'{record.pk}:{record.boxes}:{record.unit_price}:{price}' for record, price in plan)
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()[:20]


@transaction.atomic
def reprice_month(first_day, *, user, expected=None):
    """Bring the month's stale records to the list price. Records with no rate on their day
    are left as saved. With `expected` (the plan_token of the list the manager confirmed),
    nothing changes unless the plan is still exactly that list.
    Returns (records changed, change in the month's total)."""
    ensure_open(first_day)
    plan = repriceable(first_day)
    if expected is not None and plan_token(plan) != expected:
        raise PlanChanged()
    changed, delta = 0, 0
    for record, list_price in plan:
        before = snapshot(record)
        record.unit_price = list_price
        record.total = list_price * record.boxes
        record.save(update_fields=['unit_price', 'total', 'updated_at'])
        log_record(AuditAction.REPRICE, record, user=user, before=before, after=snapshot(record))
        changed += 1
        delta += record.total - before['total']
    return changed, delta
