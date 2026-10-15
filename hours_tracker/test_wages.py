from datetime import date, datetime
from decimal import Decimal
from importlib import import_module
from string import Formatter

from django.apps import apps
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from . import wages
from .models import CustomUser, EmployeeWage, Settings, WorkHours

S = wages.STRINGS['en']
SEPT, OCT, NOV = date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1)
PASSWORD = 'not-a-real-pass-123'


def make_user(username, **fields):
    fields.setdefault('email', f'{username}@example.com')
    return CustomUser.objects.create_user(username=fields['email'] if username == '@email' else username,
                                          password=PASSWORD, **fields)


def work(user, day, hours):
    WorkHours.objects.create(user=user, date=day, hours=hours)


class WageLookupTests(TestCase):
    def setUp(self):
        self.kim = make_user('kim', is_employee=True, hourly_wage=9000)

    def test_a_month_uses_its_own_wage(self):
        EmployeeWage.objects.create(user=self.kim, effective_from=SEPT, hourly_wage=10000)
        EmployeeWage.objects.create(user=self.kim, effective_from=NOV, hourly_wage=12000)
        self.assertEqual(wages.wage_for(self.kim, SEPT), 10000)
        self.assertEqual(wages.wage_for(self.kim, OCT), 10000)
        self.assertEqual(wages.wage_for(self.kim, NOV), 12000)
        self.assertEqual(wages.wage_for(self.kim, date(2027, 5, 1)), 12000)
        # Before their first wage, the first wage applies (work entered before they were set up).
        self.assertEqual(wages.wage_for(self.kim, date(2026, 1, 1)), 10000)

    def test_without_dated_wages_the_old_field_is_used(self):
        self.assertEqual(wages.wage_for(self.kim, SEPT), 9000)

    def test_pay_across_months_uses_each_months_wage(self):
        EmployeeWage.objects.create(user=self.kim, effective_from=SEPT, hourly_wage=10000)
        EmployeeWage.objects.create(user=self.kim, effective_from=NOV, hourly_wage=12000)
        work(self.kim, date(2026, 9, 30), 8)
        work(self.kim, date(2026, 11, 1), 2)
        self.assertEqual(wages.pay_for(self.kim, WorkHours.objects.filter(user=self.kim)), 8 * 10000 + 2 * 12000)

    def test_the_seed_migration_keeps_everyones_current_wage(self):
        joined = timezone.make_aware(datetime(2026, 3, 15, 9, 0))
        CustomUser.objects.filter(pk=self.kim.pk).update(date_joined=joined)
        boss = make_user('boss', is_admin=True)  # not an employee, no wage: left alone
        seed = import_module('hours_tracker.migrations.0008_seed_employee_wages').seed
        seed(apps, None)
        seed(apps, None)  # running it again adds nothing
        wage = EmployeeWage.objects.get(user=self.kim)
        self.assertEqual((wage.effective_from, wage.hourly_wage), (date(2026, 3, 1), 9000))
        self.assertFalse(EmployeeWage.objects.filter(user=boss).exists())

    def test_both_languages_have_the_same_keys_and_placeholders(self):
        en, ko = wages.STRINGS['en'], wages.STRINGS['ko']
        self.assertEqual(set(en), set(ko))
        fields = lambda text: sorted(name for _, name, _, _ in Formatter().parse(text) if name)
        for key in en:
            with self.subTest(key=key):
                self.assertEqual(fields(en[key]), fields(ko[key]))


class PayUsesTheMonthsWageTests(TestCase):
    """Kim: ₩10,000 from September, ₩12,000 from November; 10 hours in each of Sept and Nov."""

    def setUp(self):
        self.boss = make_user('boss', is_superuser=True, is_admin=True)
        self.kim = make_user('kim', is_employee=True, hourly_wage=10000)
        EmployeeWage.objects.create(user=self.kim, effective_from=SEPT, hourly_wage=10000)
        EmployeeWage.objects.create(user=self.kim, effective_from=NOV, hourly_wage=12000)
        work(self.kim, date(2026, 9, 3), 10)
        work(self.kim, date(2026, 11, 3), 10)
        self.client.force_login(self.boss)

    def test_payslips(self):
        for month, gross in ((9, 100000), (11, 120000)):
            with self.subTest(month=month):
                response = self.client.get(reverse('payslip', args=[self.kim.pk]), {'year': 2026, 'month': month})
                self.assertEqual(response.context['gross'], gross)

    def test_the_employees_calendar(self):
        response = self.client.get(reverse('employee_calendar', args=[self.kim.pk]), {'year': 2026, 'month': 11})
        self.assertEqual(response.context['hourly_wage'], 12000)
        self.assertEqual(response.context['total_salary'], 120000)
        self.assertContains(response, '₩12000')

    def test_their_own_calendar(self):
        self.client.force_login(self.kim)
        response = self.client.get(reverse('calendar'), {'year': 2026, 'month': 9})
        self.assertEqual(response.context['total_salary'], 100000)
        self.assertContains(response, '₩10000')

    def test_the_dashboard_month_and_all_time(self):
        november = self.client.post(reverse('superuser_dashboard'), {'year': 2026, 'month': 11, 'view_type': 'monthly'})
        self.assertEqual(november.context['total_salary'], 120000)
        all_time = self.client.post(reverse('superuser_dashboard'), {'year': 2026, 'month': 11, 'view_type': 'all_time'})
        self.assertEqual(all_time.context['total_salary'], 220000)

    def test_the_paper_view(self):
        response = self.client.get(reverse('paper_view'), {'year': 2026, 'month': 9})
        self.assertEqual(response.context['total_salary'], 100000)


class EmployeeEditTests(TestCase):
    def setUp(self):
        self.boss = make_user('boss', is_admin=True)
        self.kim = make_user('@email', email='kim@example.com', first_name='Min', is_employee=True, hourly_wage=10000)
        EmployeeWage.objects.create(user=self.kim, effective_from=SEPT, hourly_wage=10000)
        self.url = reverse('employee_edit', args=[self.kim.pk])
        self.client.force_login(self.boss)

    def details(self, **changes):
        data = {
            'first_name': 'Min', 'last_name': 'Kim', 'email': 'kim@example.com', 'bank_name': 'Shinhan',
            'account_number': '110-123-456789', 'visa_type': 'E-9', 'is_employee': 'on',
        }
        data.update(changes)
        return self.client.post(self.url, {key: value for key, value in data.items() if value is not None})

    def test_a_manager_edits_the_details(self):
        self.assertRedirects(self.details(), self.url)
        self.kim.refresh_from_db()
        self.assertEqual((self.kim.last_name, self.kim.bank_name, self.kim.account_number, self.kim.visa_type),
                         ('Kim', 'Shinhan', '110-123-456789', 'E-9'))

    def test_the_login_follows_a_changed_email(self):
        self.details(email='minkim@example.com')
        self.kim.refresh_from_db()
        self.assertEqual((self.kim.email, self.kim.username), ('minkim@example.com', 'minkim@example.com'))

    def test_a_separate_username_is_left_alone(self):
        lee = make_user('lee', email='lee@example.com', is_employee=True)
        self.client.post(reverse('employee_edit', args=[lee.pk]), {'email': 'lee2@example.com', 'is_employee': 'on'})
        lee.refresh_from_db()
        self.assertEqual((lee.email, lee.username), ('lee2@example.com', 'lee'))

    def test_an_email_another_account_signs_in_with_is_refused(self):
        make_user('@email', email='taken@example.com')
        response = self.details(email='TAKEN@example.com')
        self.assertContains(response, S['err_email_taken'])
        self.kim.refresh_from_db()
        self.assertEqual(self.kim.email, 'kim@example.com')

    def test_you_cannot_remove_your_own_admin_rights(self):
        response = self.client.post(reverse('employee_edit', args=[self.boss.pk]), {'email': 'boss@example.com'})
        self.assertEqual(response.status_code, 302)
        self.boss.refresh_from_db()
        self.assertTrue(self.boss.is_admin)

    def test_only_a_superuser_edits_a_superuser(self):
        owner = make_user('owner', is_superuser=True)
        response = self.client.get(reverse('employee_edit', args=[owner.pk]))
        self.assertRedirects(response, reverse('manage_users'), fetch_redirect_response=False)

    def test_employees_cannot_edit(self):
        self.client.force_login(self.kim)
        self.assertRedirects(self.client.get(self.url), reverse('calendar'), fetch_redirect_response=False)

    def test_the_manage_users_page_links_here_and_shows_this_months_wage(self):
        EmployeeWage.objects.create(user=self.kim, effective_from=date(2020, 1, 1), hourly_wage=5000)
        page = self.client.get(reverse('manage_users'))
        self.assertContains(page, self.url)
        self.assertContains(page, '<td>10000</td>', html=False)


class WageEditTests(TestCase):
    def setUp(self):
        self.boss = make_user('boss', is_admin=True)
        self.kim = make_user('kim', is_employee=True, hourly_wage=10000)
        EmployeeWage.objects.create(user=self.kim, effective_from=SEPT, hourly_wage=10000)
        self.add_url = reverse('employee_wage_add', args=[self.kim.pk])
        self.edit_url = reverse('employee_edit', args=[self.kim.pk])
        self.client.force_login(self.boss)

    def test_a_raise_from_a_later_month(self):
        response = self.client.post(self.add_url, {'month': '2026-11', 'hourly_wage': '₩12,000'})
        self.assertRedirects(response, f'{self.edit_url}#wages', fetch_redirect_response=False)
        self.assertEqual(wages.wage_for(self.kim, NOV), 12000)
        self.assertEqual(wages.wage_for(self.kim, OCT), 10000)
        page = self.client.get(self.edit_url)
        self.assertContains(page, '₩12,000 / hour')
        self.assertContains(page, S['upcoming'])

    def test_saving_the_same_month_replaces_it(self):
        self.client.post(self.add_url, {'month': '2026-09', 'hourly_wage': '10030'})
        self.assertEqual(list(self.kim.wages.values_list('hourly_wage', flat=True)), [Decimal('10030.00')])

    def test_a_wage_below_the_minimum_is_saved_with_a_warning(self):
        Settings.objects.update_or_create(id=1, defaults={'minimum_wage': 10030})
        response = self.client.post(self.add_url, {'month': '2026-11', 'hourly_wage': '9000'}, follow=True)
        self.assertContains(response, S['below_minimum'].format(wage='9,000', minimum='10,030'))
        self.assertEqual(wages.wage_for(self.kim, NOV), 9000)

    def test_bad_input_is_refused(self):
        for data, message in (({'month': '2026-11', 'hourly_wage': '-5'}, S['err_wage']),
                              ({'month': '2026-11', 'hourly_wage': '10000.555'}, S['err_wage']),
                              ({'month': 'soon', 'hourly_wage': '10000'}, S['err_month'])):
            with self.subTest(data=data):
                response = self.client.post(self.add_url, data)
                self.assertContains(response, message)
        self.assertEqual(self.kim.wages.count(), 1)

    def test_deleting_a_wage_but_never_the_last_one(self):
        raise_ = EmployeeWage.objects.create(user=self.kim, effective_from=NOV, hourly_wage=12000)
        self.client.post(reverse('employee_wage_delete', args=[raise_.pk]))
        self.assertEqual(self.kim.wages.count(), 1)
        only = self.kim.wages.get()
        response = self.client.post(reverse('employee_wage_delete', args=[only.pk]), follow=True)
        self.assertContains(response, escape(S['wage_only_one']))
        self.assertTrue(EmployeeWage.objects.filter(pk=only.pk).exists())

    def test_registering_an_employee_records_their_first_wage(self):
        self.client.post(reverse('register_employee'), {
            'email': 'new@example.com', 'first_name': 'New', 'hourly_wage': '10030', 'is_employee': 'on',
        })
        new = CustomUser.objects.get(email='new@example.com')
        wage = new.wages.get()
        self.assertEqual((wage.effective_from, wage.hourly_wage), (wages.this_month(), Decimal('10030.00')))
