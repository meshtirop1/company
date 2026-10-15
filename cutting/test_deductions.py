"""Cutters' tax and health insurance: set per cutter from a month, refused when it would change a
locked month's payslip, logged, and shown on payslips, the monthly pay page and the Excel file."""
from datetime import date
from decimal import Decimal
from io import BytesIO

from django.urls import reverse
from openpyxl import load_workbook

from hours_tracker import deductions
from hours_tracker.models import InsuranceMode

from . import reports, services
from .i18n import STRINGS
from .models import AuditAction, AuditEntry, CutterDeduction, MonthLock
from .test_reports import SEPT, ReportData
from .tests import ManagerTestCase

EN, KO = STRINGS['en'], STRINGS['ko']
D_EN, D_KO = deductions.STRINGS['en'], deductions.STRINGS['ko']
AUG, OCT, NOV = date(2026, 8, 1), date(2026, 10, 1), date(2026, 11, 1)
KIM_RATE = {'tax_percent': Decimal('3.3'), 'insurance_mode': InsuranceMode.AMOUNT, 'insurance_value': Decimal('10000')}
LEE_RATE = {'tax_percent': Decimal('0'), 'insurance_mode': InsuranceMode.PERCENT, 'insurance_value': Decimal('3.545')}


class DeductionTestCase(ReportData, ManagerTestCase):
    """September (see ReportData): Kim earns ₩79,000, Lee ₩21,000, Park ₩15,000.
    Kim: 3.3% tax + ₩10,000 insurance → ₩2,600 + ₩10,000, net ₩66,400.
    Lee: 3.545% insurance → ₩740 (744.45 rounded down to 10 won), net ₩20,260. Park: none."""

    def setUp(self):
        super().setUp()
        self.build()

    def set_rates(self):
        services.set_deduction(self.kim, SEPT, KIM_RATE, user=self.manager)
        services.set_deduction(self.lee, SEPT, LEE_RATE, user=self.manager)


class ReportDeductionTests(DeductionTestCase):
    def test_a_cutters_month(self):
        self.set_rates()
        result = reports.cutter_month(self.kim, SEPT)['deductions']
        self.assertEqual((result['gross'], result['tax'], result['insurance'], result['net']), (79000, 2600, 10000, 66400))

    def test_the_month_summary(self):
        self.set_rates()
        summary = reports.month_summary(SEPT)
        rows = {row['cutter'].name: row['deductions'] for row in summary['rows']}
        self.assertEqual(rows['Lee']['insurance'], 740)
        self.assertEqual(rows['Lee']['net'], 20260)
        self.assertFalse(rows['Park']['shown'])
        self.assertEqual(rows['Park']['net'], 15000)
        self.assertTrue(summary['has_deductions'])
        self.assertEqual((summary['tax'], summary['insurance'], summary['net']), (2600, 10740, 115000 - 13340))

    def test_a_later_rate_does_not_reach_back(self):
        self.set_rates()
        services.set_deduction(self.kim, OCT, {**KIM_RATE, 'tax_percent': Decimal('10')}, user=self.manager)
        self.assertEqual(reports.cutter_month(self.kim, SEPT)['deductions']['tax'], 2600)

    def test_without_rates_nothing_changes(self):
        summary = reports.month_summary(SEPT)
        self.assertFalse(summary['has_deductions'])
        self.assertEqual(summary['net'], summary['total'])


class DeductionLockTests(DeductionTestCase):
    """September is locked (paid). A rate covers its month and every month until the cutter's next one."""

    def setUp(self):
        super().setUp()
        MonthLock.objects.create(month=SEPT)

    def test_a_rate_that_would_cover_the_locked_month_is_refused(self):
        for start in (SEPT, AUG):
            with self.subTest(start=start), self.assertRaises(services.MonthLocked) as refused:
                services.set_deduction(self.kim, start, KIM_RATE, user=self.manager)
            self.assertEqual(refused.exception.month, SEPT)
        self.assertFalse(CutterDeduction.objects.exists())

    def test_a_rate_after_the_locked_month_is_fine(self):
        services.set_deduction(self.kim, OCT, KIM_RATE, user=self.manager)
        self.assertEqual(CutterDeduction.objects.get().effective_from, OCT)

    def test_a_later_rate_bounds_what_an_earlier_one_covers(self):
        services.set_deduction(self.kim, NOV, KIM_RATE, user=self.manager)
        services.set_deduction(self.kim, OCT, KIM_RATE, user=self.manager)  # covers October only
        with self.assertRaises(services.MonthLocked):
            services.set_deduction(self.kim, AUG, KIM_RATE, user=self.manager)  # Aug–Oct takes in September

    def test_deleting_a_rate_that_covers_the_locked_month_is_refused(self):
        MonthLock.objects.all().delete()
        rate = services.set_deduction(self.kim, AUG, KIM_RATE, user=self.manager)
        MonthLock.objects.create(month=SEPT)
        with self.assertRaises(services.MonthLocked):
            services.delete_deduction(rate, user=self.manager)
        self.assertTrue(CutterDeduction.objects.filter(pk=rate.pk).exists())

    def test_the_page_explains_the_refusal(self):
        self.use_korean()
        response = self.client.post(reverse('cutting:cutter_deduction_set', args=[self.kim.pk]), {
            'month': '2026-09', 'tax_percent': '3.3', 'insurance_mode': '', 'insurance_value': '',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, D_KO['err_locked'].format(month='2026-09'))
        self.assertFalse(CutterDeduction.objects.exists())


class DeductionPageTests(DeductionTestCase):
    def post_rate(self, **data):
        base = {'month': '2026-10', 'tax_percent': '3.3', 'insurance_mode': 'amount', 'insurance_value': '₩150,000'}
        return self.client.post(reverse('cutting:cutter_deduction_set', args=[self.kim.pk]), {**base, **data})

    def test_setting_a_rate_is_saved_and_logged_once(self):
        edit_url = reverse('cutting:cutter_edit', args=[self.kim.pk])
        self.assertRedirects(self.post_rate(), f'{edit_url}#deductions', fetch_redirect_response=False)
        rate = CutterDeduction.objects.get(cutter=self.kim)
        self.assertEqual((rate.effective_from, rate.insurance_value), (OCT, 150000))
        entry = AuditEntry.objects.get(action=AuditAction.DEDUCTION_SET)
        self.assertEqual((entry.month, entry.cutter_name, entry.before), (OCT, 'Kim', None))
        self.assertEqual(entry.after['tax_percent'], '3.300')

        self.post_rate()  # saved again unchanged: nothing new in the log
        self.assertEqual(AuditEntry.objects.filter(action=AuditAction.DEDUCTION_SET).count(), 1)

        page = self.client.get(edit_url)
        self.assertContains(page, '₩150,000')
        self.assertContains(page, D_EN['deductions'])

    def test_deleting_a_rate_is_logged(self):
        self.post_rate()
        rate = CutterDeduction.objects.get()
        self.client.post(reverse('cutting:cutter_deduction_delete', args=[rate.pk]))
        self.assertFalse(CutterDeduction.objects.exists())
        entry = AuditEntry.objects.get(action=AuditAction.DEDUCTION_DELETE)
        self.assertEqual(entry.before['insurance_value'], '150000.000')

    def test_the_change_log_reads_naturally(self):
        self.post_rate()
        response = self.client.get(reverse('cutting:audit'))
        self.assertContains(response, EN['action_deduction_set'])
        self.assertContains(response, 'From 2026-10: tax 3.3%, health insurance ₩150,000')

    def test_the_cutter_details_form_still_posts_to_itself(self):
        # The page is also shown by the tax form's URL; renaming there must not post to it.
        response = self.post_rate(tax_percent='bad')
        self.assertContains(response, f'action="{reverse("cutting:cutter_edit", args=[self.kim.pk])}"')

    def test_the_help_page_covers_it(self):
        self.assertContains(self.client.get(reverse('cutting:help')), EN['help_deductions_title'])


class DeductionOutputTests(DeductionTestCase):
    def setUp(self):
        super().setUp()
        self.set_rates()

    def test_the_payslip_shows_the_deductions_and_net_pay(self):
        response = self.client.get(reverse('cutting:payslip', args=[SEPT, self.kim.pk]))
        self.assertContains(response, EN['net_pay'])
        self.assertContains(response, 'Income tax (3.3%)')
        self.assertContains(response, '−₩2,600')
        self.assertContains(response, '−₩10,000')
        self.assertContains(response, '₩66,400')

    def test_a_korean_payslip_uses_korean_labels(self):
        response = self.client.get(reverse('cutting:payslip', args=[SEPT, self.kim.pk]), {'slip_lang': 'ko'})
        self.assertContains(response, KO['net_pay'])
        self.assertContains(response, '소득세 (3.3%)')

    def test_a_cutter_without_rates_keeps_the_plain_payslip(self):
        response = self.client.get(reverse('cutting:payslip', args=[SEPT, self.park.pk]))
        self.assertContains(response, EN['total_pay'])
        self.assertNotContains(response, EN['net_pay'])

    def test_the_monthly_pay_page_shows_net_pay(self):
        response = self.client.get(reverse('cutting:month', args=[SEPT]))
        self.assertContains(response, EN['net_col'])
        self.assertContains(response, '₩101,660')  # the month's net

    def test_the_excel_summary_has_tax_insurance_and_net_columns(self):
        response = self.client.get(reverse('cutting:month_export', args=[SEPT]))
        sheet = load_workbook(BytesIO(response.content))[EN['xl_summary_sheet']]
        header = [cell.value for cell in sheet[4]]
        self.assertEqual(header[-3:], [EN['xl_tax'], EN['xl_insurance'], EN['xl_net']])
        rows = {row[0]: row[-3:] for row in sheet.iter_rows(min_row=5, values_only=True)}
        self.assertEqual(rows['Kim'], (2600, 10000, 66400))
        self.assertEqual(rows['Park'], (0, 0, 15000))
        self.assertEqual(rows[EN['xl_total_row']], (2600, 10740, 101660))
