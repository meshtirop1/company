"""Skin peeling by outside companies: the count cross-check, pay per fish brought back, tax per
company, the paid-month lock, and the pages."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from . import peeling
from .i18n import STRINGS
from .models import AuditAction, AuditEntry, PeelCompany, PeelKind, PeelMovement, PeelPaid, TaxMode
from .tests import ManagerTestCase, make_user

EN, KO = STRINGS['en'], STRINGS['ko']
SEPT = date(2026, 9, 1)
AFTER_SEPT = date(2026, 10, 5)


def last_month():
    return (timezone.localdate().replace(day=1) - timedelta(days=1)).replace(day=1)


class PeelData:
    """Company A, ₩140 a fish from Sept 1 and ₩150 from Sept 15 — the example from the owner:
      9/2 give 7,000 · 9/5 back 3,000 · 9/10 back 3,000 · 9/12 give 2,000 (more while bringing back)
      9/20 back 1,000 (at ₩150) · 9/25 lost 20
    Given 9,000 = back 7,000 + lost 20 + still with them 1,980.
    Pay: 6,000 × ₩140 + 1,000 × ₩150 = ₩990,000."""

    def build(self, tax_mode=TaxMode.NONE):
        self.company = PeelCompany.objects.create(name='A Peeling', tax_mode=tax_mode)
        user = getattr(self, 'manager', None)
        peeling.set_price(self.company, day=date(2026, 9, 1), price_per_fish=140, user=user)
        peeling.set_price(self.company, day=date(2026, 9, 15), price_per_fish=150, user=user)
        for day, kind, fish in ((2, 'out', 7000), (5, 'back', 3000), (10, 'back', 3000), (12, 'out', 2000),
                                (20, 'back', 1000), (25, 'lost', 20)):
            self.add(date(2026, 9, day), kind, fish)

    def add(self, day, kind, fish, company=None):
        return peeling.record(company or self.company, day=day, kind=kind, fish=fish,
                              user=getattr(self, 'manager', None), token=uuid.uuid4())


class PeelMathTests(PeelData, TestCase):
    def setUp(self):
        self.build()

    def test_the_count_cross_check(self):
        self.assertEqual(peeling.company_counts(self.company),
                         {'out': 9000, 'back': 7000, 'lost': 20, 'with_them': 1980})

    def test_pay_uses_the_price_on_the_day_each_batch_came_back(self):
        backs = PeelMovement.objects.filter(kind=PeelKind.BACK).order_by('date')
        self.assertEqual([(m.unit_price, m.amount) for m in backs],
                         [(140, 420000), (140, 420000), (150, 150000)])
        figures = peeling.statement(self.company, SEPT)
        self.assertEqual((figures['fish_back'], figures['amount'], figures['tax'], figures['total']),
                         (7000, 990000, 0, 990000))

    def test_lost_and_given_fish_are_not_paid(self):
        self.assertEqual(PeelMovement.objects.exclude(kind=PeelKind.BACK).filter(amount__gt=0).count(), 0)

    def test_tax_settings(self):
        self.assertEqual(peeling.tax_on(990000, TaxMode.VAT), (99000, 1089000))
        self.assertEqual(peeling.tax_on(990000, TaxMode.WITHHOLD), (29700 + 2970, 990000 - 32670))
        # Rounding: VAT drops the part of a won; withholding rounds each part down to 10 won.
        self.assertEqual(peeling.tax_on(123457, TaxMode.VAT), (12345, 135802))
        self.assertEqual(peeling.tax_on(123457, TaxMode.WITHHOLD), (3700 + 370, 123457 - 4070))
        self.assertEqual(peeling.tax_on(5000, TaxMode.NONE), (0, 5000))

    def test_the_statement_counts_the_month_and_what_is_left_at_its_end(self):
        self.add(date(2026, 10, 3), 'back', 500)
        figures = peeling.statement(self.company, SEPT)
        self.assertEqual(figures['month_counts'], {'out': 9000, 'back': 7000, 'lost': 20, 'with_them': 1980})
        self.assertEqual(figures['end_counts']['with_them'], 1980)  # October's batch doesn't count yet
        self.assertEqual(peeling.company_counts(self.company)['with_them'], 1480)


class PeelRuleTests(PeelData, TestCase):
    def setUp(self):
        self.build()

    def test_more_cannot_come_back_than_they_have(self):
        for kind in ('back', 'lost'):
            with self.subTest(kind=kind), self.assertRaises(peeling.TooManyBack) as refused:
                self.add(date(2026, 9, 28), kind, 2000)
            self.assertEqual(refused.exception.short, 20)  # they only have 1,980
        self.assertEqual(PeelMovement.objects.count(), 6)

    def test_no_price_on_the_day_is_refused(self):
        with self.assertRaises(peeling.NoPrice):
            self.add(date(2026, 8, 31), 'back', 10)

    def test_a_form_saves_only_once(self):
        token = uuid.uuid4()
        peeling.record(self.company, day=date(2026, 9, 28), kind='out', fish=10, token=token)
        with self.assertRaises(IntegrityError):
            peeling.record(self.company, day=date(2026, 9, 28), kind='out', fish=10, token=token)

    def test_correcting_the_count_keeps_the_saved_price(self):
        batch = PeelMovement.objects.get(date=date(2026, 9, 20))
        peeling.update(batch, day=batch.date, fish=900, note='', user=None, reason='miscounted')
        batch.refresh_from_db()
        self.assertEqual((batch.unit_price, batch.amount), (150, 135000))
        entry = AuditEntry.objects.get(action=AuditAction.PEEL_EDIT)
        self.assertEqual((entry.before['fish'], entry.after['fish'], entry.reason), (1000, 900, 'miscounted'))

    def test_moving_a_batch_to_another_day_takes_that_days_price(self):
        batch = PeelMovement.objects.get(date=date(2026, 9, 20))
        peeling.update(batch, day=date(2026, 9, 14), fish=batch.fish, note='', user=None)
        batch.refresh_from_db()
        self.assertEqual((batch.unit_price, batch.amount), (140, 140000))

    def test_deleting_fish_given_that_already_came_back_is_refused(self):
        handover = PeelMovement.objects.get(date=date(2026, 9, 2))
        pk = handover.pk  # delete() clears the in-memory pk even when the change is rolled back
        with self.assertRaises(peeling.TooManyBack):
            peeling.delete(handover, user=None)
        self.assertTrue(PeelMovement.objects.filter(pk=pk).exists())
        self.assertFalse(AuditEntry.objects.filter(action=AuditAction.PEEL_DELETE).exists())

    def test_a_new_price_never_changes_saved_batches(self):
        peeling.set_price(self.company, day=date(2026, 9, 1), price_per_fish=100)
        self.assertEqual(peeling.statement(self.company, SEPT)['amount'], 990000)
        self.assertEqual(AuditEntry.objects.filter(action=AuditAction.PEEL_PRICE).count(), 3)


class PeelPaidTests(PeelData, TestCase):
    def setUp(self):
        self.build(tax_mode=TaxMode.VAT)

    def test_a_month_is_marked_paid_only_once_it_is_over(self):
        with self.assertRaises(peeling.MonthNotOver):
            peeling.mark_paid(self.company, SEPT, user=None, today=date(2026, 9, 29))
        paid = peeling.mark_paid(self.company, SEPT, user=None, today=date(2026, 9, 30))
        self.assertEqual((paid.fish, paid.amount, paid.tax, paid.total), (7000, 990000, 99000, 1089000))
        self.assertEqual(peeling.mark_paid(self.company, SEPT, user=None, today=AFTER_SEPT), paid)

    def test_a_paid_month_refuses_every_change(self):
        peeling.mark_paid(self.company, SEPT, user=None, today=AFTER_SEPT)
        batch = PeelMovement.objects.get(date=date(2026, 9, 20))
        changes = {
            'record': lambda: self.add(date(2026, 9, 28), 'out', 5),
            'update': lambda: peeling.update(batch, day=batch.date, fish=1, note='', user=None),
            'move in': lambda: peeling.update(self.add(date(2026, 10, 2), 'out', 5), day=date(2026, 9, 29),
                                              fish=5, note='', user=None),
            'delete': lambda: peeling.delete(batch, user=None),
        }
        for name, change in changes.items():
            with self.subTest(name), self.assertRaises(peeling.PeelLocked):
                change()
        self.add(date(2026, 10, 2), 'back', 100)  # October is still open

    def test_the_paid_statement_keeps_its_figures_after_a_tax_change(self):
        peeling.mark_paid(self.company, SEPT, user=None, today=AFTER_SEPT)
        self.company.tax_mode = TaxMode.WITHHOLD
        self.company.save()
        figures = peeling.statement(self.company, SEPT)
        self.assertEqual((figures['tax_mode'], figures['total']), (TaxMode.VAT, 1089000))

    def test_reopening_needs_a_reason_and_is_logged(self):
        peeling.mark_paid(self.company, SEPT, user=None, today=AFTER_SEPT)
        self.assertTrue(peeling.reopen(self.company, SEPT, user=None, reason='wrong count'))
        self.assertFalse(PeelPaid.objects.exists())
        entry = AuditEntry.objects.get(action=AuditAction.PEEL_UNPAID)
        self.assertEqual((entry.reason, entry.before['total']), ('wrong count', 1089000))
        self.add(date(2026, 9, 28), 'out', 5)  # open again


class PeelPageTests(PeelData, ManagerTestCase):
    def setUp(self):
        super().setUp()
        self.month = last_month()
        self.company = PeelCompany.objects.create(name='B Peeling')
        peeling.set_price(self.company, day=self.month, price_per_fish=130, user=self.manager)

    def entry(self, **data):
        base = {'company': self.company.pk, 'kind': 'out', 'date': self.month.isoformat(), 'fish': '7,000',
                'note': '', 'token': str(uuid.uuid4())}
        return self.client.post(reverse('cutting:peel_entry'), {**base, **data}, follow=True)

    def test_giving_and_bringing_back_fish(self):
        self.entry()
        response = self.entry(kind='back', fish='3000')
        self.assertContains(response, EN['pl_saved_back'].format(company='B Peeling', fish='3,000', price='130',
                                                                 amount='390,000'))
        self.assertContains(response, escape(EN['pl_check'].format(out='7,000', back='3,000', lost='0',
                                                                    with_them='4,000')))

    def test_a_double_tap_saves_once(self):
        token = str(uuid.uuid4())
        self.entry(token=token)
        response = self.entry(token=token)
        self.assertContains(response, EN['pl_already_saved'])
        self.assertEqual(PeelMovement.objects.count(), 1)

    def test_bringing_back_more_than_they_have_is_explained(self):
        self.entry(fish='100')
        response = self.entry(kind='back', fish='150')
        self.assertContains(response, EN['pl_err_too_many'].format(company='B Peeling', available='100'))
        self.assertEqual(PeelMovement.objects.filter(kind='back').count(), 0)

    def test_future_dates_are_refused(self):
        response = self.entry(date=(timezone.localdate() + timedelta(days=1)).isoformat())
        self.assertContains(response, escape(EN['pl_err_future']))
        self.assertFalse(PeelMovement.objects.exists())

    def test_the_entry_form_is_prefilled_from_the_home_page_buttons(self):
        response = self.client.get(reverse('cutting:peel_entry'), {'company': self.company.pk, 'kind': 'back'})
        self.assertEqual(response.context['form'].initial['company'], self.company)
        self.assertEqual(response.context['form'].initial['kind'], 'back')

    def test_home_company_and_statement_pages(self):
        self.entry()
        self.entry(kind='back', fish='3000')
        home = self.client.get(reverse('cutting:peel_home'))
        self.assertContains(home, 'B Peeling')
        company = self.client.get(reverse('cutting:peel_company', args=[self.company.pk]))
        self.assertContains(company, '₩390,000')
        statement = self.client.get(reverse('cutting:peel_statement', args=[self.company.pk, self.month]))
        self.assertContains(statement, EN['pl_total_to_pay'])
        self.assertContains(statement, '₩390,000')
        self.assertContains(statement, EN['pl_mark_paid'])  # last month is over

    def test_marking_paid_from_the_statement_and_reopening(self):
        self.entry()
        self.entry(kind='back', fish='3000')
        url = reverse('cutting:peel_statement', args=[self.company.pk, self.month])
        self.client.post(reverse('cutting:peel_mark_paid', args=[self.company.pk, self.month]))
        self.assertTrue(PeelPaid.objects.filter(company=self.company, month=self.month).exists())
        refused = self.entry(fish='5')
        self.assertContains(refused, escape(EN['pl_err_locked'].format(month=self.month.strftime('%Y-%m'),
                                                                      company='B Peeling')))
        self.client.post(reverse('cutting:peel_reopen', args=[self.company.pk, self.month]), {'reason': 'recount'})
        self.assertFalse(PeelPaid.objects.exists())
        self.assertContains(self.client.get(url), EN['pl_mark_paid'])

    def test_the_current_month_cannot_be_marked_paid_yet(self):
        this_month = timezone.localdate().replace(day=1)
        response = self.client.post(reverse('cutting:peel_mark_paid', args=[self.company.pk, this_month]), follow=True)
        self.assertFalse(PeelPaid.objects.exists())
        self.assertContains(response, EN['pl_err_paid_early'].split('{')[0])

    def test_adding_a_company_with_its_first_price(self):
        response = self.client.post(reverse('cutting:peel_company_new'), {
            'name': '  C   Peeling ', 'note': '', 'tax_mode': 'withhold', 'price_per_fish': '₩140', 'price_from': '2026-09-01',
        }, follow=True)
        company = PeelCompany.objects.get(name='C Peeling')
        self.assertEqual((company.tax_mode, company.price_on(date(2026, 9, 1)).price_per_fish), ('withhold', 140))
        self.assertContains(response, EN['pl_company_added'].format(name='C Peeling'))
        duplicate = self.client.post(reverse('cutting:peel_company_new'), {
            'name': 'c peeling', 'tax_mode': 'none', 'price_per_fish': '140', 'price_from': '2026-09-01',
        })
        self.assertContains(duplicate, EN['pl_err_duplicate'])

    def test_a_company_with_fish_cannot_be_deactivated(self):
        self.entry(fish='50')
        response = self.client.post(reverse('cutting:peel_company_edit', args=[self.company.pk]), {
            'name': 'B Peeling', 'note': '', 'tax_mode': 'none',
        })
        self.assertContains(response, EN['pl_err_still_has'].format(name='B Peeling', count='50'))
        self.company.refresh_from_db()
        self.assertTrue(self.company.is_active)

    def test_corrections_appear_in_the_change_log(self):
        self.entry()
        movement = PeelMovement.objects.get()
        self.client.post(reverse('cutting:peel_entry_edit', args=[movement.pk]), {
            'date': movement.date.isoformat(), 'fish': '6,900', 'note': '', 'reason': 'recount',
        })
        log = self.client.get(reverse('cutting:audit'))
        self.assertContains(log, EN['action_peel_edit'])
        self.assertContains(log, '7,000 fish')
        self.assertContains(log, '6,900 fish')

    def test_korean_pages(self):
        self.use_korean()
        self.entry()
        self.assertContains(self.client.get(reverse('cutting:peel_home')), KO['pl_title'])
        statement = self.client.get(reverse('cutting:peel_statement', args=[self.company.pk, self.month]))
        self.assertContains(statement, KO['pl_statement_heading'])

    def test_the_hub_and_help_lead_here(self):
        self.assertContains(self.client.get(reverse('cutting:hub')), reverse('cutting:peel_home'))
        self.assertContains(self.client.get(reverse('cutting:help')), EN['help_peeling_title'])

    def test_employees_are_kept_out(self):
        self.client.force_login(make_user('worker', is_employee=True))
        self.assertEqual(self.client.get(reverse('cutting:peel_home')).status_code, 403)


class PeelSummaryTests(PeelData, ManagerTestCase):
    """September across companies:
      A (+10% VAT): the owner's example — ₩990,000 + ₩99,000 VAT = ₩1,089,000; 1,980 still out.
      B (3.3% withheld): 4,000 out, 3,000 back at ₩130 = ₩390,000 − ₩12,870 = ₩377,130; 1,000 out.
      D: 500 given in August and nothing since — still listed, it holds our fish.
      C: inactive, nothing ever — left out."""

    def setUp(self):
        super().setUp()
        self.build(tax_mode=TaxMode.VAT)
        b = PeelCompany.objects.create(name='B Peeling', tax_mode=TaxMode.WITHHOLD)
        peeling.set_price(b, day=SEPT, price_per_fish=130)
        self.add(date(2026, 9, 3), 'out', 4000, company=b)
        self.add(date(2026, 9, 9), 'back', 3000, company=b)
        d = PeelCompany.objects.create(name='D Peeling')
        peeling.set_price(d, day=date(2026, 8, 1), price_per_fish=100)
        self.add(date(2026, 8, 10), 'out', 500, company=d)
        PeelCompany.objects.create(name='C Peeling', is_active=False)

    def test_the_summary_figures(self):
        summary = peeling.month_summary(SEPT)
        self.assertEqual([row['company'].name for row in summary['rows']], ['A Peeling', 'B Peeling', 'D Peeling'])
        signed = {row['company'].name: row['signed_tax'] for row in summary['rows']}
        self.assertEqual(signed, {'A Peeling': 99000, 'B Peeling': -12870, 'D Peeling': 0})
        self.assertEqual(
            {key: summary[key] for key in ('out', 'back', 'lost', 'with_them', 'amount', 'signed_tax', 'total')},
            {'out': 13000, 'back': 10000, 'lost': 20, 'with_them': 3480, 'amount': 1380000,
             'signed_tax': 86130, 'total': 1466130},
        )

    def test_the_summary_page(self):
        response = self.client.get(reverse('cutting:peel_summary', args=[SEPT]))
        self.assertContains(response, EN['pl_summary_heading'])
        for text in ('A Peeling', 'B Peeling', 'D Peeling', '+₩99,000', '−₩12,870', '₩1,466,130', '3,480'):
            self.assertContains(response, text)
        self.assertNotContains(response, 'C Peeling')
        self.assertNotContains(response, EN['provisional_note'].split('{')[0])  # September is over

    def test_a_paid_statement_is_marked(self):
        peeling.mark_paid(self.company, SEPT, user=None, today=AFTER_SEPT)
        self.assertContains(self.client.get(reverse('cutting:peel_summary', args=[SEPT])), '>A Peeling</a> &#128274;')

    def test_this_months_summary_is_provisional_and_the_home_page_links_to_it(self):
        this_month = timezone.localdate().replace(day=1)
        current = self.client.get(reverse('cutting:peel_summary_current'))
        self.assertRedirects(current, reverse('cutting:peel_summary', args=[this_month]))
        self.assertContains(self.client.get(reverse('cutting:peel_summary', args=[this_month])),
                            EN['provisional_note'].split('{')[0])
        self.assertContains(self.client.get(reverse('cutting:peel_home')), reverse('cutting:peel_summary_current'))

    def test_korean(self):
        self.use_korean()
        response = self.client.get(reverse('cutting:peel_summary', args=[SEPT]))
        self.assertContains(response, KO['pl_summary_heading'])
        self.assertContains(response, KO['pl_col_with_them'])


class PeelStatementLinkTests(PeelData, ManagerTestCase):
    """Each company's statement — its own PDF — is one tap away from the list, its page and the summary."""

    def setUp(self):
        super().setUp()
        self.build()

    def test_every_company_links_to_its_statement(self):
        this_month = timezone.localdate().replace(day=1)
        statement = reverse('cutting:peel_statement', args=[self.company.pk, this_month])
        for page in (reverse('cutting:peel_home'), reverse('cutting:peel_company', args=[self.company.pk])):
            with self.subTest(page=page):
                response = self.client.get(page)
                self.assertContains(response, f'href="{statement}"')
                self.assertContains(response, EN['pl_statement_pdf'])
        summary = self.client.get(reverse('cutting:peel_summary', args=[SEPT]))
        self.assertContains(summary, reverse('cutting:peel_statement', args=[self.company.pk, SEPT]))

    def test_korean_label(self):
        self.use_korean()
        self.assertContains(self.client.get(reverse('cutting:peel_home')), KO['pl_statement_pdf'])

