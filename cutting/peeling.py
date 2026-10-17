"""Skin peeling by outside companies: every write, and the figures built from them.

Fish go out to a company, come back peeled in batches, or are written off as lost or damaged.
The cross-check is always: given = brought back + lost + still with them. Pay is per fish
brought back at the company's price for that day, plus or minus the company's tax setting.

Like cutting/services.py, this is the only write path: a company's paid month refuses every
change, corrections and deletions go into the change log, and the checks happen inside the
transaction so two phones can't slip a change past each other.
"""
from datetime import date
from decimal import ROUND_DOWN, Decimal

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from .models import AuditAction, PeelCompany, PeelKind, PeelMovement, PeelPaid, PeelPrice, TaxMode
from .reports import month_bounds
from .services import log, month_of, user_label


class NoPrice(Exception):
    """The company has no price in force on that day."""

    def __init__(self, company, day):
        super().__init__(f'No price for {company} on {day}')
        self.company = company
        self.day = day


class PeelLocked(Exception):
    """The entry belongs to a month already paid to this company."""

    def __init__(self, company, month):
        super().__init__(f'{company} {month:%Y-%m} is paid')
        self.company = company
        self.month = month


class TooManyBack(Exception):
    """More fish would be brought back or written off than the company was given.
    `short` is by how many."""

    def __init__(self, company, short):
        super().__init__(f'{company} would be {short} fish short')
        self.company = company
        self.short = short


class MonthNotOver(Exception):
    def __init__(self, month, last_day):
        super().__init__(f'{month:%Y-%m} runs until {last_day}')
        self.month = month
        self.last_day = last_day


# ─── Counting ─────────────────────────────────────────────────

def counts(movements):
    """{'out', 'back', 'lost', 'with_them'} over a queryset of movements."""
    by_kind = dict(movements.order_by().values_list('kind').annotate(total=Sum('fish')))
    out, back, lost = (by_kind.get(kind, 0) for kind in (PeelKind.OUT, PeelKind.BACK, PeelKind.LOST))
    return {'out': out, 'back': back, 'lost': lost, 'with_them': out - back - lost}


def company_counts(company, *, through=None):
    movements = company.movements.all()
    if through is not None:
        movements = movements.filter(date__lte=through)
    return counts(movements)


def ensure_balance(company):
    """Refuse (inside the caller's transaction, so the change rolls back) if the company would
    have brought back or written off more fish than it was given."""
    with_them = company_counts(company)['with_them']
    if with_them < 0:
        raise TooManyBack(company, -with_them)


# ─── Paid months ──────────────────────────────────────────────

def paid_month(company, day):
    return PeelPaid.objects.filter(company=company, month=month_of(day)).first()


def ensure_open(company, day):
    if PeelPaid.objects.filter(company=company, month=month_of(day)).exists():
        raise PeelLocked(company, month_of(day))


def can_mark_paid(first_day, today=None):
    """A month can be marked paid from its last day on — once its batches are all in."""
    return (today or timezone.localdate()) >= month_bounds(first_day)[1]


# ─── Entries ──────────────────────────────────────────────────

def priced(company, day):
    price = company.price_on(day)
    if price is None:
        raise NoPrice(company, day)
    return price.price_per_fish


def snapshot(movement):
    return {
        'date': movement.date.isoformat(), 'kind': movement.kind, 'fish': movement.fish,
        'unit_price': int(movement.unit_price) if movement.unit_price is not None else None,
        'amount': int(movement.amount), 'note': movement.note,
    }


def set_pay(movement):
    """A batch brought back is paid at the company's price for its day; nothing else is paid."""
    if movement.kind == PeelKind.BACK:
        movement.unit_price = priced(movement.company, movement.date)
        movement.amount = movement.unit_price * movement.fish
    else:
        movement.unit_price = None
        movement.amount = 0


@transaction.atomic
def record(company, *, day, kind, fish, note='', user=None, token):
    """Save one entry. A reused `token` raises IntegrityError, so a form can only save once."""
    ensure_open(company, day)
    movement = PeelMovement(
        company=company, date=day, kind=kind, fish=fish, note=note, token=token,
        entered_by=user, entered_by_name=user_label(user),
    )
    set_pay(movement)
    movement.save()
    ensure_balance(company)
    return movement


@transaction.atomic
def update(movement, *, day, fish, note, user=None, reason=''):
    """Correct an entry's date, number of fish or note. Changing only the number keeps the
    price it was saved with; moving it to another day takes that day's price. Saving it
    unchanged writes nothing."""
    ensure_open(movement.company, movement.date)
    ensure_open(movement.company, day)
    if (day, fish, note) == (movement.date, movement.fish, movement.note):
        return movement
    before = snapshot(movement)
    moved = day != movement.date
    movement.date, movement.fish, movement.note = day, fish, note
    if moved:
        set_pay(movement)
    elif movement.kind == PeelKind.BACK:
        movement.amount = movement.unit_price * fish
    movement.save()
    ensure_balance(movement.company)
    log_movement(AuditAction.PEEL_EDIT, movement, user=user, before=before, after=snapshot(movement), reason=reason)
    return movement


@transaction.atomic
def delete(movement, *, user=None):
    ensure_open(movement.company, movement.date)
    log_movement(AuditAction.PEEL_DELETE, movement, user=user, before=snapshot(movement))
    company = movement.company
    movement.delete()
    ensure_balance(company)  # deleting fish given out can't leave more back than given


def log_movement(action, movement, *, user, before=None, after=None, reason=''):
    log(action, user=user, month=month_of(movement.date), work_date=movement.date,
        cutter_name=movement.company.name, record_id=movement.pk, before=before, after=after, reason=reason)


# ─── Prices ───────────────────────────────────────────────────

def price_snapshot(price):
    return {'price': int(price.price_per_fish), 'effective_from': price.effective_from.isoformat()}


@transaction.atomic
def set_price(company, *, day, price_per_fish, user=None):
    """Add a price from `day`, or replace the one already starting that day. Batches already
    saved keep their price."""
    price = company.prices.filter(effective_from=day).first()
    before = price_snapshot(price) if price else None
    if price is None:
        price = PeelPrice(company=company, effective_from=day, created_by=user)
    price.price_per_fish = price_per_fish
    price.save()
    after = price_snapshot(price)
    if after != before:
        log(AuditAction.PEEL_PRICE, user=user, month=month_of(day), work_date=day, cutter_name=company.name,
            before=before, after=after)
    return price


@transaction.atomic
def delete_price(price, *, user=None):
    log(AuditAction.PEEL_PRICE, user=user, month=month_of(price.effective_from), work_date=price.effective_from,
        cutter_name=price.company.name, before=price_snapshot(price))
    price.delete()


# ─── Statements ───────────────────────────────────────────────

def won_floor(amount, step=1):
    return (Decimal(amount) / step).to_integral_value(rounding=ROUND_DOWN) * step


def tax_on(amount, tax_mode):
    """(tax, total) for a month's pay. VAT is added on top (원 미만 절사). Withholding takes off
    3% income tax and 10% of that as local income tax, each rounded down to 10 won."""
    amount = Decimal(amount)
    if tax_mode == TaxMode.VAT:
        tax = won_floor(amount * Decimal('0.1'))
        return tax, amount + tax
    if tax_mode == TaxMode.WITHHOLD:
        income = won_floor(amount * Decimal('0.03'), 10)
        local = won_floor(income * Decimal('0.1'), 10)
        return income + local, amount - income - local
    return Decimal(0), amount


def statement(company, first_day):
    """A company's month: the batches brought back with their pay, the tax, the total to pay,
    and the fish count cross-check. A paid month shows the figures it was paid with."""
    first, last = month_bounds(first_day)
    in_month = company.movements.filter(date__range=(first, last))
    lines = list(in_month.filter(kind=PeelKind.BACK).order_by('date', 'created_at', 'pk'))
    amount = sum((line.amount for line in lines), Decimal(0))
    fish_back = sum(line.fish for line in lines)
    paid = paid_month(company, first)
    if paid:
        tax_mode, tax, total = paid.tax_mode, paid.tax, paid.total
    else:
        tax_mode = company.tax_mode
        tax, total = tax_on(amount, tax_mode)
    return {
        'company': company, 'first': first, 'last': last, 'paid': paid,
        'lines': lines, 'fish_back': fish_back, 'amount': amount,
        'tax_mode': tax_mode, 'tax': tax, 'total': total,
        'month_counts': counts(in_month),
        'end_counts': company_counts(company, through=last),
        'other_entries': list(in_month.exclude(kind=PeelKind.BACK).order_by('date', 'created_at', 'pk')),
    }


def months_with_entries(company):
    """Each month the company has entries in, newest first, with its counts and pay."""
    rows = (
        company.movements.order_by().values('date__year', 'date__month')
        .annotate(entries=Count('pk')).order_by('-date__year', '-date__month')
    )
    return [statement(company, date(row['date__year'], row['date__month'], 1)) for row in rows]


def signed_tax(figures):
    """Tax as it changes what we pay: VAT is added (+), withholding is kept back (−)."""
    return -figures['tax'] if figures['tax_mode'] == TaxMode.WITHHOLD else figures['tax']


def month_summary(first_day):
    """Every company with anything in the month — fish given, back or lost, fish still with them
    at its end, or a paid statement — with that month's statement figures, and the totals."""
    rows = []
    for company in PeelCompany.objects.prefetch_related('prices').order_by('name'):
        figures = statement(company, first_day)
        moved = any(figures['month_counts'][kind] for kind in ('out', 'back', 'lost'))
        if moved or figures['end_counts']['with_them'] or figures['paid']:
            rows.append({**figures, 'signed_tax': signed_tax(figures)})
    first, last = month_bounds(first_day)
    return {
        'first': first, 'last': last, 'rows': rows,
        'out': sum(row['month_counts']['out'] for row in rows),
        'back': sum(row['month_counts']['back'] for row in rows),
        'lost': sum(row['month_counts']['lost'] for row in rows),
        'with_them': sum(row['end_counts']['with_them'] for row in rows),
        'amount': sum((row['amount'] for row in rows), Decimal(0)),
        'signed_tax': sum((row['signed_tax'] for row in rows), Decimal(0)),
        'total': sum((row['total'] for row in rows), Decimal(0)),
    }


@transaction.atomic
def mark_paid(company, first_day, *, user, today=None):
    """Freeze a company's month as paid. Marking it twice changes nothing."""
    first_day = month_of(first_day)
    existing = paid_month(company, first_day)
    if existing:
        return existing
    if not can_mark_paid(first_day, today):
        raise MonthNotOver(first_day, month_bounds(first_day)[1])
    figures = statement(company, first_day)
    paid = PeelPaid.objects.create(
        company=company, month=first_day, fish=figures['fish_back'], amount=figures['amount'],
        tax_mode=figures['tax_mode'], tax=figures['tax'], total=figures['total'],
        paid_by=user, paid_by_name=user_label(user),
    )
    log(AuditAction.PEEL_PAID, user=user, month=first_day, cutter_name=company.name,
        after={'fish': paid.fish, 'amount': int(paid.amount), 'tax': int(paid.tax), 'total': int(paid.total)})
    return paid


@transaction.atomic
def reopen(company, first_day, *, user, reason):
    """Reopen a paid month; the reason goes into the change log. False if it wasn't paid."""
    paid = paid_month(company, first_day)
    if paid is None:
        return False
    before = {'fish': paid.fish, 'amount': int(paid.amount), 'tax': int(paid.tax), 'total': int(paid.total),
              'paid_by': paid.paid_by_name}
    paid.delete()
    log(AuditAction.PEEL_UNPAID, user=user, month=month_of(first_day), cutter_name=company.name,
        before=before, reason=reason)
    return True
