"""Phase 5: payslips in each cutter's language, and the supervisor's help page."""
import uuid
from datetime import date

from django.urls import reverse

from . import services
from .i18n import STRINGS
from .models import Cutter
from .test_entry import EntryTestCase
from .tests import make_user

EN, KO = STRINGS['en'], STRINGS['ko']
SEPT = date(2026, 9, 1)


class PayslipLanguageTests(EntryTestCase):
    """Kim reads English, Lee reads Korean, Park has no preference (follows the screen)."""

    def setUp(self):
        super().setUp()
        Cutter.objects.filter(pk=self.kim.pk).update(payslip_language='en')
        Cutter.objects.filter(pk=self.lee.pk).update(payslip_language='ko')
        services.save_batch(work_date=date(2026, 9, 10), entered_by=self.manager, token=uuid.uuid4(),
                            rows=[(self.kim, self.tongpo7, 2), (self.lee, self.tongpo7, 3), (self.park, self.tongpo7, 4)])

    def slip(self, cutter, **params):
        return self.client.get(reverse('cutting:payslip', args=[SEPT, cutter.pk]), params)

    def test_a_slip_prints_in_its_cutters_language_whatever_the_screen(self):
        self.use_korean()
        kim = self.slip(self.kim)
        self.assertContains(kim, '<html lang="en">', html=False)
        self.assertContains(kim, EN['total_pay'])
        self.assertNotContains(kim, KO['total_pay'])
        lee = self.slip(self.lee)
        self.assertContains(lee, KO['total_pay'])

    def test_no_preference_follows_the_screen(self):
        self.assertContains(self.slip(self.park), EN['total_pay'])
        self.use_korean()
        self.assertContains(self.slip(self.park), KO['total_pay'])

    def test_printing_all_slips_gives_each_cutter_their_own_language(self):
        response = self.client.get(reverse('cutting:payslips', args=[SEPT]))
        self.assertEqual([(s['cutter'].name, s['lang']) for s in response.context['slips']],
                         [('Kim', 'en'), ('Lee', 'ko'), ('Park', 'en')])
        self.assertContains(response, '<div class="sheet" lang="ko">', count=1, html=False)
        self.assertContains(response, '<div class="sheet" lang="en">', count=2, html=False)
        self.assertContains(response, KO['subtotal'].format(style='통포'))
        self.assertContains(response, EN['subtotal'].format(style='통포'), count=2)

    def test_the_toolbar_can_print_every_slip_in_one_language(self):
        response = self.client.get(reverse('cutting:payslips', args=[SEPT]), {'slip_lang': 'ko'})
        self.assertEqual({s['lang'] for s in response.context['slips']}, {'ko'})
        self.assertContains(response, '<html lang="ko">', html=False)
        self.assertContains(response, 'href="?slip_lang=en"', html=False)
        nonsense = self.client.get(reverse('cutting:payslips', args=[SEPT]), {'slip_lang': 'fr'})
        self.assertEqual([s['lang'] for s in nonsense.context['slips']], ['en', 'ko', 'en'])

    def test_the_language_is_chosen_on_the_cutter_form(self):
        response = self.post('cutting:cutter_edit', self.park.pk, data={'name': 'Park', 'note': '', 'payslip_language': 'ko'})
        self.park.refresh_from_db()
        self.assertEqual(self.park.payslip_language, 'ko')
        self.assertContains(response, f"{EN['payslip_language']}: 한국어")
        self.post('cutting:cutters', data={'name': 'Nguyen', 'note': '', 'payslip_language': 'en'})
        self.assertEqual(Cutter.objects.get(name='Nguyen').payslip_language, 'en')
        self.post('cutting:cutters', data={'name': 'Choi', 'note': ''})
        self.assertEqual(Cutter.objects.get(name='Choi').payslip_language, '')
        self.post('cutting:cutters', data={'name': 'Bad', 'note': '', 'payslip_language': 'xx'})
        self.assertFalse(Cutter.objects.filter(name='Bad').exists())


class HelpPageTests(EntryTestCase):
    def test_help_in_both_languages(self):
        url = reverse('cutting:help')
        self.assertContains(self.client.get(reverse('cutting:hub')), url)
        page = self.client.get(url)
        for key in ('help_title', 'help_daily_1', 'help_fix_2', 'help_month_3', 'help_prices_2'):
            self.assertContains(page, EN[key].replace('"', '&quot;').replace("'", '&#x27;'), msg_prefix=key)
        self.use_korean()
        page = self.client.get(url)
        self.assertContains(page, 'lang="ko"')
        self.assertContains(page, KO['help_month_title'])

    def test_only_managers_see_help(self):
        self.client.force_login(make_user('worker', is_employee=True))
        self.assertEqual(self.client.get(reverse('cutting:help')).status_code, 403)
