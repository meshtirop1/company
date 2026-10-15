"""Phase 5: payslips in each cutter's language, and the supervisor's help page."""
import uuid
from datetime import date
from urllib.parse import quote

from django.urls import reverse
from django.utils import timezone

from . import services
from .i18n import COUNTED, STRINGS, counted
from .models import CutRecord, Cutter
from .test_entry import EntryTestCase
from .tests import make_user, message_texts

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


class WordingTests(EntryTestCase):
    def test_one_is_singular_in_english_and_the_same_in_korean(self):
        self.assertEqual(counted(EN, 'batch_saved', 1), EN['batch_saved_one'])
        self.assertEqual(counted(EN, 'batch_saved', 2), EN['batch_saved'])
        for key in COUNTED:
            self.assertIn(f'{key}_one', EN, key)
            self.assertEqual(KO[f'{key}_one'], KO[key], key)
        response = self.save_entry({self.kim: 3})
        self.assertIn(EN['batch_saved_one'].format(count=1, date='2026-10-10', total='12,000'), message_texts(response))
        services.save_batch(work_date=timezone.localdate(), entered_by=self.manager, token=uuid.uuid4(),
                            rows=[(self.kim, self.tongpo7, 1)])
        self.assertContains(self.client.get(reverse('cutting:hub')), '1 row · ₩4,000')
        js_text = self.client.get(reverse('cutting:entry')).context['js_text']
        self.assertEqual(js_text['summary_one'], EN['js_summary_one'])

    def test_a_mangled_form_token_comes_back_ready_to_save(self):
        data = self.entry_data({self.kim: 3})
        data['token'] = 'not-a-token'
        response = self.client.post(reverse('cutting:entry'), data)
        self.assertIn(EN['err_form_expired'], message_texts(response))
        self.assertNotContains(response, 'UUID')
        self.assertFalse(CutRecord.objects.exists())
        fresh = response.context['form'].data
        self.assertEqual(len(str(uuid.UUID(fresh['token']))), 36)
        self.client.post(reverse('cutting:entry'), fresh)
        self.assertEqual(CutRecord.objects.get().boxes, 3)

    def test_the_excel_file_is_named_in_the_page_language(self):
        url = reverse('cutting:month_export', args=[SEPT])
        self.assertIn('filename="fish-cutting-2026-09.xlsx"', self.client.get(url)['Content-Disposition'])
        self.use_korean()
        header = self.client.get(url)['Content-Disposition']
        self.assertIn("filename*=utf-8''", header)
        self.assertIn(quote('생선손질수당-2026-09.xlsx'), header)

    def test_display_order_errors_say_the_allowed_range(self):
        response = self.post('cutting:prices', data={'style': 'tongpo', 'size': '14', 'sort_order': 'abc',
                                                     'unit_price': '8000', 'effective_from': '2026-10-01'})
        self.assertContains(response, EN['err_order_range'])

    def test_each_rows_size_picker_is_labelled_with_the_cutter(self):
        self.assertContains(self.client.get(reverse('cutting:entry')), f'aria-label="Kim — {EN["change_row"]}"')


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
