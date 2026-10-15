from datetime import date
from decimal import Decimal
from string import Formatter

from django.test import TestCase
from django.urls import reverse

from . import deductions
from .deductions import DeductionRateForm, compute, rate_for
from .models import CardExpense, CustomUser, EmployeeDeduction, InsuranceMode, WorkHours

D = deductions.STRINGS['en']
SEPT, OCT = date(2026, 9, 1), date(2026, 10, 1)


def rate(month=SEPT, tax='0', mode=InsuranceMode.NONE, value='0'):
    """An unsaved rate — compute() only reads its fields."""
    return EmployeeDeduction(effective_from=month, tax_percent=Decimal(tax), insurance_mode=mode,
                             insurance_value=Decimal(value))


class ComputeTests(TestCase):
    def test_tax_and_percent_insurance_are_taken_from_gross_and_rounded_down_to_10_won(self):
        result = compute(Decimal('79000'), rate(tax='3.3', mode=InsuranceMode.PERCENT, value='3.545'))
        self.assertEqual(result['tax'], 2600)        # 2,607 → 2,600
        self.assertEqual(result['insurance'], 2800)  # 2,800.55 → 2,800
        self.assertEqual(result['total'], 5400)
        self.assertEqual(result['net'], 73600)

    def test_fixed_insurance_is_taken_as_is(self):
        result = compute(1000000, rate(mode=InsuranceMode.AMOUNT, value='150000'))
        self.assertEqual((result['tax'], result['insurance'], result['net']), (0, 150000, 850000))

    def test_no_rate_or_no_pay_deducts_nothing(self):
        self.assertEqual(compute(500000, None)['total'], 0)
        self.assertFalse(compute(500000, None)['shown'])
        # A month with no pay has nothing to take a fixed amount from.
        nothing = compute(0, rate(tax='3.3', mode=InsuranceMode.AMOUNT, value='150000'))
        self.assertEqual((nothing['total'], nothing['net']), (0, 0))
        self.assertTrue(nothing['shown'])

    def test_a_month_uses_the_latest_rate_starting_on_or_before_it(self):
        rates = [rate(month=date(2026, 1, 1), tax='1'), rate(month=SEPT, tax='2'), rate(month=OCT, tax='3')]
        self.assertIsNone(rate_for(rates, date(2025, 12, 1)))
        self.assertEqual(rate_for(rates, date(2026, 8, 1)).tax_percent, 1)
        self.assertEqual(rate_for(rates, SEPT).tax_percent, 2)
        self.assertEqual(rate_for(rates, date(2027, 3, 1)).tax_percent, 3)

    def test_percent_text_drops_trailing_zeros(self):
        self.assertEqual(deductions.percent_text(Decimal('3.300')), '3.3')
        self.assertEqual(deductions.percent_text(Decimal('10.000')), '10')
        self.assertEqual(deductions.percent_text(Decimal('3.545')), '3.545')


class DeductionFormTests(TestCase):
    def form(self, **data):
        base = {'month': '2026-10', 'tax_percent': '3.3', 'insurance_mode': '', 'insurance_value': ''}
        return DeductionRateForm({**base, **data}, D=D)

    def test_a_typical_rate(self):
        form = self.form(insurance_mode='amount', insurance_value='₩150,000')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['month'], OCT)
        self.assertEqual(form.values(), {
            'tax_percent': Decimal('3.3'), 'insurance_mode': 'amount', 'insurance_value': Decimal('150000'),
        })

    def test_percent_signs_won_signs_and_full_width_digits_are_accepted(self):
        form = self.form(tax_percent='３.３%', insurance_mode='percent', insurance_value='3.545%')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['tax_percent'], Decimal('3.3'))
        self.assertEqual(form.cleaned_data['insurance_value'], Decimal('3.545'))

    def test_no_insurance_ignores_the_value_box(self):
        form = self.form(insurance_value='123')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.values()['insurance_value'], 0)

    def test_bad_input_is_refused_with_a_clear_message(self):
        cases = {
            'month': ({'month': '2026-13'}, D['err_month']),
            'month ': ({'month': 'October'}, D['err_month']),
            'tax_percent': ({'tax_percent': '101'}, D['err_percent']),
            'tax_percent ': ({'tax_percent': '3.3333'}, D['err_percent']),
            'insurance_value': ({'insurance_mode': 'percent', 'insurance_value': ''}, D['err_insurance_value']),
            'insurance_value ': ({'insurance_mode': 'percent', 'insurance_value': '0'}, D['err_percent']),
            'insurance_value  ': ({'insurance_mode': 'amount', 'insurance_value': '1500.5'}, D['err_amount']),
            'insurance_value   ': ({'insurance_mode': 'amount', 'insurance_value': 'lots'}, D['err_amount']),
        }
        for field, (data, message) in cases.items():
            with self.subTest(data=data):
                form = self.form(**data)
                self.assertFalse(form.is_valid())
                self.assertEqual(form.errors[field.strip()], [message])


class DeductionStringsTests(TestCase):
    def test_both_languages_have_the_same_keys_and_placeholders(self):
        en, ko = deductions.STRINGS['en'], deductions.STRINGS['ko']
        self.assertEqual(set(en), set(ko))
        for key in en:
            with self.subTest(key=key):
                fields = lambda text: sorted(name for _, name, _, _ in Formatter().parse(text) if name)
                self.assertEqual(fields(en[key]), fields(ko[key]))


class EmployeeDeductionPageTests(TestCase):
    def setUp(self):
        self.manager = CustomUser.objects.create_user(
            username='boss', email='boss@example.com', password='not-a-real-pass-123', is_admin=True)
        self.kim = CustomUser.objects.create_user(
            username='kim', email='kim@example.com', password='not-a-real-pass-123', is_employee=True,
            hourly_wage=10000)
        self.url = reverse('employee_deductions', args=[self.kim.pk])
        self.client.force_login(self.manager)

    def post_rate(self, **data):
        base = {'month': '2026-09', 'tax_percent': '3.3', 'insurance_mode': 'percent', 'insurance_value': '3.545'}
        return self.client.post(self.url, {**base, **data})

    def test_a_manager_adds_replaces_and_deletes_a_rate(self):
        self.assertRedirects(self.post_rate(), self.url)
        saved = EmployeeDeduction.objects.get(user=self.kim)
        self.assertEqual((saved.effective_from, saved.tax_percent), (SEPT, Decimal('3.3')))

        self.post_rate(tax_percent='5')  # the same month again replaces it
        self.assertEqual(EmployeeDeduction.objects.get(user=self.kim).tax_percent, 5)

        page = self.client.get(self.url)
        self.assertContains(page, '2026-09')
        self.assertContains(page, '5%')

        response = self.client.post(reverse('employee_deduction_delete', args=[saved.pk]))
        self.assertRedirects(response, self.url)
        self.assertFalse(EmployeeDeduction.objects.exists())

    def test_invalid_input_shows_the_form_again(self):
        response = self.post_rate(tax_percent='200')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, D['err_percent'])
        self.assertFalse(EmployeeDeduction.objects.exists())

    def test_the_manage_users_page_links_to_it(self):
        self.assertContains(self.client.get(reverse('manage_users')), self.url)

    def test_employees_cannot_see_or_change_rates(self):
        self.client.force_login(self.kim)
        self.assertRedirects(self.client.get(self.url), reverse('calendar'), fetch_redirect_response=False)
        self.post_rate()
        self.assertFalse(EmployeeDeduction.objects.exists())


class EmployeePayslipTests(TestCase):
    """Kim: ₩10,000/h. September: 100 hours (₩1,000,000) and a ₩5,000 card expense. August: 10 hours."""

    def setUp(self):
        self.manager = CustomUser.objects.create_user(
            username='boss', email='boss@example.com', password='not-a-real-pass-123', is_admin=True)
        self.kim = CustomUser.objects.create_user(
            username='kim', email='kim@example.com', password='not-a-real-pass-123', is_employee=True,
            hourly_wage=10000)
        for day in range(1, 11):
            WorkHours.objects.create(user=self.kim, date=date(2026, 9, day), hours=10)
        WorkHours.objects.create(user=self.kim, date=date(2026, 8, 3), hours=10)
        CardExpense.objects.create(user=self.kim, amount=5000, date=date(2026, 9, 2), description='Fuel')
        self.client.force_login(self.manager)

    def payslip(self, month):
        return self.client.get(reverse('payslip', args=[self.kim.pk]), {'year': 2026, 'month': month})

    def test_tax_insurance_and_card_expenses_come_off_gross_pay(self):
        EmployeeDeduction.objects.create(user=self.kim, effective_from=SEPT, tax_percent=Decimal('3.3'),
                                         insurance_mode=InsuranceMode.PERCENT, insurance_value=Decimal('3.545'))
        response = self.payslip(9)
        self.assertEqual(response.context['ded']['tax'], 33000)
        self.assertEqual(response.context['ded']['insurance'], 35450)
        self.assertEqual(response.context['net'], 1000000 - 33000 - 35450 - 5000)
        self.assertContains(response, 'Income tax (3.3%)')
        self.assertContains(response, 'Health insurance (3.545%)')
        self.assertContains(response, '&#8361;926550')

    def test_earlier_months_keep_their_own_rate(self):
        EmployeeDeduction.objects.create(user=self.kim, effective_from=SEPT, tax_percent=Decimal('3.3'))
        EmployeeDeduction.objects.create(user=self.kim, effective_from=OCT, tax_percent=Decimal('10'))
        self.assertEqual(self.payslip(9).context['ded']['tax'], 33000)  # October's 10% doesn't reach back
        august = self.payslip(8)  # before any rate
        self.assertEqual(august.context['net'], 100000)
        self.assertNotContains(august, 'Income tax')

    def test_without_a_rate_the_payslip_is_unchanged(self):
        response = self.payslip(9)
        self.assertEqual(response.context['net'], 1000000 - 5000)
        self.assertNotContains(response, 'Deductions (tax and insurance)')

    def test_the_email_lists_the_deductions(self):
        EmployeeDeduction.objects.create(user=self.kim, effective_from=SEPT, insurance_mode=InsuranceMode.AMOUNT,
                                         insurance_value=Decimal('150000'))
        from django.core import mail
        self.client.post(f"{reverse('payslip', args=[self.kim.pk])}?year=2026&month=9", {'action': 'email'})
        self.assertEqual(len(mail.outbox), 1)
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn('Health insurance', html)
        self.assertIn('&#8361;845000', html)  # 1,000,000 − 150,000 − 5,000
