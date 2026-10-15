"""Employees' hourly wages by month, and the "Edit employee" page's forms and text.

Every pay figure — calendars, the dashboard, the paper view and payslips — takes the wage
from wage_for(), so a raise entered "from November" changes November on, never October.
"""
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .deductions import parse_month, plain_number, rate_for
from .models import CustomUser

WAGE_MAX = Decimal('99999999.99')


def this_month():
    return timezone.localdate().replace(day=1)


def wage_for(user, first_day):
    """The hourly wage for the month starting `first_day`.

    The latest wage starting on or before that month; for a month before their first wage,
    that first wage (work entered before they were set up is paid at it); with no wages
    recorded at all, CustomUser.hourly_wage. Reads a prefetched `wages` set if there is one.
    """
    wages = list(user.wages.all())
    if not wages:
        return user.hourly_wage or Decimal(0)
    wage = rate_for(wages, first_day) or min(wages, key=lambda wage: wage.effective_from)
    return wage.hourly_wage


def pay_for(user, hours):
    """Pay for a WorkHours queryset that may span months: each month's hours at that month's wage."""
    by_month = hours.annotate(month=TruncMonth('date')).values('month').annotate(total=Sum('hours'))
    return sum((row['total'] * wage_for(user, row['month']) for row in by_month), Decimal(0))


def wage_text(amount):
    return f'{Decimal(amount):,.0f}' if Decimal(amount) == Decimal(amount).to_integral_value() else f'{Decimal(amount):,.2f}'


def wage_rows(S, wages, today=None):
    """Every wage, newest first, marked as in force now or upcoming."""
    month = (today or timezone.localdate()).replace(day=1)
    current = rate_for(wages, month) or (min(wages, key=lambda wage: wage.effective_from) if wages else None)
    rows = []
    for wage in sorted(wages, key=lambda wage: wage.effective_from, reverse=True):
        label = wage.effective_from.strftime('%Y-%m')
        status = ''
        if wage == current:
            status = S['current']
        elif wage.effective_from > month:
            status = S['upcoming']
        rows.append({
            'wage': wage, 'month': label, 'status': status,
            'amount': S['per_hour'].format(wage=wage_text(wage.hourly_wage)),
            'confirm_delete': S['confirm_delete'].format(month=label),
        })
    return rows


# ─── Forms ────────────────────────────────────────────────────

def style(form, S):
    for field in form.fields.values():
        field.error_messages.update({'required': S['err_required'], 'invalid': S['err_invalid'],
                                     'max_length': S['err_invalid']})
        if not isinstance(field.widget, forms.CheckboxInput):
            field.widget.attrs['class'] = 'input-field'
        else:
            field.widget.attrs['class'] = 'checkbox-input'


class WageForm(forms.Form):
    """A wage from a start month. Saving a month that already has a wage replaces it."""
    month = forms.CharField(max_length=10, widget=forms.TextInput(attrs={'type': 'month'}))
    hourly_wage = forms.CharField(max_length=20, widget=forms.TextInput(attrs={'inputmode': 'decimal'}))

    def __init__(self, *args, S, **kwargs):
        super().__init__(*args, **kwargs)
        self.S = S
        self.fields['month'].label = S['start_month']
        self.fields['month'].initial = timezone.localdate().strftime('%Y-%m')
        self.fields['hourly_wage'].label = S['hourly_wage']
        style(self, S)

    def clean_month(self):
        first_day = parse_month(self.cleaned_data['month'])
        if first_day is None:
            raise ValidationError(self.S['err_month'])
        return first_day

    def clean_hourly_wage(self):
        number = plain_number(self.cleaned_data['hourly_wage'])
        if number is None or number < 0 or number > WAGE_MAX or -number.as_tuple().exponent > 2:
            raise ValidationError(self.S['err_wage'])
        return number


class EmployeeDetailsForm(forms.ModelForm):
    """Name, contact, bank and role. The login follows the email when it was the email."""

    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'email', 'bank_name', 'account_number', 'visa_type',
                  'is_contracted', 'is_employee', 'is_admin']

    def __init__(self, *args, S, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.S = S
        self.old_email = self.instance.email
        for name, field in self.fields.items():
            field.label = S[f'field_{name}']
        self.fields['email'].required = True
        if actor.pk == self.instance.pk:
            # Unticking your own Admin box would lock you out of this page.
            self.fields['is_admin'].disabled = True
            self.fields['is_admin'].help_text = S['own_admin_help']
        style(self, S)

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if self.signs_in_with_email() and email.lower() != self.old_email.lower():
            clash = CustomUser.objects.filter(username__iexact=email).exclude(pk=self.instance.pk)
            if clash.exists():
                raise ValidationError(self.S['err_email_taken'])
        return email

    def signs_in_with_email(self):
        return self.instance.username.lower() == (self.old_email or '').lower()

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.signs_in_with_email():
            user.username = user.email
        if commit:
            user.save()
        return user


# ─── Strings ──────────────────────────────────────────────────

STRINGS = {
    'en': {
        'page_title': 'Edit employee — {name}',
        'back_to_users': '← Manage users',
        'details': 'Details',
        'signs_in_as': 'Signs in with: {username}',
        'field_first_name': 'First name',
        'field_last_name': 'Last name',
        'field_email': 'Email',
        'field_bank_name': 'Bank name',
        'field_account_number': 'Account number',
        'field_visa_type': 'Visa type',
        'field_is_contracted': 'Contracted',
        'field_is_employee': 'Employee (shows on payroll)',
        'field_is_admin': 'Admin (can manage the site)',
        'own_admin_help': "You can't remove your own admin rights.",
        'save_details': 'Save details',
        'saved': 'Saved {name}.',
        'err_form': 'Please fix the highlighted fields.',
        'err_required': 'This field is required.',
        'err_invalid': 'Enter a valid value.',
        'err_email_taken': 'Another account already signs in with this email.',
        'err_superuser': 'Only a superuser can edit this account.',
        'wages': 'Hourly wage',
        'wages_intro': (
            "A wage applies from its start month until the next one. Each month's pay uses that month's wage, "
            'so a raise entered from next month never changes earlier payslips. '
            'Saving a month that already has a wage replaces it.'
        ),
        'start_month': 'From month',
        'hourly_wage': 'Hourly wage (₩)',
        'save_wage': 'Save wage',
        'current': 'In force now',
        'upcoming': 'Upcoming',
        'per_hour': '₩{wage} / hour',
        'col_from': 'From',
        'delete': 'Delete',
        'confirm_delete': 'Delete the wage starting {month}?',
        'no_wages': 'No wage recorded yet.',
        'wage_saved': 'Saved the wage from {month}: ₩{wage} / hour.',
        'wage_deleted': 'Deleted the wage from {month}.',
        'wage_only_one': "This is their only wage, so it can't be deleted. Add the correct one first.",
        'below_minimum': 'Note: ₩{wage} / hour is below the minimum wage set on Manage users (₩{minimum}).',
        'err_month': 'Pick a month, e.g. 2026-10.',
        'err_wage': 'Enter an hourly wage of 0 or more, with up to 2 decimals.',
        'tax_link': 'Tax & insurance →',
    },
    'ko': {
        'page_title': '직원 정보 수정 — {name}',
        'back_to_users': '← 사용자 관리',
        'details': '기본 정보',
        'signs_in_as': '로그인 아이디: {username}',
        'field_first_name': '이름',
        'field_last_name': '성',
        'field_email': '이메일',
        'field_bank_name': '은행',
        'field_account_number': '계좌 번호',
        'field_visa_type': '비자 유형',
        'field_is_contracted': '계약직',
        'field_is_employee': '직원 (급여 대상)',
        'field_is_admin': '관리자 (사이트 관리 권한)',
        'own_admin_help': '자신의 관리자 권한은 해제할 수 없습니다.',
        'save_details': '저장',
        'saved': '{name} 님 정보를 저장했습니다.',
        'err_form': '표시된 항목을 고쳐 주세요.',
        'err_required': '필수 항목입니다.',
        'err_invalid': '올바른 값을 입력하세요.',
        'err_email_taken': '이 이메일로 로그인하는 다른 계정이 이미 있습니다.',
        'err_superuser': '이 계정은 슈퍼유저만 수정할 수 있습니다.',
        'wages': '시급',
        'wages_intro': (
            '시급은 시작 월부터 다음 시급 전까지 적용됩니다. 매달 급여는 그 달의 시급으로 계산하므로, '
            '다음 달부터 인상한 시급은 이전 명세서를 바꾸지 않습니다. '
            '이미 시급이 있는 월에 저장하면 그 시급을 바꿉니다.'
        ),
        'start_month': '적용 시작 월',
        'hourly_wage': '시급 (₩)',
        'save_wage': '저장',
        'current': '현재 적용',
        'upcoming': '예정',
        'per_hour': '시간당 ₩{wage}',
        'col_from': '적용 시작',
        'delete': '삭제',
        'confirm_delete': '{month}부터 적용되는 시급을 삭제할까요?',
        'no_wages': '아직 기록된 시급이 없습니다.',
        'wage_saved': '{month}부터 시간당 ₩{wage}을(를) 저장했습니다.',
        'wage_deleted': '{month}부터 적용되는 시급을 삭제했습니다.',
        'wage_only_one': '유일한 시급이라 삭제할 수 없습니다. 올바른 시급을 먼저 추가하세요.',
        'below_minimum': '참고: 시간당 ₩{wage}은(는) 사용자 관리에 설정된 최저 임금(₩{minimum})보다 낮습니다.',
        'err_month': '월을 선택하세요. 예: 2026-10',
        'err_wage': '0 이상의 시급을 소수점 둘째 자리까지 입력하세요.',
        'tax_link': '세금·보험 →',
    },
}


def strings(lang):
    return STRINGS['ko' if lang == 'ko' else 'en']
