import unicodedata

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import Cutter, CuttingStyle, PriceItem, PriceRate

DATE_WIDGET = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
SORT_ORDER_MAX = 32767  # PositiveSmallIntegerField's ceiling on every database


class WonField(forms.DecimalField):
    """A whole-won amount. Also accepts '4,500' or '₩4500' as typed on a desktop keyboard."""

    def __init__(self, **kwargs):
        kwargs.setdefault('max_digits', 10)
        kwargs.setdefault('decimal_places', 0)
        kwargs.setdefault('min_value', 1)
        kwargs.setdefault('widget', forms.TextInput(attrs={'inputmode': 'numeric', 'autocomplete': 'off'}))
        super().__init__(**kwargs)

    def to_python(self, value):
        if isinstance(value, str):
            value = value.replace(',', '').replace('₩', '').strip()
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
        field.widget.attrs['class'] = f"{field.widget.attrs.get('class', '')} input-field".strip()


def localize_price(field, T):
    field.label = T['unit_price']
    field.error_messages['min_value'] = T['err_price_min']


def localize_sort_order(field, T):
    field.label = T['sort_order']
    field.help_text = T['sort_order_help']
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

    class Meta:
        model = PriceItem
        fields = ['size', 'sort_order']

    def __init__(self, *args, T, **kwargs):
        super().__init__(*args, **kwargs)
        self.T = T
        self.fields['size'].label = T['size']
        self.fields['size'].help_text = T['size_help']
        localize(self, T)
        localize_sort_order(self.fields['sort_order'], T)

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
