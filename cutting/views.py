"""Supervisor pages for the fish-cutting pay module.

Only managers (is_admin) and superusers may use them; anyone else gets the 403 page.
Every page renders one shared template with the session language's strings (see i18n.py).
"""
import uuid
from datetime import date, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, ProtectedError, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_POST

from . import exports, reports, services
from .forms import (
    BatchEntryForm, CutterForm, PriceItemCreateForm, PriceItemEditForm, PriceRateForm, RecordEditForm,
    UnlockForm, ordered_items,
)
from .i18n import STRINGS, counted, get_lang
from .models import AuditAction, AuditEntry, CutBatch, CutRecord, Cutter, CuttingStyle, PriceItem, PriceRate
from .templatetags.cutting_tags import signed_won


def manager_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not (request.user.is_admin or request.user.is_superuser):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def strings(request):
    return STRINGS[get_lang(request)]


def render_page(request, template, **context):
    lang = get_lang(request)
    context.update(T=STRINGS[lang], lang=lang, base_template=f'base_{lang}.html')
    return render(request, f'cutting/{template}', context)


def won(amount):
    return f'{int(amount):,}'


def to_item(item):
    """Back to the price list, scrolled to the line that was just changed."""
    return redirect(f"{reverse('cutting:prices')}#item-{item.pk}")


def posted_active(request):
    """The target state sent by an activate/deactivate button, so a double tap is harmless."""
    return request.POST.get('active') == '1'


# ─── Hub ──────────────────────────────────────────────────────

@manager_required
def hub(request):
    T = strings(request)
    today_records = CutRecord.objects.filter(work_date=timezone.localdate())
    today_total = today_records.aggregate(total=Sum('total'))['total'] or 0
    rows = today_records.count()
    return render_page(
        request, 'hub.html',
        today_summary=counted(T, 'stat_today_value', rows).format(rows=rows, total=won(today_total)),
        active_cutters=Cutter.objects.filter(is_active=True).count(),
        priced_items=PriceItem.objects.filter(is_active=True).count(),
    )


HELP_SECTIONS = (('daily', 3), ('fix', 2), ('month', 3), ('prices', 2))


@manager_required
def help_page(request):
    T = strings(request)
    sections = [
        {'title': T[f'help_{key}_title'], 'steps': [T[f'help_{key}_{n}'] for n in range(1, count + 1)]}
        for key, count in HELP_SECTIONS
    ]
    return render_page(request, 'help.html', sections=sections)


# ─── Cutters ──────────────────────────────────────────────────

@manager_required
def cutters(request):
    T = strings(request)
    if request.method == 'POST':
        form = CutterForm(request.POST, T=T)
        if form.is_valid():
            cutter = form.save()
            messages.success(request, T['cutter_added'].format(name=cutter.name))
            return redirect('cutting:cutters')
        messages.error(request, T['err_form'])
    else:
        form = CutterForm(T=T)

    inactive_rows = [
        {'cutter': cutter, 'confirm_delete': T['confirm_delete_cutter'].format(name=cutter.name)}
        for cutter in Cutter.objects.filter(is_active=False)
    ]
    return render_page(
        request, 'cutters.html',
        form=form,
        active=Cutter.objects.filter(is_active=True),
        inactive_rows=inactive_rows,
    )


@manager_required
def cutter_edit(request, pk):
    T = strings(request)
    cutter = get_object_or_404(Cutter, pk=pk)
    heading = T['edit_cutter'].format(name=cutter.name)  # before the form can touch the instance
    if request.method == 'POST':
        form = CutterForm(request.POST, instance=cutter, T=T)
        if form.is_valid():
            form.save()
            messages.success(request, T['cutter_saved'].format(name=cutter.name))
            return redirect('cutting:cutters')
        messages.error(request, T['err_form'])
    else:
        form = CutterForm(instance=cutter, T=T)
    return render_page(request, 'cutter_edit.html', form=form, heading=heading)


@manager_required
@require_POST
def cutter_set_active(request, pk):
    T = strings(request)
    cutter = get_object_or_404(Cutter, pk=pk)
    cutter.is_active = posted_active(request)
    cutter.save(update_fields=['is_active', 'updated_at'])
    key = 'cutter_activated' if cutter.is_active else 'cutter_deactivated'
    messages.success(request, T[key].format(name=cutter.name))
    return redirect('cutting:cutters')


@manager_required
@require_POST
def cutter_delete(request, pk):
    T = strings(request)
    cutter = get_object_or_404(Cutter, pk=pk)
    name = cutter.name
    try:
        cutter.delete()
    except ProtectedError:
        messages.error(request, T['cutter_in_use'].format(name=name))
    else:
        messages.success(request, T['cutter_deleted'].format(name=name))
    return redirect('cutting:cutters')


# ─── Price list ───────────────────────────────────────────────

def price_groups(T):
    """The price list grouped by style, each line with today's rate, upcoming rates and history."""
    today = timezone.localdate()
    rows_by_style = {value: [] for value in CuttingStyle.values}
    for item in PriceItem.objects.prefetch_related('rates').order_by('sort_order', 'pk'):
        history = sorted(item.rates.all(), key=lambda rate: rate.effective_from, reverse=True)
        current = item.rate_on(today)
        upcoming = [rate for rate in reversed(history) if rate.effective_from > today]
        rows_by_style[item.style].append({
            'item': item,
            'current': current,
            'current_since': T['since'].format(date=current.effective_from.isoformat()) if current else '',
            'upcoming': [
                T['upcoming_rate'].format(date=rate.effective_from.isoformat(), price=won(rate.unit_price))
                for rate in upcoming
            ],
            'history': [{'rate': rate, 'is_current': rate == current} for rate in history],
            'can_delete_rate': len(history) > 1,
            'confirm_delete_item': T['confirm_delete_item'].format(item=item),
        })
    return [
        {'style': value, 'label': label, 'desc': T[f'style_{value}_desc'], 'rows': rows_by_style[value]}
        for value, label in CuttingStyle.choices
    ]


@manager_required
def prices(request):
    T = strings(request)
    if request.method == 'POST':
        form = PriceItemCreateForm(request.POST, T=T)
        if form.is_valid():
            with transaction.atomic():
                item = form.save(user=request.user)
                services.log_rate(AuditAction.RATE_ADD, user=request.user,
                                  after=services.rate_snapshot(item.rates.get()))
            messages.success(request, T['item_added'].format(item=item, price=won(form.cleaned_data['unit_price'])))
            return to_item(item)
        messages.error(request, T['err_form'])
    else:
        form = PriceItemCreateForm(T=T)
    return render_page(request, 'prices.html', form=form, groups=price_groups(T))


@manager_required
def item_edit(request, pk):
    T = strings(request)
    item = get_object_or_404(PriceItem, pk=pk)
    heading = T['edit_item'].format(item=item)
    if request.method == 'POST':
        form = PriceItemEditForm(request.POST, instance=item, T=T)
        if form.is_valid():
            form.save()
            messages.success(request, T['item_saved'].format(item=item))
            return to_item(item)
        messages.error(request, T['err_form'])
    else:
        form = PriceItemEditForm(instance=item, T=T)
    return render_page(request, 'item_edit.html', form=form, item=item, heading=heading)


@manager_required
@require_POST
def item_set_active(request, pk):
    T = strings(request)
    item = get_object_or_404(PriceItem, pk=pk)
    item.is_active = posted_active(request)
    item.save(update_fields=['is_active', 'updated_at'])
    key = 'item_activated' if item.is_active else 'item_deactivated'
    messages.success(request, T[key].format(item=item))
    return to_item(item)


@manager_required
@require_POST
def item_delete(request, pk):
    T = strings(request)
    item = get_object_or_404(PriceItem, pk=pk)
    label = str(item)
    try:
        item.delete()
    except ProtectedError:
        messages.error(request, T['item_in_use'].format(item=label))
        return to_item(item)
    messages.success(request, T['item_deleted'].format(item=label))
    return redirect('cutting:prices')


# ─── Rates ────────────────────────────────────────────────────

def render_rate_form(request, form, item, heading):
    history = item.rates.order_by('-effective_from')
    return render_page(request, 'rate_form.html', form=form, item=item, heading=heading, history=history)


@manager_required
def rate_add(request, item_pk):
    T = strings(request)
    item = get_object_or_404(PriceItem, pk=item_pk)
    if request.method == 'POST':
        form = PriceRateForm(request.POST, item=item, T=T)
        if form.is_valid():
            with transaction.atomic():
                rate = form.save(user=request.user)
                services.log_rate(AuditAction.RATE_ADD, user=request.user, after=services.rate_snapshot(rate))
            messages.success(request, T['rate_added'].format(
                item=item, price=won(rate.unit_price), date=rate.effective_from.isoformat(),
            ))
            return to_item(item)
        messages.error(request, T['err_form'])
    else:
        form = PriceRateForm(item=item, T=T)
    return render_rate_form(request, form, item, T['add_rate_title'].format(item=item))


@manager_required
def rate_edit(request, pk):
    T = strings(request)
    rate = get_object_or_404(PriceRate.objects.select_related('item'), pk=pk)
    item = rate.item
    if request.method == 'POST':
        before = services.rate_snapshot(rate)  # the form writes into `rate` as it validates
        form = PriceRateForm(request.POST, instance=rate, item=item, T=T)
        if form.is_valid():
            with transaction.atomic():
                form.save(user=request.user)
                after = services.rate_snapshot(rate)
                if after != before:
                    services.log_rate(AuditAction.RATE_EDIT, user=request.user, before=before, after=after)
            messages.success(request, T['rate_saved'].format(item=item))
            return to_item(item)
        messages.error(request, T['err_form'])
    else:
        form = PriceRateForm(instance=rate, item=item, T=T)
    return render_rate_form(request, form, item, T['edit_rate_title'].format(item=item))


@manager_required
@require_POST
def rate_delete(request, pk):
    T = strings(request)
    rate = get_object_or_404(PriceRate.objects.select_related('item'), pk=pk)
    item = rate.item
    if item.rates.count() <= 1:
        # Deleting the last rate would leave the size with no price to look up.
        messages.error(request, T['rate_only_one'].format(item=item))
    else:
        started = rate.effective_from.isoformat()
        with transaction.atomic():
            services.log_rate(AuditAction.RATE_DELETE, user=request.user, before=services.rate_snapshot(rate))
            rate.delete()
        messages.success(request, T['rate_deleted'].format(item=item, date=started))
    return to_item(item)


# ─── Work entry ───────────────────────────────────────────────

def parse_day(value, default):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


def saved_batch(token):
    """The batch already saved with this form token, if any."""
    try:
        return CutBatch.objects.filter(token=uuid.UUID(str(token))).first()
    except ValueError:
        return None


def entry_items():
    return ordered_items(PriceItem.objects.filter(is_active=True).prefetch_related('rates'))


def price_data(items):
    """Every active size's rate history, for the entry page's live pay preview."""
    return {
        str(item.pk): {
            'style': item.style,
            'rates': [[rate.effective_from.isoformat(), int(rate.unit_price)] for rate in item.rates.all()],
        }
        for item in items
    }


def already_saved(request, T, batch):
    messages.info(request, T['batch_already_saved'])
    return redirect('cutting:day', batch.work_date)


def posted_day(form):
    """The form's work date — parsed from the post when validation refused it (e.g. a locked month)."""
    return form.cleaned_data.get('work_date') or parse_day(form.data.get('work_date'), None)


def same_work(batch, form):
    """True when a post repeats exactly what `batch` already holds — a double tap, or Back and
    Save again. Still true if the month has been locked since: the lock only refuses its date,
    and the work is already saved, not missing."""
    form.is_valid()
    if set(form.errors) - {'work_date'} or batch.work_date != posted_day(form):
        return False
    saved = sorted(batch.records.values_list('cutter_id', 'item_id', 'boxes'))
    return saved == sorted((cutter.pk, item.pk, boxes) for cutter, item, boxes in form.rows)


def with_fresh_token(post):
    data = post.copy()
    data['token'] = str(uuid.uuid4())
    return data


@manager_required
def entry(request):
    T = strings(request)
    today = timezone.localdate()
    cutters = Cutter.objects.filter(is_active=True)
    items = entry_items()

    if request.method == 'POST':
        form = BatchEntryForm(request.POST, T=T, cutters=cutters, items=items)
        spent = saved_batch(request.POST.get('token'))
        if spent is None and form.is_valid():
            data = form.cleaned_data
            try:
                batch = services.save_batch(
                    work_date=data['work_date'], rows=form.rows, entered_by=request.user, token=data['token'],
                )
            except IntegrityError:
                spent = saved_batch(data['token'])  # the same form, saved by a simultaneous request
                if spent is None:
                    raise
            except services.NoRate as missing:  # a rate removed while the form was open
                messages.error(request, T['err_no_rate'].format(item=missing.item, date=missing.day.isoformat()))
            except services.MonthLocked as locked:  # the month was locked while the form was open
                messages.error(request, locked_message(T, locked.month))
            else:
                total = batch.records.aggregate(total=Sum('total'))['total']
                messages.success(request, counted(T, 'batch_saved', len(form.rows)).format(
                    count=len(form.rows), date=batch.work_date.isoformat(), total=won(total),
                ))
                return redirect('cutting:day', batch.work_date)

        if spent is None and 'token' in form.errors:
            # A missing or mangled form token (an old page, or a tampered post): nothing to save it
            # under, so the rows come back under a fresh token — one more tap of Save files them.
            messages.warning(request, T['err_form_expired'])
            form = BatchEntryForm(with_fresh_token(request.POST), T=T, cutters=cutters, items=items)
            form.is_valid()
        elif spent is not None:
            # This form's token was used already — most often a form brought back with the Back
            # button. The very same work again is a double tap. Anything else is new work: it is
            # never dropped, and never saved unseen — it comes back under a fresh token to confirm.
            if same_work(spent, form):
                return already_saved(request, T, spent)
            day = posted_day(form)
            if day and services.lock_for(day):
                # Different work, but for a locked month: "tap Save to add them" could only fail.
                messages.error(request, locked_message(T, services.month_of(day)))
            else:
                messages.warning(request, T['err_token_spent'].format(
                    date=spent.work_date.isoformat(), time=timezone.localtime(spent.created_at).strftime('%H:%M'),
                ))
            form = BatchEntryForm(with_fresh_token(request.POST), T=T, cutters=cutters, items=items)
            form.is_valid()  # show any row errors alongside the notice
        elif form.errors:
            messages.error(request, T['err_batch_rows'])
    else:
        day = min(parse_day(request.GET.get('date'), today), today)
        first = items[0] if items else None
        form = BatchEntryForm(T=T, cutters=cutters, items=items, initial={
            'token': uuid.uuid4(),
            'work_date': day,
            'style': first.style if first else CuttingStyle.TONGPO,
            'item': str(first.pk) if first else '',
        })

    return render_page(
        request, 'entry.html',
        form=form,
        rows=list(form.entry_rows()),
        has_items=bool(items),
        today=today,
        price_data=price_data(items),
        js_text={'per_box': T['js_per_box'], 'no_rate': T['js_no_rate'],
                 'summary': T['js_summary'], 'summary_one': T['js_summary_one']},
    )


def entered_by_label(batch):
    return batch.entered_by_name or services.user_label(batch.entered_by) or '—'


def locked_message(T, month):
    return T['err_month_locked'].format(month=f'{month:%Y-%m}')


def lock_banner(T, lock):
    """'🔒 2026-09 is locked (paid) — by …, on …' for a locked month's pages, else ''."""
    if lock is None:
        return ''
    return T['locked_banner'].format(
        month=f'{lock.month:%Y-%m}', name=lock.locked_by_name or '—',
        when=timezone.localtime(lock.locked_at).strftime('%Y-%m-%d %H:%M'),
    )


def refuse_if_locked(request, T, day):
    """The day page with an explanation, when `day` is in a locked month; else None."""
    if services.lock_for(day):
        messages.error(request, locked_message(T, services.month_of(day)))
        return redirect('cutting:day', day)
    return None


@manager_required
def day(request, day=None):
    if day is None:
        if 'date' in request.GET:  # the "go to date" box
            return redirect('cutting:day', parse_day(request.GET['date'], timezone.localdate()))
        day = timezone.localdate()
    T = strings(request)
    today = timezone.localdate()
    records = CutRecord.objects.select_related('cutter').order_by('cutter__name', 'pk')
    batches = (
        CutBatch.objects.filter(work_date=day)
        .select_related('entered_by')
        .prefetch_related(Prefetch('records', queryset=records))
        .order_by('created_at')
    )
    lock = services.lock_for(day)
    blocks, day_total = [], 0
    for batch in batches:
        rows = list(batch.records.all())
        batch_total = sum(record.total for record in rows)
        day_total += batch_total
        blocks.append({
            'batch': batch,
            'entered_by': entered_by_label(batch),
            'total': batch_total,
            'confirm_delete': counted(T, 'confirm_delete_batch', len(rows)).format(count=len(rows)),
            'rows': [
                {'record': record, 'confirm_delete': T['confirm_delete_record'].format(name=record.cutter.name)}
                for record in rows
            ],
        })
    return render_page(
        request, 'day.html',
        day=day,
        heading=T['day_title'].format(date=day.isoformat()),
        by_cutter=reports.day_summary(day),
        blocks=blocks,
        day_total=day_total,
        previous_day=day - timedelta(days=1),
        next_day=day + timedelta(days=1) if day < today else None,
        can_enter=day <= today and lock is None,
        is_today=day == today,
        locked=lock is not None,
        lock_banner=lock_banner(T, lock),
        month=services.month_of(day),
    )


@manager_required
def record_edit(request, pk):
    T = strings(request)
    record = get_object_or_404(CutRecord.objects.select_related('cutter', 'item'), pk=pk)
    refused = refuse_if_locked(request, T, record.work_date)
    if refused:
        return refused
    heading = T['edit_record_title'].format(name=record.cutter.name, date=record.work_date.isoformat())
    if request.method == 'POST':
        form = RecordEditForm(request.POST, T=T, record=record, items=entry_items())
        if form.is_valid():
            data = form.cleaned_data
            if data['item'].pk == record.item_id and data['boxes'] == record.boxes:
                # Saving it as it was changes nothing, so nothing (not even a reason) is logged.
                messages.info(request, T['record_unchanged'])
                return redirect('cutting:day', record.work_date)
            try:
                services.update_record(
                    record, item=data['item'], boxes=data['boxes'], user=request.user, reason=data['reason'],
                )
            except services.NoRate as missing:
                messages.error(request, T['err_no_rate'].format(item=missing.item, date=missing.day.isoformat()))
            except services.MonthLocked:
                return refuse_if_locked(request, T, record.work_date)
            else:
                messages.success(request, T['record_saved'].format(name=record.cutter.name))
                return redirect('cutting:day', record.work_date)
        else:
            messages.error(request, T['err_form'])
    else:
        form = RecordEditForm(T=T, record=record, items=entry_items())
    return render_page(request, 'record_edit.html', form=form, record=record, heading=heading)


@manager_required
@require_POST
def record_delete(request, pk):
    T = strings(request)
    record = get_object_or_404(CutRecord.objects.select_related('cutter', 'batch'), pk=pk)
    work_date, name = record.work_date, record.cutter.name
    try:
        services.delete_record(record, user=request.user)
    except services.MonthLocked:
        return refuse_if_locked(request, T, work_date)
    messages.success(request, T['record_deleted'].format(name=name))
    return redirect('cutting:day', work_date)


@manager_required
@require_POST
def batch_delete(request, pk):
    T = strings(request)
    batch = get_object_or_404(CutBatch, pk=pk)
    work_date, count = batch.work_date, batch.records.count()
    try:
        services.delete_batch(batch, user=request.user)
    except services.MonthLocked:
        return refuse_if_locked(request, T, work_date)
    messages.success(request, counted(T, 'batch_deleted', count).format(count=count))
    return redirect('cutting:day', work_date)


# ─── Reports ──────────────────────────────────────────────────

def this_month():
    return timezone.localdate().replace(day=1)


def month_label(first_day):
    return first_day.strftime('%Y-%m')


def parse_month(value, default):
    """'2026-10' from the month picker → date(2026, 10, 1)."""
    try:
        year, month = value.split('-')
        return date(int(year), int(month), 1)
    except (AttributeError, ValueError):
        return default


def next_month(first_day):
    return (first_day.replace(day=28) + timedelta(days=4)).replace(day=1)


@manager_required
def month_report(request, month=None):
    if month is None:
        if 'month' in request.GET:  # the "go to month" box
            return redirect('cutting:month', parse_month(request.GET['month'], this_month()))
        month = this_month()
    T = strings(request)
    label = month_label(month)
    lock = services.lock_for(month)
    stale = [] if lock else services.stale_records(month)
    return render_page(
        request, 'month.html',
        month=month,
        heading=T['month_title'].format(month=label),
        provisional=reports.provisional_note(T, month),
        summary=reports.month_summary(month),
        previous_month=(month - timedelta(days=1)).replace(day=1),
        next_month=next_month(month) if month < this_month() else None,
        is_current=month == this_month(),
        lock=lock,
        lock_banner=lock_banner(T, lock),
        can_lock=lock is None and services.can_lock(month),
        lock_not_yet=T['lock_not_yet'].format(date=reports.month_bounds(month)[1].isoformat()),
        confirm_lock=T['confirm_lock'].format(month=label),
        unlock_form=UnlockForm(T=T) if lock else None,
        stale_notice=counted(T, 'stale_notice', len(stale)).format(count=len(stale)) if stale else '',
        log_url=f"{reverse('cutting:audit')}?month={label}",
    )


@manager_required
def cutter_report(request, month, cutter_pk):
    T = strings(request)
    cutter = get_object_or_404(Cutter, pk=cutter_pk)
    return render_page(
        request, 'cutter_month.html',
        month=month,
        heading=T['cutter_month_title'].format(name=cutter.name, month=month_label(month)),
        provisional=reports.provisional_note(T, month),
        lock_banner=lock_banner(T, services.lock_for(month)),
        data=reports.cutter_month(cutter, month),
    )


# ─── Month lock and re-pricing ────────────────────────────────

@manager_required
@require_POST
def month_lock(request, month):
    T = strings(request)
    try:
        services.lock_month(month, user=request.user)
    except services.MonthNotOver as early:
        messages.error(request, T['err_lock_early'].format(month=month_label(month), date=early.last_day.isoformat()))
    else:
        messages.success(request, T['month_locked_done'].format(month=month_label(month)))
    return redirect('cutting:month', month)


@manager_required
@require_POST
def month_unlock(request, month):
    T = strings(request)
    form = UnlockForm(request.POST, T=T)
    if not form.is_valid():
        messages.error(request, form.errors['reason'][0])
    elif services.unlock_month(month, user=request.user, reason=form.cleaned_data['reason']):
        messages.success(request, T['month_unlocked'].format(month=month_label(month)))
    return redirect('cutting:month', month)


def reprice_plan(month):
    stale = services.stale_records(month)
    rows = []
    for record, list_price in stale:
        new_total = list_price * record.boxes if list_price is not None else None
        rows.append({
            'record': record, 'list_price': list_price, 'new_total': new_total,
            'change': new_total - record.total if new_total is not None else None,
        })
    plan = [(record, price) for record, price in stale if price is not None]
    return rows, plan


@manager_required
def reprice(request, month):
    """Review the month's entries whose saved price no longer matches the price list, and
    bring them to the list price in one go."""
    T = strings(request)
    label = month_label(month)
    if services.lock_for(month):
        messages.error(request, locked_message(T, month))
        return redirect('cutting:month', month)

    if request.method == 'POST':
        try:
            changed, delta = services.reprice_month(month, user=request.user, expected=request.POST.get('plan', ''))
        except services.MonthLocked:
            messages.error(request, locked_message(T, month))
            return redirect('cutting:month', month)
        except services.PlanChanged:
            messages.warning(request, T['reprice_changed'])
            return redirect('cutting:reprice', month)
        if changed:
            messages.success(request, counted(T, 'reprice_done', changed).format(count=changed, delta=signed_won(delta)))
        else:
            messages.info(request, T['reprice_none'].format(month=label))
        return redirect('cutting:month', month)

    rows, plan = reprice_plan(month)
    fixable = len(plan)
    delta = sum(row['change'] for row in rows if row['change'] is not None)
    return render_page(
        request, 'reprice.html',
        month=month,
        heading=T['reprice_title'].format(month=label),
        rows=rows,
        fixable=fixable,
        plan_token=services.plan_token(plan),
        no_rate=len(rows) - fixable,
        apply_label=counted(T, 'reprice_apply', fixable).format(count=fixable),
        confirm=counted(T, 'confirm_reprice', fixable).format(count=fixable, delta=signed_won(delta)),
        total_change=T['reprice_total_change'].format(delta=signed_won(delta)),
        no_rate_note=counted(T, 'reprice_no_rate', len(rows) - fixable).format(count=len(rows) - fixable),
        none_note=T['reprice_none'].format(month=label),
    )


# ─── Change log ───────────────────────────────────────────────

LOG_PAGE_SIZE = 50
RATE_ACTIONS = {AuditAction.RATE_ADD, AuditAction.RATE_EDIT, AuditAction.RATE_DELETE}
STYLE_LABELS = dict(CuttingStyle.choices)


def record_text(data):
    """'통포 7 · 10 × ₩4,000 = ₩40,000' from a change-log snapshot."""
    style = STYLE_LABELS.get(data['style'], data['style'])
    return f"{style} {data['size']} · {data['boxes']} × ₩{won(data['unit_price'])} = ₩{won(data['total'])}"


def change_texts(T, entry):
    """The before and after of a change-log entry, as text."""
    if entry.action in RATE_ACTIONS:
        def text(data):
            return T['rate_line'].format(item=data['item'], price=won(data['unit_price']), date=data['effective_from'])
    elif entry.action == AuditAction.UNLOCK:
        def text(data):
            return T['was_locked'].format(name=data.get('locked_by') or '—', when=data.get('locked_at', '')[:16].replace('T', ' '))
    elif entry.action == AuditAction.LOCK:
        return '', ''
    else:
        text = record_text
    return (text(entry.before) if entry.before else ''), (text(entry.after) if entry.after else '')


def entered_text(T, entry):
    """Who first entered a deleted row, and when."""
    data = entry.before or {}
    if entry.action not in (AuditAction.DELETE_RECORD, AuditAction.DELETE_BATCH) or 'saved_at' not in data:
        return ''
    return T['entered_note'].format(name=data.get('entered_by') or '—', when=data['saved_at'][:16].replace('T', ' '))


@manager_required
def audit_log(request):
    T = strings(request)
    month = parse_month(request.GET.get('month'), None)
    entries = AuditEntry.objects.all()
    if month:
        entries = entries.filter(month=month)
    page = Paginator(entries, LOG_PAGE_SIZE).get_page(request.GET.get('page'))
    rows = []
    for entry in page:
        before, after = change_texts(T, entry)
        rows.append({
            'entry': entry,
            'action': T[f'action_{entry.action}'],
            'when': timezone.localtime(entry.at).strftime('%Y-%m-%d %H:%M'),
            'before': before,
            'after': after,
            'entered': entered_text(T, entry),
            'is_rate': entry.action in RATE_ACTIONS,
        })
    query = f'month={month_label(month)}&' if month else ''
    return render_page(
        request, 'audit.html',
        heading=T['audit_month_title'].format(month=month_label(month)) if month else T['audit_title'],
        month=month,
        rows=rows,
        page=page,
        page_label=T['page_of'].format(page=page.number, pages=page.paginator.num_pages),
        page_query=query,
    )


@manager_required
def month_export(request, month):
    T = strings(request)
    response = HttpResponse(
        exports.month_workbook_bytes(month, T),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    # In the page's language; a Korean name goes out RFC 5987-encoded (filename*=utf-8''…).
    response['Content-Disposition'] = content_disposition_header(True, T['xl_filename'].format(month=month_label(month)))
    return response


def render_payslips(request, month, slips):
    """The printable payslip sheet (a standalone page, like the employees' payslip).

    Each slip prints in its cutter's payslip language (else the screen's), so a mixed crew
    each get one they can read. `?slip_lang=en|ko` prints every slip on the page in that
    language instead.
    """
    screen_lang = get_lang(request)
    forced = request.GET.get('slip_lang')
    forced = forced if forced in STRINGS else None
    for slip in slips:
        slip['lang'] = forced or slip['cutter'].payslip_language or screen_lang
        slip['T'] = T = STRINGS[slip['lang']]
        slip['provisional'] = reports.provisional_note(T, month)
        for group in slip['style_groups']:
            group['subtotal_label'] = T['subtotal'].format(style=group['label'])
    lang = slips[0]['lang'] if len(slips) == 1 else (forced or screen_lang)
    T = STRINGS[lang]
    # One cutter's slip is titled with their name, so each saved PDF gets its own file name.
    title = T['payslip_title'] + ' — ' + month_label(month)
    if len(slips) == 1:
        title = f"{slips[0]['cutter'].name} — {title}"
    return render(request, 'cutting/payslip.html', {
        'T': T,
        'lang': lang,
        'slips': slips,
        'title': title,
        'forced': forced,
        'month_label': month_label(month),
        'back_url': reverse('cutting:month', args=[month]),
        'generated': timezone.localtime(),
    })


@manager_required
def payslip(request, month, cutter_pk):
    cutter = get_object_or_404(Cutter, pk=cutter_pk)
    return render_payslips(request, month, [reports.cutter_month(cutter, month)])


@manager_required
def payslips(request, month):
    """Every payslip for the month, one per page, ready to print in one go."""
    slips = [reports.cutter_month(cutter, month) for cutter in reports.cutters_paid_in(month)]
    return render_payslips(request, month, slips)
