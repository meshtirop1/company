"""Supervisor pages for the fish-cutting pay module.

Only managers (is_admin) and superusers may use them; anyone else gets the 403 page.
Every page renders one shared template with the session language's strings (see i18n.py).
"""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import CutterForm, PriceItemCreateForm, PriceItemEditForm, PriceRateForm
from .i18n import STRINGS, get_lang
from .models import Cutter, CuttingStyle, PriceItem, PriceRate


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
    return render_page(
        request, 'hub.html',
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
