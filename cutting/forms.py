import re
import unicodedata

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import AuditEntry, Cutter, CuttingStyle, PriceItem, PriceRate
from .services import lock_for

DATE_WIDGET = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
SORT_ORDER_MAX = 32767  # PositiveSmallIntegerField's ceiling on every database
BOXES_MAX = 9999
REASON_MAX = AuditEntry._meta.get_field('reason').max_length


class WonField(forms.DecimalField):
    """A whole-won amount. Also accepts '4,500', '₩4500', '4500원' and full-width digits.

    On a Korean PC keyboard the ₩ key types a backslash (U+005C, drawn as ₩ in Korean
    fonts), so that is stripped too.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault('max_digits', 10)
        kwargs.setdefault('decimal_places', 0)
        kwargs.setdefault('min_value', 1)
        kwargs.setdefault('widget', forms.TextInput(attrs={'inputmode': 'numeric', 'autocomplete': 'off'}))
        super().__init__(**kwargs)

    def to_python(self, value):
        if isinstance(value, str):
            value = unicodedata.normalize('NFKC', value)  # full-width ￦, digits and commas → plain
            for mark in (',', '₩', '\\', '원'):
                value = value.replace(mark, '')
            value = value.strip()
        return super().to_python(value)


def normalize_size(value):
    """'10 ～ 11' (full-width, as a Korean keyboard may type it) → '10~11'; '4, 5, 6' → '4,5,6'."""
    return ''.join(unicodedata.normalize('NFKC', value).split())


def style_choices(T):
    return [(value, f'{label} — {T[f"style_{value}_desc"]}') for value, label in CuttingStyle.choices]


def localize(form, T):
    """Give every field the page language's error messages and the design-system input class.

    Django's built-in messages would otherwise appear in English on Korean pages, because
    this app picks its language from the session rather than Django's own locale.
    """
    number_codes = ('invalid', 'max_digits', 'max_decimal_places', 'max_whole_digits')
    for field in form.fields.values():
        messages = {
            'required': T['err_required'],
            'invalid_choice': T['err_choice'],
            'max_length': T['err_max_length'],
        }
        if isinstance(field, forms.DateField):
            messages['invalid'] = T['err_date']
        elif isinstance(field, forms.IntegerField):  # DecimalField subclasses IntegerField
            messages.update(dict.fromkeys(number_codes, T['err_number']))
        field.error_messages.update(messages)
        if not isinstance(field.widget, (forms.CheckboxInput, forms.RadioSelect)):  # .input-field is text-box styling
            field.widget.attrs['class'] = f"{field.widget.attrs.get('class', '')} input-field".strip()


def localize_price(field, T):
    field.label = T['unit_price']
    field.error_messages['min_value'] = T['err_price_min']


def localize_sort_order(field, T, help_key='sort_order_help'):
    field.label = T['sort_order']
    field.help_text = T[help_key]
    field.error_messages.update(min_value=T['err_order_range'], max_value=T['err_order_range'])


class CutterForm(forms.ModelForm):
    class Meta:
        model = Cutter
        fields = ['name', 'note']

    def __init__(self, *args, T, **kwargs):
        super().__init__(*args, **kwargs)
        self.T = T
        localize(self, T)
        self.fields['name'].label = T['name']
        self.fields['name'].widget.attrs['autocomplete'] = 'off'
        self.fields['note'].label = T['note']
        self.fields['note'].help_text = T['note_help']

    def clean_name(self):
        name = ' '.join(self.cleaned_data['name'].split())
        if Cutter.objects.filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise ValidationError(self.T['err_duplicate_name'])
        return name


class PriceItemCreateForm(forms.Form):
    """A new price-list line plus its first rate, saved together."""
    style = forms.ChoiceField()
    size = forms.CharField(max_length=20)
    sort_order = forms.IntegerField(min_value=0, max_value=SORT_ORDER_MAX, required=False)
    unit_price = WonField()
    effective_from = forms.DateField(widget=DATE_WIDGET)

    def __init__(self, *args, T, **kwargs):
        super().__init__(*args, **kwargs)
        self.T = T
        self.fields['style'].choices = style_choices(T)
        self.fields['style'].label = T['style']
        self.fields['size'].label = T['size']
        self.fields['size'].help_text = T['size_help']
        self.fields['effective_from'].label = T['effective_from']
        self.fields['effective_from'].initial = timezone.localdate()
        localize(self, T)
        localize_price(self.fields['unit_price'], T)
        localize_sort_order(self.fields['sort_order'], T)

    def clean_size(self):
        size = normalize_size(self.cleaned_data['size'])
        if not size:
            raise ValidationError(self.T['err_required'])
        return size

    def clean(self):
        cleaned = super().clean()
        style, size = cleaned.get('style'), cleaned.get('size')
        if style and size and PriceItem.objects.filter(style=style, size=size).exists():
            item = f'{CuttingStyle(style).label} {size}'
            self.add_error('size', self.T['err_duplicate_item'].format(item=item))
        return cleaned

    def save(self, user):
        data = self.cleaned_data
        sort_order = data['sort_order']
        if sort_order is None:
            last = PriceItem.objects.filter(style=data['style']).aggregate(last=Max('sort_order'))['last']
            sort_order = min((last or 0) + 10, SORT_ORDER_MAX)
        with transaction.atomic():
            item = PriceItem.objects.create(style=data['style'], size=data['size'], sort_order=sort_order)
            PriceRate.objects.create(
                item=item, unit_price=data['unit_price'], effective_from=data['effective_from'], created_by=user,
            )
        return item


class PriceItemEditForm(forms.ModelForm):
    """Rename a size or move it in the list. The style is fixed once the line exists."""
    sort_order = forms.IntegerField(min_value=0, max_value=SORT_ORDER_MAX)  # same range as when adding

    class Meta:
        model = PriceItem
        fields = ['size', 'sort_order']

    def __init__(self, *args, T, **kwargs):
        super().__init__(*args, **kwargs)
        self.T = T
        self.fields['size'].label = T['size']
        self.fields['size'].help_text = T['size_help']
        localize(self, T)
        localize_sort_order(self.fields['sort_order'], T, help_key='sort_order_help_edit')  # blank isn't allowed here

    def clean_size(self):
        size = normalize_size(self.cleaned_data['size'])
        if not size:
            raise ValidationError(self.T['err_required'])
        clash = PriceItem.objects.filter(style=self.instance.style, size=size).exclude(pk=self.instance.pk)
        if clash.exists():
            item = f'{self.instance.get_style_display()} {size}'
            raise ValidationError(self.T['err_duplicate_item'].format(item=item))
        return size


class PriceRateForm(forms.ModelForm):
    unit_price = WonField()

    class Meta:
        model = PriceRate
        fields = ['unit_price', 'effective_from']
        widgets = {'effective_from': DATE_WIDGET}

    def __init__(self, *args, item, T, **kwargs):
        super().__init__(*args, **kwargs)
        self.item = item
        self.T = T
        self.fields['effective_from'].label = T['effective_from']
        if self.instance.pk is None:
            self.fields['effective_from'].initial = timezone.localdate()
        localize(self, T)
        localize_price(self.fields['unit_price'], T)

    def clean_effective_from(self):
        day = self.cleaned_data['effective_from']
        clash = PriceRate.objects.filter(item=self.item, effective_from=day).exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError(self.T['err_duplicate_rate_date'])
        return day

    def save(self, user):
        rate = super().save(commit=False)
        rate.item = self.item
        if rate.pk is None:
            rate.created_by = user
        rate.save()
        return rate


# ─── Work entry ───────────────────────────────────────────────

def ordered_items(items):
    """Price-list lines in sheet order: 통포 first, then 통할복, each by display order."""
    style_rank = {value: rank for rank, value in enumerate(CuttingStyle.values)}
    return sorted(items, key=lambda item: (style_rank.get(item.style, len(style_rank)), item.sort_order, item.pk))


def grouped_item_choices(items, *, with_style):
    """Choices grouped by style, e.g. [('통포', [('3', '7'), ...]), ('통할복', [...])]."""
    groups = []
    for value, label in CuttingStyle.choices:
        members = [(str(item.pk), f'{label} {item.size}' if with_style else item.size)
                   for item in items if item.style == value]
        if members:
            groups.append((label, members))
    return groups


class ItemSelect(forms.Select):
    """A size picker whose options carry their style, so the page can show one style at a time."""

    def __init__(self, *args, item_styles=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.item_styles = item_styles or {}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if style := self.item_styles.get(str(value)):
            option['attrs']['data-style'] = style
        return option


def localize_boxes(field, T):
    field.label = T['boxes']
    field.error_messages.update(dict.fromkeys(('invalid', 'min_value', 'max_value'), T['err_boxes_range']))


class BatchEntryForm(forms.Form):
    """The entry screen: a work date, a default style and size, and a row per active cutter.

    A row counts when its box is ticked. Its size is the batch default unless the row
    picks its own. `self.rows` holds (cutter, item, boxes) for every valid ticked row.
    """
    token = forms.UUIDField(widget=forms.HiddenInput)
    work_date = forms.DateField(widget=DATE_WIDGET)
    style = forms.ChoiceField(choices=CuttingStyle.choices, widget=forms.RadioSelect)

    def __init__(self, *args, T, cutters, items, **kwargs):
        super().__init__(*args, **kwargs)
        self.T = T
        self.cutters = list(cutters)
        self.items = {str(item.pk): item for item in items}
        item_styles = {pk: item.style for pk, item in self.items.items()}
        self.rows = []

        self.fields['work_date'].label = T['work_date']
        self.fields['style'].label = T['style']
        self.fields['item'] = forms.ChoiceField(
            label=T['size'], choices=grouped_item_choices(items, with_style=False),
            widget=ItemSelect(item_styles=item_styles),
        )
        override_choices = [('', T['same_as_batch'])] + grouped_item_choices(items, with_style=True)
        for cutter in self.cutters:
            self.fields[f'include_{cutter.pk}'] = forms.BooleanField(
                required=False, label=cutter.name, widget=forms.CheckboxInput(attrs={'class': 'cut-include'}),
            )
            self.fields[f'boxes_{cutter.pk}'] = forms.IntegerField(
                required=False, min_value=1, max_value=BOXES_MAX,
                widget=forms.TextInput(attrs={
                    'class': 'cut-boxes', 'inputmode': 'numeric', 'pattern': '[0-9]*', 'autocomplete': 'off',
                    'aria-label': f"{cutter.name} — {T['boxes']}",
                }),
            )
            self.fields[f'item_{cutter.pk}'] = forms.ChoiceField(
                required=False, label=T['change_row'], choices=override_choices,
                widget=ItemSelect(item_styles=item_styles, attrs={'class': 'cut-override'}),
            )
        localize(self, T)
        for cutter in self.cutters:
            localize_boxes(self.fields[f'boxes_{cutter.pk}'], T)

    def entry_rows(self):
        """One row per active cutter, for the template."""
        for cutter in self.cutters:
            override = self[f'item_{cutter.pk}']
            yield {
                'cutter': cutter,
                'include': self[f'include_{cutter.pk}'],
                'boxes': self[f'boxes_{cutter.pk}'],
                'item': override,
                'overridden': bool(override.value()),
            }

    def clean_work_date(self):
        day = self.cleaned_data['work_date']
        if day > timezone.localdate():
            raise ValidationError(self.T['err_future_date'])
        if lock_for(day):
            raise ValidationError(self.T['err_month_locked'].format(month=f'{day:%Y-%m}'))
        return day

    def clean(self):
        cleaned = super().clean()
        T = self.T
        for cutter in self.cutters:
            if not cleaned.get(f'include_{cutter.pk}'):  # an unticked row is ignored, typos and all
                self._errors.pop(f'boxes_{cutter.pk}', None)
                self._errors.pop(f'item_{cutter.pk}', None)
        day = cleaned.get('work_date')
        style = cleaned.get('style')
        default_item = self.items.get(cleaned.get('item') or '')
        if default_item and style and default_item.style != style:
            self.add_error('item', T['err_style_mismatch'])
            default_item = None

        for cutter in self.cutters:
            if not cleaned.get(f'include_{cutter.pk}'):
                continue
            boxes_field, item_field = f'boxes_{cutter.pk}', f'item_{cutter.pk}'
            boxes = cleaned.get(boxes_field)
            if boxes is None:
                if boxes_field not in self.errors:
                    self.add_error(boxes_field, T['err_boxes_required'])
                continue
            own_item = self.items.get(cleaned.get(item_field) or '')
            item = own_item or default_item
            if item is None:
                continue  # the size field already explains why
            if day and item.rate_on(day) is None:
                field = item_field if own_item else 'item'
                message = T['err_no_rate'].format(item=item, date=day.isoformat())
                if message not in self.errors.get(field, []):
                    self.add_error(field, message)
                continue
            self.rows.append((cutter, item, boxes))

        names, removed = self._ticked_unlisted_cutters()
        for name in names:
            self.add_error(None, T['err_cutter_inactive'].format(name=name))
        if removed:
            self.add_error(None, T['err_cutter_gone'])
        if not self.rows and not self.errors:
            raise ValidationError(T['err_no_rows'])
        return cleaned

    def _ticked_unlisted_cutters(self):
        """Ticked rows whose cutter was deactivated or deleted after the form was opened.

        Returns the names of those still on file, and how many were deleted outright.
        Either way the batch must not save without them, or their boxes would vanish.
        """
        listed = {cutter.pk for cutter in self.cutters}
        ticked = set()
        for key, value in self.data.items():
            match = re.fullmatch(r'include_(\d+)', key)
            if match and value and int(match.group(1)) not in listed:
                ticked.add(int(match.group(1)))
        names = dict(Cutter.objects.filter(pk__in=ticked).values_list('pk', 'name'))
        return list(names.values()), len(ticked - names.keys())


class RecordEditForm(forms.Form):
    """Correct one saved row: its boxes, or the size and style it was cut at."""
    boxes = forms.IntegerField(min_value=1, max_value=BOXES_MAX)
    reason = forms.CharField(max_length=REASON_MAX, required=False)

    def __init__(self, *args, T, record, items, **kwargs):
        kwargs.setdefault('initial', {'item': str(record.item_id), 'boxes': record.boxes})
        super().__init__(*args, **kwargs)
        self.T = T
        self.record = record
        self.items = {str(item.pk): item for item in items}
        self.items.setdefault(str(record.item_id), record.item)  # still editable if since hidden
        self.fields['item'] = forms.ChoiceField(
            label=T['item_col'], choices=grouped_item_choices(ordered_items(self.items.values()), with_style=True),
        )
        self.fields['boxes'].widget = forms.TextInput(attrs={'inputmode': 'numeric', 'pattern': '[0-9]*'})
        self.fields['reason'].label = T['reason_optional']
        self.fields['reason'].help_text = T['reason_help']
        self.fields['reason'].widget.attrs['autocomplete'] = 'off'
        self.order_fields(['item', 'boxes', 'reason'])
        localize(self, T)
        localize_boxes(self.fields['boxes'], T)

    def clean(self):
        cleaned = super().clean()
        item = self.items.get(cleaned.get('item') or '')
        if item and item.pk != self.record.item_id and item.rate_on(self.record.work_date) is None:
            self.add_error('item', self.T['err_no_rate'].format(
                item=item, date=self.record.work_date.isoformat(),
            ))
        cleaned['item'] = item
        return cleaned


class UnlockForm(forms.Form):
    """Reopening a paid month needs a reason; it goes into the change log."""
    reason = forms.CharField(max_length=REASON_MAX)

    def __init__(self, *args, T, **kwargs):
        super().__init__(*args, **kwargs)
        self.T = T
        self.fields['reason'].label = T['unlock_reason']
        self.fields['reason'].help_text = T['unlock_help']
        self.fields['reason'].widget.attrs['autocomplete'] = 'off'
        localize(self, T)
        self.fields['reason'].error_messages['required'] = T['err_unlock_reason']

    def clean_reason(self):
        reason = ' '.join(self.cleaned_data['reason'].split())
        if not reason:
            raise ValidationError(self.T['err_unlock_reason'])
        return reason
