"""Tax and health insurance taken off a payslip — shared by the employees' payslips and the
fish-cutting payslips.

Each person has dated rates (hours_tracker.EmployeeDeduction, cutting.CutterDeduction). A
payslip uses the rate in force for its own month — the latest one starting on or before it —
so changing a rate from next month never alters a payslip already paid. Both amounts are
taken from gross pay and rounded down to whole tens of won, as Korean payroll does.
"""
import re
import unicodedata
from datetime import date
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import InsuranceMode

ZERO = Decimal(0)
PERCENT_PLACES = 3
AMOUNT_MAX = Decimal('9999999999')  # ten digits of whole won


# ─── Arithmetic ───────────────────────────────────────────────

def floor_10(amount):
    """Round down to whole tens of won (10원 미만 절사)."""
    return (Decimal(amount) / 10).to_integral_value(rounding=ROUND_DOWN) * 10


def rate_for(rates, first_day):
    """The rate in force for the month starting `first_day`, or None.

    Filters in Python so a prefetched set of rates is reused instead of re-queried.
    """
    eligible = [rate for rate in rates if rate.effective_from <= first_day]
    return max(eligible, key=lambda rate: rate.effective_from, default=None)


def has_deductions(rate):
    return rate is not None and (rate.tax_percent > 0 or rate.insurance_mode != InsuranceMode.NONE)


def compute(gross, rate):
    """One month's deductions from its gross pay under `rate` (None means none).

    A month with no pay has nothing to take off, so it deducts nothing — not even a fixed
    insurance amount.
    """
    gross = Decimal(gross or 0)
    tax = insurance = ZERO
    if rate is not None and gross > 0:
        tax = floor_10(gross * rate.tax_percent / 100)
        if rate.insurance_mode == InsuranceMode.PERCENT:
            insurance = floor_10(gross * rate.insurance_value / 100)
        elif rate.insurance_mode == InsuranceMode.AMOUNT:
            insurance = rate.insurance_value.to_integral_value()
    total = tax + insurance
    return {
        'rate': rate, 'shown': has_deductions(rate),
        'gross': gross, 'tax': tax, 'insurance': insurance, 'total': total, 'net': gross - total,
    }


# ─── Text ─────────────────────────────────────────────────────

def percent_text(value):
    """3.300 → '3.3', 10.000 → '10'."""
    return format(Decimal(value).normalize(), 'f')


def won_text(amount):
    return f'₩{int(amount):,}'


def insurance_text(rate):
    if rate.insurance_mode == InsuranceMode.PERCENT:
        return f'{percent_text(rate.insurance_value)}%'
    if rate.insurance_mode == InsuranceMode.AMOUNT:
        return won_text(rate.insurance_value)
    return '—'


def rate_summary(D, rate):
    """'From 2026-10: tax 3.3%, health insurance ₩150,000' — for the change log."""
    return D['rate_summary'].format(
        month=rate.effective_from.strftime('%Y-%m'), tax=percent_text(rate.tax_percent), insurance=insurance_text(rate),
    )


def lines(D, result):
    """The payslip lines (label, amount) for a compute() result."""
    rate = result['rate']
    if not result['shown']:
        return []
    out = [(D['tax_line'].format(percent=percent_text(rate.tax_percent)), result['tax'])]
    if rate.insurance_mode == InsuranceMode.PERCENT:
        out.append((D['insurance_line_percent'].format(percent=percent_text(rate.insurance_value)), result['insurance']))
    elif rate.insurance_mode == InsuranceMode.AMOUNT:
        out.append((D['insurance_line'], result['insurance']))
    return out


def rate_rows(D, rates, today=None):
    """Every rate, newest first, marked as in force now or upcoming."""
    this_month = (today or timezone.localdate()).replace(day=1)
    current = rate_for(rates, this_month)
    rows = []
    for rate in sorted(rates, key=lambda rate: rate.effective_from, reverse=True):
        month = rate.effective_from.strftime('%Y-%m')
        status = ''
        if rate == current:
            status = D['current']
        elif rate.effective_from > this_month:
            status = D['upcoming']
        rows.append({
            'rate': rate, 'month': month, 'status': status,
            'tax': f'{percent_text(rate.tax_percent)}%', 'insurance': insurance_text(rate),
            'confirm_delete': D['confirm_delete'].format(month=month),
        })
    return rows


def snapshot(rate):
    """A rate as plain values the cutting change log can keep."""
    return {
        'effective_from': rate.effective_from.isoformat(), 'tax_percent': str(rate.tax_percent),
        'insurance_mode': rate.insurance_mode, 'insurance_value': str(rate.insurance_value),
    }


# ─── Form ─────────────────────────────────────────────────────

def plain_number(value):
    """'₩150,000', '150000원', '3.3%' and full-width digits → a Decimal, or None."""
    value = unicodedata.normalize('NFKC', str(value or ''))
    for mark in (',', '₩', '\\', '원', '%', ' '):
        value = value.replace(mark, '')
    if not value:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def parse_month(value):
    """'2026-10' (as a month picker sends it) → date(2026, 10, 1), or None."""
    match = re.fullmatch(r'(\d{4})-(\d{1,2})', unicodedata.normalize('NFKC', str(value or '')).strip())
    try:
        first_day = date(int(match[1]), int(match[2]), 1)
    except (TypeError, ValueError):
        return None
    return first_day if 2000 <= first_day.year <= 2100 else None


def valid_percent(number, *, allow_zero):
    return (number is not None and (number >= 0 if allow_zero else number > 0) and number <= 100
            and -number.as_tuple().exponent <= PERCENT_PLACES)


class DeductionRateForm(forms.Form):
    """A rate from a start month. Saving a month that already has a rate replaces it."""
    month = forms.CharField(max_length=10, widget=forms.TextInput(attrs={'type': 'month'}))
    tax_percent = forms.CharField(max_length=12, widget=forms.TextInput(attrs={'inputmode': 'decimal'}))
    insurance_mode = forms.ChoiceField(required=False)
    insurance_value = forms.CharField(
        max_length=20, required=False, widget=forms.TextInput(attrs={'inputmode': 'decimal'}),
    )

    def __init__(self, *args, D, **kwargs):
        super().__init__(*args, **kwargs)
        self.D = D
        fields = self.fields
        fields['month'].label = D['start_month']
        fields['month'].initial = timezone.localdate().strftime('%Y-%m')
        fields['tax_percent'].label = D['tax_percent']
        fields['tax_percent'].help_text = D['tax_percent_help']
        fields['tax_percent'].initial = '0'
        fields['insurance_mode'].label = D['insurance_mode']
        fields['insurance_mode'].choices = [
            (InsuranceMode.NONE, D['insurance_none']),
            (InsuranceMode.PERCENT, D['insurance_percent']),
            (InsuranceMode.AMOUNT, D['insurance_amount']),
        ]
        fields['insurance_value'].label = D['insurance_value']
        fields['insurance_value'].help_text = D['insurance_value_help']
        for field in fields.values():
            field.error_messages.update({'required': D['err_required'], 'invalid_choice': D['err_required'],
                                         'max_length': D['err_number']})
            field.widget.attrs['class'] = 'input-field'

    def clean_month(self):
        first_day = parse_month(self.cleaned_data['month'])
        if first_day is None:
            raise ValidationError(self.D['err_month'])
        return first_day

    def clean_tax_percent(self):
        number = plain_number(self.cleaned_data['tax_percent'])
        if not valid_percent(number, allow_zero=True):
            raise ValidationError(self.D['err_percent'])
        return number

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get('insurance_mode', InsuranceMode.NONE)
        raw = self.data.get(self.add_prefix('insurance_value'), '')
        number = plain_number(raw)
        if mode == InsuranceMode.NONE:
            cleaned['insurance_value'] = ZERO
        elif not str(raw).strip():
            self.add_error('insurance_value', self.D['err_insurance_value'])
        elif mode == InsuranceMode.PERCENT:
            if not valid_percent(number, allow_zero=False):
                self.add_error('insurance_value', self.D['err_percent'])
            else:
                cleaned['insurance_value'] = number
        elif number is None or number < 1 or number > AMOUNT_MAX or number != number.to_integral_value():
            self.add_error('insurance_value', self.D['err_amount'])
        else:
            cleaned['insurance_value'] = number.to_integral_value()
        return cleaned

    def values(self):
        """The rate's fields, for update_or_create(defaults=...)."""
        data = self.cleaned_data
        return {
            'tax_percent': data['tax_percent'],
            'insurance_mode': data['insurance_mode'] or InsuranceMode.NONE,
            'insurance_value': data['insurance_value'],
        }


# ─── Strings ──────────────────────────────────────────────────

STRINGS = {
    'en': {
        'deductions': 'Tax and health insurance',
        'deductions_intro': (
            'Set for this person only. A rate applies from its start month until the next one, so payslips '
            'for earlier months keep the rate they were paid with. Both are taken from gross pay and rounded '
            'down to 10 won. Saving a month that already has a rate replaces it.'
        ),
        'page_title': 'Tax and health insurance — {name}',
        'back_to_users': '← Manage users',
        'start_month': 'From month',
        'tax_percent': 'Income tax (%)',
        'tax_percent_help': 'Percent of gross pay, e.g. 3.3. Type 0 for none.',
        'insurance_mode': 'Health insurance',
        'insurance_none': 'None',
        'insurance_percent': '% of gross pay',
        'insurance_amount': 'Fixed amount (₩)',
        'insurance_value': 'Insurance — % or amount',
        'insurance_value_help': 'For "% of gross pay" type the percent, e.g. 3.545. For a fixed amount type the won, e.g. 150000.',
        'save_rate': 'Save rate',
        'no_rates': 'No rates yet — nothing is deducted.',
        'col_from': 'From',
        'col_tax': 'Income tax',
        'col_insurance': 'Health insurance',
        'current': 'In force now',
        'upcoming': 'Upcoming',
        'delete': 'Delete',
        'confirm_delete': 'Delete the rate starting {month}?',
        'saved': 'Saved the rate starting {month}.',
        'deleted': 'Deleted the rate starting {month}.',
        'err_form': 'Please fix the highlighted fields.',
        'err_required': 'This field is required.',
        'err_number': 'Enter a shorter number.',
        'err_month': 'Pick a month, e.g. 2026-10.',
        'err_percent': 'Enter a percentage from 0 to 100, with up to 3 decimals.',
        'err_amount': 'Enter a whole won amount of 1 or more.',
        'err_insurance_value': 'Enter the insurance percentage or amount.',
        'err_locked': (
            '{month} is locked (paid), and this change would alter its payslips. '
            'Unlock it first, or pick a later start month.'
        ),
        'tax_line': 'Income tax ({percent}%)',
        'insurance_line_percent': 'Health insurance ({percent}%)',
        'insurance_line': 'Health insurance',
        'rate_summary': 'From {month}: tax {tax}%, health insurance {insurance}',
        'manage': 'Tax & insurance',
    },
    'ko': {
        'deductions': '세금 및 건강보험',
        'deductions_intro': (
            '이 사람에게만 적용됩니다. 설정은 시작 월부터 다음 설정 전까지 적용되므로, 이전 달 명세서는 '
            '지급 당시의 공제율을 그대로 유지합니다. 둘 다 총 지급액 기준이며 10원 미만은 버립니다. '
            '이미 설정이 있는 월에 저장하면 그 설정을 바꿉니다.'
        ),
        'page_title': '세금 및 건강보험 — {name}',
        'back_to_users': '← 사용자 관리',
        'start_month': '적용 시작 월',
        'tax_percent': '소득세 (%)',
        'tax_percent_help': '총 지급액의 비율입니다. 예: 3.3. 없으면 0을 입력하세요.',
        'insurance_mode': '건강보험',
        'insurance_none': '없음',
        'insurance_percent': '총 지급액의 %',
        'insurance_amount': '고정 금액 (₩)',
        'insurance_value': '보험료 — % 또는 금액',
        'insurance_value_help': '"총 지급액의 %"는 비율을 입력하세요(예: 3.545). 고정 금액은 원 단위로 입력하세요(예: 150000).',
        'save_rate': '저장',
        'no_rates': '아직 설정이 없어 공제하지 않습니다.',
        'col_from': '적용 시작',
        'col_tax': '소득세',
        'col_insurance': '건강보험',
        'current': '현재 적용',
        'upcoming': '예정',
        'delete': '삭제',
        'confirm_delete': '{month}부터 적용되는 설정을 삭제할까요?',
        'saved': '{month}부터 적용되는 설정을 저장했습니다.',
        'deleted': '{month}부터 적용되는 설정을 삭제했습니다.',
        'err_form': '표시된 항목을 고쳐 주세요.',
        'err_required': '필수 항목입니다.',
        'err_number': '더 짧은 숫자를 입력하세요.',
        'err_month': '월을 선택하세요. 예: 2026-10',
        'err_percent': '0에서 100 사이의 비율을 소수점 셋째 자리까지 입력하세요.',
        'err_amount': '1원 이상의 금액을 원 단위로 입력하세요.',
        'err_insurance_value': '보험료 비율 또는 금액을 입력하세요.',
        'err_locked': (
            '{month}은(는) 지급 완료되어 잠겨 있으며, 이 변경은 해당 월 명세서를 바꿉니다. '
            '먼저 잠금을 해제하거나 더 늦은 시작 월을 선택하세요.'
        ),
        'tax_line': '소득세 ({percent}%)',
        'insurance_line_percent': '건강보험 ({percent}%)',
        'insurance_line': '건강보험',
        'rate_summary': '{month}부터: 소득세 {tax}%, 건강보험 {insurance}',
        'manage': '세금·보험',
    },
}


def strings(lang):
    return STRINGS['ko' if lang == 'ko' else 'en']
