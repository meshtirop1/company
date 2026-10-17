"""Supervisor pages for skin peeling by outside companies (see cutting/peeling.py)."""
import uuid
from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import peeling
from .forms import UnlockForm
from .i18n import STRINGS, get_lang
from .models import PeelCompany, PeelKind, PeelMovement, PeelPrice, TaxMode
from .peeling_forms import PeelCompanyForm, PeelEditForm, PeelEntryForm, PeelPriceForm
from .views import manager_required, month_label, next_month, render_page, strings, this_month, won

ENTRIES_PAGE_SIZE = 50


def kind_label(T, kind):
    return T[f'pl_kind_{kind}']


def tax_label(T, tax_mode):
    return T[f'pl_tax_{tax_mode}']


def tax_line_label(T, tax_mode):
    return {TaxMode.VAT: T['pl_vat_line'], TaxMode.WITHHOLD: T['pl_withhold_line']}.get(tax_mode, '')


def fish_text(count):
    return f'{int(count):,}'


def check_text(T, totals):
    """'Given 7,000 = brought back 6,000 + lost 20 + still with them 980'."""
    return T['pl_check'].format(**{key: fish_text(value) for key, value in totals.items()})


def to_company(company, anchor=''):
    return redirect(reverse('cutting:peel_company', args=[company.pk]) + anchor)


def locked_message(T, locked):
    return T['pl_err_locked'].format(company=locked.company.name, month=month_label(locked.month))


# ─── Home ─────────────────────────────────────────────────────

@manager_required
def peel_home(request):
    T = strings(request)
    month = this_month()
    rows, inactive = [], []
    for company in PeelCompany.objects.prefetch_related('prices'):
        totals = peeling.company_counts(company)
        price = company.price_on(timezone.localdate())
        row = {
            'company': company, 'totals': totals,
            'price': T['pl_per_fish'].format(price=won(price.price_per_fish)) if price else T['pl_no_price'],
            'owed': peeling.statement(company, month)['total'],
        }
        (rows if company.is_active else inactive).append(row)
    return render_page(
        request, 'peeling/home.html',
        rows=rows, inactive=inactive,
        with_them_all=sum(row['totals']['with_them'] for row in rows + inactive),
        owed_all=sum(row['owed'] for row in rows + inactive),
    )


# ─── Entries ──────────────────────────────────────────────────

def saved_movement(token):
    try:
        return PeelMovement.objects.filter(token=uuid.UUID(str(token))).first()
    except ValueError:
        return None


def entry_context(T, form):
    """Each active company's price and what it still has, for the hints beside the form."""
    today = timezone.localdate()
    hints = []
    for company in PeelCompany.objects.filter(is_active=True).prefetch_related('prices'):
        price = company.price_on(today)
        hints.append({
            'company': company,
            'with_them': fish_text(peeling.company_counts(company)['with_them']),
            'price': won(price.price_per_fish) if price else None,
        })
    return {'form': form, 'hints': hints}


@manager_required
def peel_entry(request):
    T = strings(request)
    if request.method == 'POST':
        form = PeelEntryForm(request.POST, T=T)
        spent = saved_movement(request.POST.get('token'))
        if spent is not None:
            messages.info(request, T['pl_already_saved'])
            return to_company(spent.company, '#entries')
        if form.is_valid():
            data = form.cleaned_data
            company = data['company']
            try:
                movement = peeling.record(
                    company, day=data['date'], kind=data['kind'], fish=data['fish'], note=data['note'],
                    user=request.user, token=data['token'],
                )
            except IntegrityError:
                spent = saved_movement(data['token'])  # the same form, saved by a simultaneous request
                if spent is None:
                    raise
                messages.info(request, T['pl_already_saved'])
                return to_company(spent.company, '#entries')
            except peeling.NoPrice as missing:
                messages.error(request, T['pl_err_no_price'].format(company=company.name, date=missing.day.isoformat()))
            except peeling.PeelLocked as locked:
                messages.error(request, locked_message(T, locked))
            except peeling.TooManyBack as short:
                available = data['fish'] - short.short
                messages.error(request, T['pl_err_too_many'].format(company=company.name, available=fish_text(available)))
            else:
                if movement.kind == PeelKind.BACK:
                    messages.success(request, T['pl_saved_back'].format(
                        company=company.name, fish=fish_text(movement.fish),
                        price=won(movement.unit_price), amount=won(movement.amount)))
                else:
                    messages.success(request, T['pl_saved'].format(
                        company=company.name, kind=kind_label(T, movement.kind), fish=fish_text(movement.fish)))
                return to_company(company, '#entries')
        else:
            messages.error(request, T['err_form'])
        # Shown again: a fresh token, so fixing the mistake and saving isn't taken for a repeat.
        data = request.POST.copy()
        data['token'] = str(uuid.uuid4())
        form = PeelEntryForm(data, T=T)
        form.is_valid()
    else:
        initial = {'token': uuid.uuid4()}
        company = PeelCompany.objects.filter(pk=request.GET.get('company'), is_active=True).first() \
            if (request.GET.get('company') or '').isdigit() else None
        if company:
            initial['company'] = company
        if request.GET.get('kind') in PeelKind.values:
            initial['kind'] = request.GET['kind']
        form = PeelEntryForm(initial=initial, T=T)
    return render_page(request, 'peeling/entry.html', **entry_context(T, form))


@manager_required
def peel_entry_edit(request, pk):
    T = strings(request)
    movement = get_object_or_404(PeelMovement.objects.select_related('company'), pk=pk)
    company = movement.company
    heading = T['pl_edit_entry'].format(company=company.name, date=movement.date.isoformat())
    paid = peeling.paid_month(company, movement.date)
    if request.method == 'POST':
        form = PeelEditForm(request.POST, T=T)
        if form.is_valid():
            data = form.cleaned_data
            try:
                with transaction.atomic():
                    peeling.update(movement, day=data['date'], fish=data['fish'], note=data['note'],
                                   user=request.user, reason=data['reason'])
            except peeling.NoPrice as missing:
                messages.error(request, T['pl_err_no_price'].format(company=company.name, date=missing.day.isoformat()))
            except peeling.PeelLocked as locked:
                messages.error(request, locked_message(T, locked))
            except peeling.TooManyBack as short:
                messages.error(request, T['pl_err_balance'].format(company=company.name, short=fish_text(short.short)))
            else:
                messages.success(request, T['pl_entry_saved'])
                return to_company(company, '#entries')
            movement.refresh_from_db()
        else:
            messages.error(request, T['err_form'])
    else:
        form = PeelEditForm(initial={'date': movement.date, 'fish': movement.fish, 'note': movement.note}, T=T)
    return render_page(
        request, 'peeling/entry_edit.html',
        heading=heading, movement=movement, company=company, form=form, paid=paid,
        kind=kind_label(T, movement.kind),
        confirm_delete=T['pl_confirm_delete_entry'].format(kind=kind_label(T, movement.kind), fish=fish_text(movement.fish)),
    )


@manager_required
@require_POST
def peel_entry_delete(request, pk):
    T = strings(request)
    movement = get_object_or_404(PeelMovement.objects.select_related('company'), pk=pk)
    company = movement.company
    try:
        peeling.delete(movement, user=request.user)
    except peeling.PeelLocked as locked:
        messages.error(request, locked_message(T, locked))
    except peeling.TooManyBack as short:
        messages.error(request, T['pl_err_balance'].format(company=company.name, short=fish_text(short.short)))
    else:
        messages.success(request, T['pl_entry_deleted'])
    return to_company(company, '#entries')


# ─── Companies ────────────────────────────────────────────────

@manager_required
def peel_company_new(request):
    T = strings(request)
    if request.method == 'POST':
        form = PeelCompanyForm(request.POST, T=T)
        if form.is_valid():
            with transaction.atomic():
                company = form.save()
                peeling.set_price(company, day=form.cleaned_data['price_from'],
                                  price_per_fish=form.cleaned_data['price_per_fish'], user=request.user)
            messages.success(request, T['pl_company_added'].format(name=company.name))
            return to_company(company)
        messages.error(request, T['err_form'])
    else:
        form = PeelCompanyForm(T=T)
    return render_page(request, 'peeling/company_form.html', form=form, heading=T['pl_add_company'], company=None)


@manager_required
def peel_company_edit(request, pk):
    T = strings(request)
    company = get_object_or_404(PeelCompany, pk=pk)
    heading = T['pl_edit_company_title'].format(name=company.name)  # before the form touches the name
    if request.method == 'POST':
        form = PeelCompanyForm(request.POST, instance=company, T=T)
        if form.is_valid():
            form.save()
            messages.success(request, T['pl_company_saved'].format(name=company.name))
            return to_company(company)
        messages.error(request, T['err_form'])
    else:
        form = PeelCompanyForm(instance=company, T=T)
    return render_page(
        request, 'peeling/company_form.html', form=form, heading=heading, company=company,
        can_delete=not company.movements.exists(),
        confirm_delete=T['pl_confirm_delete_company'].format(name=company.name),
    )


@manager_required
@require_POST
def peel_company_delete(request, pk):
    T = strings(request)
    company = get_object_or_404(PeelCompany, pk=pk)
    name = company.name
    try:
        company.delete()
    except ProtectedError:
        messages.error(request, T['pl_company_in_use'].format(name=name))
        return to_company(company)
    messages.success(request, T['pl_company_deleted'].format(name=name))
    return redirect('cutting:peel_home')


def entry_rows(T, company):
    """Every entry, newest first, with what the company held after it."""
    movements = list(company.movements.order_by('date', 'created_at', 'pk'))
    held = 0
    rows = []
    for movement in movements:
        held += movement.fish if movement.kind == PeelKind.OUT else -movement.fish
        rows.append({
            'movement': movement, 'kind': kind_label(T, movement.kind), 'held_after': held,
            'confirm_delete': T['pl_confirm_delete_entry'].format(kind=kind_label(T, movement.kind),
                                                                  fish=fish_text(movement.fish)),
        })
    rows.reverse()
    return rows


def render_company(request, company, *, price_form=None):
    T = strings(request)
    today = timezone.localdate()
    company = PeelCompany.objects.prefetch_related('prices').get(pk=company.pk)
    totals = peeling.company_counts(company)
    current = company.price_on(today)
    prices = [{
        'price': price, 'is_current': price == current, 'is_upcoming': price.effective_from > today,
        'confirm_delete': T['pl_confirm_delete_price'].format(date=price.effective_from.isoformat()),
    } for price in sorted(company.prices.all(), key=lambda price: price.effective_from, reverse=True)]
    statements = []
    for figures in peeling.months_with_entries(company):
        statements.append({**figures, 'label': month_label(figures['first'])})
    page = Paginator(entry_rows(T, company), ENTRIES_PAGE_SIZE).get_page(request.GET.get('page'))
    return render_page(
        request, 'peeling/company.html',
        company=company, totals=totals, check=check_text(T, totals),
        tax=tax_label(T, company.tax_mode),
        price_now=T['pl_per_fish'].format(price=won(current.price_per_fish)) if current else T['pl_no_price'],
        prices=prices, price_form=price_form or PeelPriceForm(T=T),
        statements=statements, page=page,
        page_label=T['page_of'].format(page=page.number, pages=page.paginator.num_pages),
        heading=T['pl_company_title'].format(name=company.name),
    )


@manager_required
def peel_company(request, pk):
    return render_company(request, get_object_or_404(PeelCompany, pk=pk))


@manager_required
@require_POST
def peel_price_add(request, pk):
    T = strings(request)
    company = get_object_or_404(PeelCompany, pk=pk)
    form = PeelPriceForm(request.POST, T=T)
    if not form.is_valid():
        messages.error(request, T['err_form'])
        return render_company(request, company, price_form=form)
    price = peeling.set_price(company, day=form.cleaned_data['effective_from'],
                              price_per_fish=form.cleaned_data['price_per_fish'], user=request.user)
    messages.success(request, T['pl_price_saved'].format(date=price.effective_from.isoformat(),
                                                         price=won(price.price_per_fish)))
    return to_company(company, '#prices')


@manager_required
@require_POST
def peel_price_delete(request, pk):
    T = strings(request)
    price = get_object_or_404(PeelPrice.objects.select_related('company'), pk=pk)
    started = price.effective_from.isoformat()
    peeling.delete_price(price, user=request.user)
    messages.success(request, T['pl_price_deleted'].format(date=started))
    return to_company(price.company, '#prices')


# ─── Statements ───────────────────────────────────────────────

@manager_required
def peel_statement(request, pk, month):
    """A company's month, printable: batches brought back, tax, total to pay, and the count check."""
    lang = get_lang(request)
    T = STRINGS[lang]
    company = get_object_or_404(PeelCompany, pk=pk)
    figures = peeling.statement(company, month)
    paid = figures['paid']
    label = month_label(month)
    counts_in_month = {key: fish_text(value) for key, value in figures['month_counts'].items()}
    return render(request, 'cutting/peeling/statement.html', {
        'T': T, 'lang': lang, 'company': company, 'month': month, 'month_label': label, **figures,
        'title': T['pl_statement_title'].format(company=company.name, month=label),
        'tax_name': tax_label(T, figures['tax_mode']),
        'tax_line': tax_line_label(T, figures['tax_mode']),
        'month_moves': T['pl_month_moves'].format(out=counts_in_month['out'], back=counts_in_month['back'],
                                                  lost=counts_in_month['lost']),
        'end_check': check_text(T, figures['end_counts']),
        'end_with_them': T['pl_end_with_them'].format(company=company.name, date=figures['last'].isoformat(),
                                                      count=fish_text(figures['end_counts']['with_them'])),
        'other_entries': [{'movement': m, 'kind': kind_label(T, m.kind)} for m in figures['other_entries']],
        'paid_banner': T['pl_paid_banner'].format(
            name=paid.paid_by_name or '—', when=timezone.localtime(paid.paid_at).strftime('%Y-%m-%d %H:%M'),
        ) if paid else '',
        'can_mark_paid': not paid and peeling.can_mark_paid(month),
        'paid_not_yet': T['pl_paid_not_yet'].format(date=figures['last'].isoformat()),
        'confirm_paid': T['pl_confirm_paid'].format(company=company.name, month=label),
        'reopen_form': UnlockForm(T=T) if paid else None,
        'back_url': reverse('cutting:peel_company', args=[company.pk]),
        'generated': timezone.localtime(),
    })


@manager_required
def peel_summary(request, month=None):
    """Every peeling company's month on one printable page: counts, pay, tax and the totals."""
    if month is None:
        return redirect('cutting:peel_summary', this_month())
    lang = get_lang(request)
    T = STRINGS[lang]
    summary = peeling.month_summary(month)
    label = month_label(month)
    today = timezone.localdate()
    return render(request, 'cutting/peeling/summary.html', {
        'T': T, 'lang': lang, 'month': month, 'month_label': label, **summary,
        'title': T['pl_summary_title'].format(month=label),
        'provisional': T['provisional_note'].format(date=today.isoformat()) if today <= summary['last'] else '',
        'previous_month': (month - timedelta(days=1)).replace(day=1),
        'next_month': next_month(month) if month < this_month() else None,
        'back_url': reverse('cutting:peel_home'),
        'generated': timezone.localtime(),
    })


def to_statement(company, month):
    return redirect('cutting:peel_statement', company.pk, month)


@manager_required
@require_POST
def peel_mark_paid(request, pk, month):
    T = strings(request)
    company = get_object_or_404(PeelCompany, pk=pk)
    try:
        peeling.mark_paid(company, month, user=request.user)
    except peeling.MonthNotOver as early:
        messages.error(request, T['pl_err_paid_early'].format(month=month_label(month), date=early.last_day.isoformat()))
    else:
        messages.success(request, T['pl_paid_done'].format(company=company.name, month=month_label(month)))
    return to_statement(company, month)


@manager_required
@require_POST
def peel_reopen(request, pk, month):
    T = strings(request)
    company = get_object_or_404(PeelCompany, pk=pk)
    form = UnlockForm(request.POST, T=T)
    if not form.is_valid():
        messages.error(request, form.errors['reason'][0])
    elif peeling.reopen(company, month, user=request.user, reason=form.cleaned_data['reason']):
        messages.success(request, T['pl_reopened'].format(company=company.name, month=month_label(month)))
    return to_statement(company, month)
