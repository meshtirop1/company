"""Forms for skin peeling by outside companies (see cutting/peeling.py)."""
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .forms import DATE_WIDGET, REASON_MAX, WonField, localize
from .models import PeelCompany, PeelKind, TaxMode
from .peeling import company_counts

FISH_MAX = 999999


class FishField(WonField):
    """A number of fish. Like WonField it accepts '3,000' and full-width digits."""

    def __init__(self, **kwargs):
        kwargs.setdefault('max_digits', 6)
        kwargs.setdefault('max_value', FISH_MAX)
        super().__init__(**kwargs)

    def clean(self, value):
        number = super().clean(value)
        return int(number) if number is not None else None


def tax_choices(T):
    return [(TaxMode.NONE, T['pl_tax_none']), (TaxMode.VAT, T['pl_tax_vat']), (TaxMode.WITHHOLD, T['pl_tax_withhold'])]


def not_in_future(day, T):
    if day > timezone.localdate():
        raise ValidationError(T['pl_err_future'])
    return day


class PeelCompanyForm(forms.ModelForm):
    """A company's details. Adding one also takes its first price."""
    price_per_fish = WonField(required=False)
    price_from = forms.DateField(required=False, widget=DATE_WIDGET)

    class Meta:
        model = PeelCompany
        fields = ['name', 'note', 'tax_mode', 'is_active']

    def __init__(self, *args, T, **kwargs):
        super().__init__(*args, **kwargs)
        self.T = T
        self.adding = self.instance.pk is None
        localize(self, T)
        self.fields['name'].label = T['name']
        self.fields['name'].widget.attrs['autocomplete'] = 'off'
        self.fields['note'].label = T['note']
        self.fields['note'].help_text = T['pl_company_note_help']
        self.fields['tax_mode'].label = T['pl_tax']
        self.fields['tax_mode'].help_text = T['pl_tax_help']
        self.fields['tax_mode'].choices = tax_choices(T)
        self.fields['is_active'].label = T['pl_active']
        if self.adding:
            del self.fields['is_active']
            self.fields['price_per_fish'].required = True
            self.fields['price_per_fish'].label = T['pl_price']
            self.fields['price_per_fish'].error_messages['min_value'] = T['err_price_min']
            self.fields['price_from'].required = True
            self.fields['price_from'].label = T['pl_price_from']
            self.fields['price_from'].initial = timezone.localdate()
        else:
            del self.fields['price_per_fish']
            del self.fields['price_from']

    def clean_name(self):
        name = ' '.join(self.cleaned_data['name'].split())
        if PeelCompany.objects.filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise ValidationError(self.T['pl_err_duplicate'])
        return name

    def clean_is_active(self):
        active = self.cleaned_data['is_active']
        if not active and self.instance.is_active:
            still = company_counts(self.instance)['with_them']
            if still > 0:
                raise ValidationError(self.T['pl_err_still_has'].format(name=self.instance.name, count=f'{still:,}'))
        return active


class PeelPriceForm(forms.Form):
    price_per_fish = WonField()
    effective_from = forms.DateField(widget=DATE_WIDGET)

    def __init__(self, *args, T, **kwargs):
        super().__init__(*args, **kwargs)
        localize(self, T)
        self.fields['price_per_fish'].label = T['pl_price']
        self.fields['price_per_fish'].error_messages['min_value'] = T['err_price_min']
        self.fields['effective_from'].label = T['pl_price_from']
        self.fields['effective_from'].initial = timezone.localdate()


class PeelEntryForm(forms.Form):
    """One handover. `token` is minted when the form is shown, so a double tap saves it once."""
    company = forms.ModelChoiceField(queryset=PeelCompany.objects.none())
    kind = forms.ChoiceField(widget=forms.RadioSelect)
    date = forms.DateField(widget=DATE_WIDGET)
    fish = FishField()
    note = forms.CharField(max_length=200, required=False)
    token = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, T, **kwargs):
        super().__init__(*args, **kwargs)
        self.T = T
        self.fields['company'].queryset = PeelCompany.objects.filter(is_active=True)
        self.fields['company'].label = T['pl_company']
        self.fields['company'].empty_label = T['pl_choose_company']
        self.fields['kind'].label = T['pl_kind']
        self.fields['kind'].choices = [
            (PeelKind.OUT, T['pl_kind_out']), (PeelKind.BACK, T['pl_kind_back']), (PeelKind.LOST, T['pl_kind_lost']),
        ]
        self.fields['date'].label = T['pl_date']
        self.fields['date'].initial = timezone.localdate()
        self.fields['fish'].label = T['pl_fish']
        self.fields['note'].label = T['note']
        self.fields['note'].help_text = T['pl_note_help']
        localize(self, T)
        self.fields['fish'].error_messages.update(min_value=T['pl_err_fish'], max_value=T['pl_err_fish'],
                                                  invalid=T['pl_err_fish'], max_digits=T['pl_err_fish'])
        self.fields['company'].error_messages['invalid_choice'] = T['err_choice']
        self.fields['token'].error_messages['invalid'] = T['err_form_expired']

    def clean_date(self):
        return not_in_future(self.cleaned_data['date'], self.T)

    def clean_note(self):
        return ' '.join(self.cleaned_data['note'].split())


class PeelEditForm(forms.Form):
    """Correct an entry's date, number of fish or note; the reason goes into the change log."""
    date = forms.DateField(widget=DATE_WIDGET)
    fish = FishField()
    note = forms.CharField(max_length=200, required=False)
    reason = forms.CharField(max_length=REASON_MAX, required=False)

    def __init__(self, *args, T, **kwargs):
        super().__init__(*args, **kwargs)
        self.T = T
        self.fields['date'].label = T['pl_date']
        self.fields['fish'].label = T['pl_fish']
        self.fields['note'].label = T['note']
        self.fields['reason'].label = T['reason_optional']
        self.fields['reason'].help_text = T['reason_help']
        localize(self, T)
        self.fields['fish'].error_messages.update(min_value=T['pl_err_fish'], max_value=T['pl_err_fish'],
                                                  invalid=T['pl_err_fish'], max_digits=T['pl_err_fish'])

    def clean_date(self):
        return not_in_future(self.cleaned_data['date'], self.T)

    def clean_note(self):
        return ' '.join(self.cleaned_data['note'].split())

    def clean_reason(self):
        return ' '.join(self.cleaned_data['reason'].split())
