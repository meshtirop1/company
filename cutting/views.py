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
from django.db import IntegrityError
from django.db.models import Prefetch, ProtectedError, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import exports, reports, services
from .forms import (
    BatchEntryForm, CutterForm, PriceItemCreateForm, PriceItemEditForm, PriceRateForm, RecordEditForm,
    ordered_items,
)
from .i18n import STRINGS, get_lang
from .models import CutBatch, CutRecord, Cutter, CuttingStyle, PriceItem, PriceRate


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
    return render_page(
        request, 'hub.html',
        today_summary=T['stat_today_value'].format(rows=today_records.count(), total=won(today_total)),
        active_cutters=Cutter.objects.filter(is_active=True).count(),
        priced_items=PriceItem.objects.filter(is_active=True).count(),
    )


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
            item = form.save(user=request.user)
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
            rate = form.save(user=request.user)
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
        form = PriceRateForm(request.POST, instance=rate, item=item, T=T)
        if form.is_valid():
            form.save(user=request.user)
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


def same_work(batch, form):
    """True when a valid post repeats exactly what `batch` already holds — a double tap."""
    if batch.work_date != form.cleaned_data['work_date']:
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
            else:
                total = batch.records.aggregate(total=Sum('total'))['total']
                messages.success(request, T['batch_saved'].format(
                    count=len(form.rows), date=batch.work_date.isoformat(), total=won(total),
                ))
                return redirect('cutting:day', batch.work_date)

        if spent is not None:
            # This form's token was used already — most often a form brought back with the Back
            # button. The very same work again is a double tap. Anything else is new work: it is
            # never dropped, and never saved unseen — it comes back under a fresh token to confirm.
            if form.is_valid() and same_work(spent, form):
                return already_saved(request, T, spent)
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
        js_text={'per_box': T['js_per_box'], 'no_rate': T['js_no_rate'], 'summary': T['js_summary']},
    )


def entered_by_label(batch):
    return batch.entered_by_name or services.user_label(batch.entered_by) or '—'


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
    blocks, day_total = [], 0
    for batch in batches:
        rows = list(batch.records.all())
        batch_total = sum(record.total for record in rows)
        day_total += batch_total
        blocks.append({
            'batch': batch,
            'entered_by': entered_by_label(batch),
            'total': batch_total,
            'confirm_delete': T['confirm_delete_batch'].format(count=len(rows)),
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
        can_enter=day <= today,
        is_today=day == today,
    )


@manager_required
def record_edit(request, pk):
    T = strings(request)
    record = get_object_or_404(CutRecord.objects.select_related('cutter', 'item'), pk=pk)
    heading = T['edit_record_title'].format(name=record.cutter.name, date=record.work_date.isoformat())
    if request.method == 'POST':
        form = RecordEditForm(request.POST, T=T, record=record, items=entry_items())
        if form.is_valid():
            try:
                services.update_record(record, item=form.cleaned_data['item'], boxes=form.cleaned_data['boxes'])
            except services.NoRate as missing:
                messages.error(request, T['err_no_rate'].format(item=missing.item, date=missing.day.isoformat()))
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
    services.delete_record(record)
    messages.success(request, T['record_deleted'].format(name=name))
    return redirect('cutting:day', work_date)


@manager_required
@require_POST
def batch_delete(request, pk):
    T = strings(request)
    batch = get_object_or_404(CutBatch, pk=pk)
    work_date, count = batch.work_date, batch.records.count()
    services.delete_batch(batch)
    messages.success(request, T['batch_deleted'].format(count=count))
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
    return render_page(
        request, 'month.html',
        month=month,
        heading=T['month_title'].format(month=month_label(month)),
        summary=reports.month_summary(month),
        previous_month=(month - timedelta(days=1)).replace(day=1),
        next_month=next_month(month) if month < this_month() else None,
        is_current=month == this_month(),
    )


@manager_required
def cutter_report(request, month, cutter_pk):
    T = strings(request)
    cutter = get_object_or_404(Cutter, pk=cutter_pk)
    return render_page(
        request, 'cutter_month.html',
        month=month,
        heading=T['cutter_month_title'].format(name=cutter.name, month=month_label(month)),
        data=reports.cutter_month(cutter, month),
    )


@manager_required
def month_export(request, month):
    response = HttpResponse(
        exports.month_workbook_bytes(month, strings(request)),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="fish-cutting-{month_label(month)}.xlsx"'
    return response


def render_payslips(request, month, slips):
    """The printable payslip sheet (a standalone page, like the employees' payslip)."""
    lang = get_lang(request)
    for slip in slips:
        for group in slip['style_groups']:
            group['subtotal_label'] = STRINGS[lang]['subtotal'].format(style=group['label'])
    return render(request, 'cutting/payslip.html', {
        'T': STRINGS[lang],
        'lang': lang,
        'slips': slips,
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
