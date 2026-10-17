from datetime import date

from django.test import Client, TestCase
from django.urls import reverse

from .models import CardExpense, CustomUser

PASSWORD = 'not-a-real-pass-123'


def make_user(username, first_name, **flags):
    return CustomUser.objects.create_user(username=username, email=f'{username}@example.com', password=PASSWORD,
                                          first_name=first_name, last_name='Test', **flags)


class CardExpenseAccessTests(TestCase):
    """Employees record and see only their own card expenses; only managers (Admin or
    superuser) get the employee list, to record for anyone."""

    def setUp(self):
        self.manager = make_user('boss', 'Boss', is_admin=True, is_employee=True)
        self.kim = make_user('kim', 'Kim', is_employee=True)
        self.lee = make_user('lee', 'Lee', is_employee=True)
        CardExpense.objects.create(user=self.lee, amount=55000, date=date(2026, 10, 3), description='Lee fuel')
        self.url = reverse('card_expenses')

    def as_user(self, user, lang='en'):
        self.client.force_login(user)
        session = self.client.session
        session['language'] = lang
        session.save()

    def test_an_employee_sees_no_employee_list_and_no_one_elses_expenses(self):
        for lang in ('en', 'ko'):
            with self.subTest(lang=lang):
                self.as_user(self.kim, lang)
                page = self.client.get(self.url)
                self.assertNotContains(page, 'name="user_id"')  # neither the form's list nor the filter
                self.assertNotContains(page, 'Lee Test')
                self.assertNotContains(page, 'Lee fuel')
                self.assertContains(page, 'Kim Test')
                self.assertEqual(page.context['is_manager'], False)

    def test_the_page_says_who_is_signed_in(self):
        self.as_user(self.kim)
        self.assertContains(self.client.get(self.url), 'you can record and see only your own expenses')
        self.as_user(self.kim, 'ko')
        self.assertContains(self.client.get(self.url), '본인의 지출만 기록하고 볼 수 있습니다')
        self.as_user(self.manager)
        self.assertContains(self.client.get(self.url), 'managers can record and see expenses for any employee')

    def test_the_menu_shows_who_is_signed_in(self):
        self.as_user(self.kim)
        page = self.client.get(reverse('calendar'))
        self.assertContains(page, 'nav-user')
        self.assertContains(page, 'Kim Test <span class="nav-role">Employee</span>', html=False)

    def test_an_employee_cannot_record_for_someone_else(self):
        self.as_user(self.kim)
        self.client.post(self.url, {'action': 'add', 'user_id': self.lee.pk, 'amount': '12000',
                                    'date': '2026-10-05', 'description': 'Lunch'})
        expense = CardExpense.objects.get(description='Lunch')
        self.assertEqual(expense.user, self.kim)

    def test_an_employee_cannot_delete_someone_elses_expense(self):
        self.as_user(self.kim)
        theirs = CardExpense.objects.get(user=self.lee)
        self.client.post(self.url, {'action': 'delete', 'expense_id': theirs.pk})
        self.assertTrue(CardExpense.objects.filter(pk=theirs.pk).exists())

    def test_a_manager_gets_the_employee_list_and_records_for_anyone(self):
        self.as_user(self.manager)
        page = self.client.get(self.url)
        self.assertContains(page, 'name="user_id"')
        self.assertContains(page, 'Lee Test')
        self.client.post(self.url, {'action': 'add', 'user_id': self.kim.pk, 'amount': '8000',
                                    'date': '2026-10-06', 'description': 'Tolls'})
        self.assertEqual(CardExpense.objects.get(description='Tolls').user, self.kim)


class StaleSignInTests(TestCase):
    """A sign-in form left open on a phone still signed in as someone else."""

    def setUp(self):
        for name in ('kim', 'lee'):
            CustomUser.objects.create_user(username=name, email=f'{name}@example.com', password=PASSWORD,
                                           is_employee=True)
        self.client = Client(enforce_csrf_checks=True)
        self.client.get(reverse('login'))
        stale = self.client.cookies['csrftoken'].value
        self.client.post(reverse('login'), {'username': 'kim', 'password': PASSWORD, 'csrfmiddlewaretoken': stale})
        self.stale = stale  # signing in gave the phone a new token, so this one is now stale

    def test_someone_else_signing_in_is_not_carried_on_as_the_previous_person(self):
        response = self.client.post(reverse('login'), {
            'username': 'lee', 'password': PASSWORD, 'csrfmiddlewaretoken': self.stale})
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, 'csrf_failure_en.html')

    def test_the_same_person_tapping_twice_still_goes_to_the_calendar(self):
        response = self.client.post(reverse('login'), {
            'username': 'KIM', 'password': PASSWORD, 'csrfmiddlewaretoken': self.stale})
        self.assertRedirects(response, reverse('calendar'), fetch_redirect_response=False)
