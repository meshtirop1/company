import re
import string
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from hours_tracker.models import CustomUser

from .i18n import STRINGS
from .models import Cutter, PriceItem, PriceRate
from .templatetags.cutting_tags import won

EN, KO = STRINGS['en'], STRINGS['ko']
SEED_FROM = date(2026, 1, 1)
RATE_SHEET = {  # as printed on the company's rate sheet, in sheet order
    'tongpo': [('7', 4000), ('8', 4500), ('9', 5000), ('10~11', 6500), ('12', 7000)],
    'tonghalbok': [('4,5,6', 2300), ('7,8', 2400), ('9', 2500), ('10~11', 3000), ('12', 3300), ('13', 3300)],
}


def make_user(username, **flags):
    return CustomUser.objects.create_user(
        username=username, email=f'{username}@example.com', password='not-a-real-pass-123', **flags,
    )


def message_texts(response):
    return [str(message) for message in response.context['messages']]


class ManagerTestCase(TestCase):
    """Signed in as a manager (is_admin), the supervisor role that does all data entry."""

    def setUp(self):
        self.manager = make_user('manager', is_admin=True)
        self.client.force_login(self.manager)

    def use_korean(self):
        session = self.client.session
        session['language'] = 'ko'
        session.save()

    def post(self, name, *args, data=None):
        return self.client.post(reverse(name, args=args), data or {}, follow=True)


# ─── Seeded price list ────────────────────────────────────────

class SeededPriceListTests(TestCase):
    def test_price_list_matches_the_rate_sheet(self):
        expected = sum(len(rows) for rows in RATE_SHEET.values())
        self.assertEqual(PriceItem.objects.count(), expected)
        for style, rows in RATE_SHEET.items():
            for size, price in rows:
                item = PriceItem.objects.get(style=style, size=size)
                rates = list(item.rates.all())
                self.assertEqual(len(rates), 1, item)
                self.assertEqual(rates[0].effective_from, SEED_FROM, item)
                self.assertEqual(rates[0].unit_price, price, item)

    def test_sheet_order_is_kept(self):
        for style, rows in RATE_SHEET.items():
            sizes = list(PriceItem.objects.filter(style=style).order_by('sort_order').values_list('size', flat=True))
            self.assertEqual(sizes, [size for size, _ in rows])

    def test_tongpo_pays_more_than_tonghalbok_at_every_shared_size(self):
        for size in ('9', '10~11', '12'):
            tongpo = PriceItem.objects.get(style='tongpo', size=size).rate_on(SEED_FROM)
            tonghalbok = PriceItem.objects.get(style='tonghalbok', size=size).rate_on(SEED_FROM)
            self.assertGreater(tongpo.unit_price, tonghalbok.unit_price, size)


# ─── Dated rates ──────────────────────────────────────────────

class RateLookupTests(TestCase):
    def setUp(self):
        self.item = PriceItem.objects.create(style='tongpo', size='99')
        PriceRate.objects.create(item=self.item, unit_price=4000, effective_from=date(2026, 1, 1))
        PriceRate.objects.create(item=self.item, unit_price=4500, effective_from=date(2026, 10, 20))

    def test_no_rate_before_the_first_start_date(self):
        self.assertIsNone(self.item.rate_on(date(2025, 12, 31)))

    def test_a_rate_applies_from_its_start_date(self):
        self.assertEqual(self.item.rate_on(date(2026, 1, 1)).unit_price, 4000)
        self.assertEqual(self.item.rate_on(date(2026, 10, 20)).unit_price, 4500)

    def test_the_old_rate_holds_until_the_new_one_starts(self):
        # A rise on the 20th must not reach back to work done on the 10th.
        self.assertEqual(self.item.rate_on(date(2026, 10, 10)).unit_price, 4000)
        self.assertEqual(self.item.rate_on(date(2026, 10, 19)).unit_price, 4000)
        self.assertEqual(self.item.rate_on(date(2030, 1, 1)).unit_price, 4500)

    def test_prefetched_rates_are_reused(self):
        item = PriceItem.objects.prefetch_related('rates').get(pk=self.item.pk)
        with self.assertNumQueries(0):
            self.assertEqual(item.rate_on(date(2026, 10, 10)).unit_price, 4000)


class ConstraintTests(TestCase):
    def test_one_rate_per_size_per_start_date(self):
        item = PriceItem.objects.get(style='tongpo', size='7')
        with transaction.atomic(), self.assertRaises(IntegrityError):
            PriceRate.objects.create(item=item, unit_price=9999, effective_from=SEED_FROM)

    def test_price_must_be_positive(self):
        item = PriceItem.objects.get(style='tongpo', size='7')
        with transaction.atomic(), self.assertRaises(IntegrityError):
            PriceRate.objects.create(item=item, unit_price=0, effective_from=date(2027, 1, 1))

    def test_cutter_names_are_unique_ignoring_case(self):
        Cutter.objects.create(name='Kim')
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Cutter.objects.create(name='kim')

    def test_one_line_per_style_and_size(self):
        with transaction.atomic(), self.assertRaises(IntegrityError):
            PriceItem.objects.create(style='tongpo', size='7')
        PriceItem.objects.create(style='tongpo', size='13')  # 13 exists only for 통할복


# ─── Access control ───────────────────────────────────────────

class AccessTests(TestCase):
    def setUp(self):
        self.cutter = Cutter.objects.create(name='Kim')
        self.item = PriceItem.objects.get(style='tongpo', size='7')
        self.rate = self.item.rates.get()

    def pages(self):
        return [
            reverse('cutting:hub'),
            reverse('cutting:cutters'),
            reverse('cutting:cutter_edit', args=[self.cutter.pk]),
            reverse('cutting:prices'),
            reverse('cutting:item_edit', args=[self.item.pk]),
            reverse('cutting:rate_add', args=[self.item.pk]),
            reverse('cutting:rate_edit', args=[self.rate.pk]),
        ]

    def actions(self):
        return [
            reverse('cutting:cutter_set_active', args=[self.cutter.pk]),
            reverse('cutting:cutter_delete', args=[self.cutter.pk]),
            reverse('cutting:item_set_active', args=[self.item.pk]),
            reverse('cutting:item_delete', args=[self.item.pk]),
            reverse('cutting:rate_delete', args=[self.rate.pk]),
        ]

    def test_anonymous_visitors_are_sent_to_login(self):
        for url in self.pages() + self.actions():
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response['Location'].startswith('/login/'), url)

    def test_employees_get_the_403_page(self):
        self.client.force_login(make_user('worker', is_employee=True))
        for url in self.pages():
            self.assertEqual(self.client.get(url).status_code, 403, url)
        for url in self.actions():
            self.assertEqual(self.client.post(url).status_code, 403, url)
        self.assertTrue(Cutter.objects.filter(pk=self.cutter.pk).exists())
        self.assertTrue(PriceItem.objects.filter(pk=self.item.pk).exists())

    def test_managers_and_superusers_can_open_every_page(self):
        for user in (make_user('boss', is_admin=True), make_user('root', is_superuser=True, is_staff=True)):
            self.client.force_login(user)
            for url in self.pages():
                self.assertEqual(self.client.get(url).status_code, 200, (user, url))

    def test_actions_only_accept_post(self):
        self.client.force_login(make_user('boss', is_admin=True))
        for url in self.actions():
            self.assertEqual(self.client.get(url).status_code, 405, url)

    def test_nav_link_is_shown_to_managers_only(self):
        hub_link = f'href="{reverse("cutting:hub")}"'
        self.client.force_login(make_user('boss', is_admin=True))
        self.assertContains(self.client.get(reverse('card_expenses')), hub_link)
        self.client.force_login(make_user('worker', is_employee=True))
        self.assertNotContains(self.client.get(reverse('card_expenses')), hub_link)


# ─── Cutters ──────────────────────────────────────────────────

class CutterTests(ManagerTestCase):
    def test_add_a_cutter(self):
        response = self.post('cutting:cutters', data={'name': 'Kim Min-su', 'note': 'Team A'})
        cutter = Cutter.objects.get()
        self.assertEqual((cutter.name, cutter.note, cutter.is_active), ('Kim Min-su', 'Team A', True))
        self.assertIn(EN['cutter_added'].format(name='Kim Min-su'), message_texts(response))

    def test_extra_spaces_in_names_are_tidied(self):
        self.post('cutting:cutters', data={'name': '  Kim    Min  '})
        self.assertEqual(Cutter.objects.get().name, 'Kim Min')

    def test_a_name_is_required(self):
        response = self.post('cutting:cutters', data={'name': '   '})
        self.assertContains(response, escape(EN['err_required']))
        self.assertFalse(Cutter.objects.exists())

    def test_duplicate_names_are_rejected_ignoring_case(self):
        Cutter.objects.create(name='Kim Min')
        response = self.post('cutting:cutters', data={'name': 'kim  min'})
        self.assertContains(response, escape(EN['err_duplicate_name']))
        self.assertEqual(Cutter.objects.count(), 1)

    def test_rename_a_cutter(self):
        cutter = Cutter.objects.create(name='Kim')
        self.post('cutting:cutter_edit', cutter.pk, data={'name': 'Kim (A)', 'note': ''})
        cutter.refresh_from_db()
        self.assertEqual(cutter.name, 'Kim (A)')

    def test_saving_without_changing_the_name_is_fine(self):
        cutter = Cutter.objects.create(name='Kim')
        self.post('cutting:cutter_edit', cutter.pk, data={'name': 'Kim', 'note': 'phone 010'})
        cutter.refresh_from_db()
        self.assertEqual(cutter.note, 'phone 010')

    def test_renaming_onto_another_cutter_is_rejected(self):
        Cutter.objects.create(name='Lee')
        cutter = Cutter.objects.create(name='Kim')
        response = self.post('cutting:cutter_edit', cutter.pk, data={'name': 'LEE', 'note': ''})
        self.assertContains(response, escape(EN['err_duplicate_name']))
        self.assertContains(response, escape(EN['edit_cutter'].format(name='Kim')))  # heading keeps the saved name
        cutter.refresh_from_db()
        self.assertEqual(cutter.name, 'Kim')

    def test_deactivate_and_activate_are_safe_to_repeat(self):
        cutter = Cutter.objects.create(name='Kim')
        for _ in range(2):  # a double tap must not flip it back
            self.post('cutting:cutter_set_active', cutter.pk, data={'active': '0'})
            cutter.refresh_from_db()
            self.assertFalse(cutter.is_active)
        self.post('cutting:cutter_set_active', cutter.pk, data={'active': '1'})
        cutter.refresh_from_db()
        self.assertTrue(cutter.is_active)

    def test_inactive_cutters_are_listed_separately(self):
        Cutter.objects.create(name='Kim', is_active=False)
        response = self.client.get(reverse('cutting:cutters'))
        self.assertEqual(list(response.context['active']), [])
        self.assertEqual([row['cutter'].name for row in response.context['inactive_rows']], ['Kim'])
        self.assertContains(response, EN['inactive_cutters'])

    def test_with_only_inactive_cutters_the_roster_points_to_reactivating(self):
        Cutter.objects.create(name='Kim', is_active=False)
        response = self.client.get(reverse('cutting:cutters'))
        self.assertContains(response, EN['roster_no_active'])
        self.assertNotContains(response, EN['no_cutters'])

    def test_delete_a_cutter(self):
        cutter = Cutter.objects.create(name='Kim', is_active=False)
        response = self.post('cutting:cutter_delete', cutter.pk)
        self.assertFalse(Cutter.objects.exists())
        self.assertIn(EN['cutter_deleted'].format(name='Kim'), message_texts(response))

    def test_korean_pages_and_messages(self):
        self.use_korean()
        response = self.post('cutting:cutters', data={'name': '김민수'})
        self.assertContains(response, 'lang="ko"')
        self.assertIn(KO['cutter_added'].format(name='김민수'), message_texts(response))
        response = self.post('cutting:cutters', data={'name': '김민수'})
        self.assertContains(response, escape(KO['err_duplicate_name']))


# ─── Price list ───────────────────────────────────────────────

class PriceListTests(ManagerTestCase):
    def add_size(self, **overrides):
        data = {
            'style': 'tongpo', 'size': '13', 'unit_price': '7500',
            'effective_from': timezone.localdate().isoformat(), 'sort_order': '',
        }
        data.update(overrides)
        return self.post('cutting:prices', data=data)

    def test_page_shows_every_seeded_rate(self):
        response = self.client.get(reverse('cutting:prices'))
        for rows in RATE_SHEET.values():
            for size, price in rows:
                self.assertContains(response, f'₩{price:,}')

    def test_add_a_size_with_its_first_rate(self):
        response = self.add_size(unit_price='7,500')
        item = PriceItem.objects.get(style='tongpo', size='13')
        rate = item.rates.get()
        self.assertEqual(item.sort_order, 60)  # after 통포 12 (sort order 50)
        self.assertEqual(rate.unit_price, 7500)
        self.assertEqual(rate.created_by, self.manager)
        self.assertIn(EN['item_added'].format(item='통포 13', price='7,500'), message_texts(response))

    def test_explicit_sort_order_is_used(self):
        self.add_size(sort_order='5')
        self.assertEqual(PriceItem.objects.get(style='tongpo', size='13').sort_order, 5)

    def test_price_accepts_commas_and_the_won_sign(self):
        self.add_size(unit_price='₩8,000')
        self.assertEqual(PriceItem.objects.get(style='tongpo', size='13').rates.get().unit_price, 8000)

    def test_price_accepts_what_a_korean_keyboard_types(self):
        # The ₩ key on a Korean PC keyboard types a backslash; an IME can give full-width forms.
        for typed, size in (('\\4,500', '13'), ('￦4500', '14'), ('4500원', '15'), ('４５００', '16')):
            with self.subTest(typed=typed):
                self.add_size(size=size, unit_price=typed)
                self.assertEqual(PriceItem.objects.get(style='tongpo', size=size).rates.get().unit_price, 4500)

    def test_field_errors_are_linked_for_screen_readers(self):
        response = self.add_size(unit_price='0')
        self.assertContains(response, 'aria-describedby="id_unit_price_error"')
        self.assertContains(response, 'id="id_unit_price_error"')

    def test_editing_a_size_keeps_the_display_order_in_range(self):
        item = PriceItem.objects.get(style='tongpo', size='12')
        response = self.post('cutting:item_edit', item.pk, data={'size': '12', 'sort_order': '40000'})
        self.assertContains(response, escape(EN['err_order_range']))
        item.refresh_from_db()
        self.assertEqual(item.sort_order, 50)

    def test_the_edit_hint_does_not_offer_leaving_the_order_blank(self):
        item = PriceItem.objects.get(style='tongpo', size='12')
        form = self.client.get(reverse('cutting:item_edit', args=[item.pk])).context['form']
        self.assertEqual(form.fields['sort_order'].help_text, EN['sort_order_help_edit'])

    def test_size_spacing_and_full_width_characters_are_normalized(self):
        response = self.add_size(size=' 10 ～ 11 ')  # 통포 10~11 is already on the sheet
        self.assertContains(response, escape(EN['err_duplicate_item'].format(item='통포 10~11')))
        self.assertEqual(PriceItem.objects.filter(style='tongpo', size='10~11').count(), 1)

    def test_invalid_prices_are_rejected(self):
        cases = [
            ('0', EN['err_price_min']), ('-5', EN['err_price_min']),
            ('12.5', EN['err_number']), ('abc', EN['err_number']), ('', EN['err_required']),
        ]
        for value, message in cases:
            with self.subTest(value=value):
                response = self.add_size(unit_price=value)
                self.assertContains(response, escape(message))
                self.assertFalse(PriceItem.objects.filter(style='tongpo', size='13').exists())

    def test_validation_messages_are_in_korean_on_korean_pages(self):
        self.use_korean()
        response = self.add_size(unit_price='0', effective_from='not-a-date')
        self.assertContains(response, escape(KO['err_price_min']))
        self.assertContains(response, escape(KO['err_date']))
        self.assertIn(KO['err_form'], message_texts(response))

    def test_add_a_new_rate_from_a_later_date(self):
        item = PriceItem.objects.get(style='tongpo', size='10~11')
        self.post('cutting:rate_add', item.pk, data={'unit_price': '7000', 'effective_from': '2026-10-20'})
        self.assertEqual(item.rate_on(date(2026, 10, 19)).unit_price, 6500)
        self.assertEqual(item.rate_on(date(2026, 10, 20)).unit_price, 7000)

    def test_a_second_rate_on_the_same_start_date_is_rejected(self):
        item = PriceItem.objects.get(style='tongpo', size='7')
        response = self.post('cutting:rate_add', item.pk, data={'unit_price': '9000', 'effective_from': '2026-01-01'})
        self.assertContains(response, escape(EN['err_duplicate_rate_date']))
        self.assertEqual(item.rates.count(), 1)

    def test_edit_a_rate(self):
        rate = PriceItem.objects.get(style='tongpo', size='10~11').rates.get()
        self.post('cutting:rate_edit', rate.pk, data={'unit_price': '6800', 'effective_from': '2026-01-01'})
        rate.refresh_from_db()
        self.assertEqual(rate.unit_price, 6800)

    def test_moving_a_rate_onto_another_rates_date_is_rejected(self):
        item = PriceItem.objects.get(style='tongpo', size='7')
        later = PriceRate.objects.create(item=item, unit_price=4200, effective_from=date(2026, 11, 1))
        response = self.post('cutting:rate_edit', later.pk, data={'unit_price': '4200', 'effective_from': '2026-01-01'})
        self.assertContains(response, escape(EN['err_duplicate_rate_date']))
        later.refresh_from_db()
        self.assertEqual(later.effective_from, date(2026, 11, 1))

    def test_the_only_rate_of_a_size_cannot_be_deleted(self):
        item = PriceItem.objects.get(style='tongpo', size='7')
        response = self.post('cutting:rate_delete', item.rates.get().pk)
        self.assertEqual(item.rates.count(), 1)
        self.assertIn(EN['rate_only_one'].format(item=item), message_texts(response))

    def test_delete_one_of_several_rates(self):
        item = PriceItem.objects.get(style='tongpo', size='7')
        later = PriceRate.objects.create(item=item, unit_price=4200, effective_from=date(2026, 11, 1))
        self.post('cutting:rate_delete', later.pk)
        self.assertEqual(list(item.rates.values_list('unit_price', flat=True)), [Decimal(4000)])

    def test_hide_and_show_a_size(self):
        item = PriceItem.objects.get(style='tongpo', size='7')
        self.post('cutting:item_set_active', item.pk, data={'active': '0'})
        item.refresh_from_db()
        self.assertFalse(item.is_active)
        self.post('cutting:item_set_active', item.pk, data={'active': '1'})
        item.refresh_from_db()
        self.assertTrue(item.is_active)

    def test_delete_a_size_and_its_rates(self):
        item = PriceItem.objects.get(style='tongpo', size='7')
        self.post('cutting:item_delete', item.pk)
        self.assertFalse(PriceItem.objects.filter(pk=item.pk).exists())
        self.assertFalse(PriceRate.objects.filter(item_id=item.pk).exists())

    def test_rename_a_size(self):
        item = PriceItem.objects.get(style='tongpo', size='12')
        self.post('cutting:item_edit', item.pk, data={'size': '12~13', 'sort_order': '50'})
        item.refresh_from_db()
        self.assertEqual(item.size, '12~13')

    def test_renaming_onto_a_size_in_the_same_style_is_rejected(self):
        item = PriceItem.objects.get(style='tongpo', size='12')
        response = self.post('cutting:item_edit', item.pk, data={'size': '7', 'sort_order': '50'})
        self.assertContains(response, escape(EN['err_duplicate_item'].format(item='통포 7')))
        item.refresh_from_db()
        self.assertEqual(item.size, '12')

    def test_the_same_size_may_exist_in_the_other_style(self):
        item = PriceItem.objects.get(style='tongpo', size='12')
        self.post('cutting:item_edit', item.pk, data={'size': '13', 'sort_order': '50'})  # 통할복 13 exists
        item.refresh_from_db()
        self.assertEqual(item.size, '13')

    def test_upcoming_rates_are_announced(self):
        item = PriceItem.objects.get(style='tongpo', size='7')
        start = timezone.localdate() + timedelta(days=5)
        PriceRate.objects.create(item=item, unit_price=9999, effective_from=start)
        response = self.client.get(reverse('cutting:prices'))
        self.assertContains(response, EN['upcoming_rate'].format(date=start.isoformat(), price='9,999'))

    def test_a_size_with_no_rate_in_force_today_is_flagged(self):
        item = PriceItem.objects.create(style='tongpo', size='14')
        PriceRate.objects.create(item=item, unit_price=8000, effective_from=timezone.localdate() + timedelta(days=1))
        response = self.client.get(reverse('cutting:prices'))
        self.assertContains(response, EN['no_current_rate'])


# ─── Translations and assets ─────────────────────────────────

def placeholders(text):
    named = {field for _, field, _, _ in string.Formatter().parse(text) if field}
    return named | set(re.findall(r'%\((\w+)\)', text))


class TranslationTests(ManagerTestCase):
    def test_both_languages_have_the_same_strings(self):
        self.assertEqual(set(EN), set(KO))

    def test_placeholders_match_in_both_languages(self):
        for key in EN:
            self.assertEqual(placeholders(EN[key]), placeholders(KO[key]), key)

    def test_every_string_is_translated(self):
        untranslated = [key for key in EN if EN[key] == KO[key]]
        self.assertEqual(untranslated, [])

    def test_every_page_renders_in_korean(self):
        item = PriceItem.objects.get(style='tongpo', size='7')
        cutter = Cutter.objects.create(name='김민수')
        self.use_korean()
        pages = {
            reverse('cutting:hub'): KO['module'],
            reverse('cutting:cutters'): KO['cutters_title'],
            reverse('cutting:cutter_edit', args=[cutter.pk]): KO['edit_cutter'].format(name='김민수'),
            reverse('cutting:prices'): KO['prices_title'],
            reverse('cutting:item_edit', args=[item.pk]): KO['edit_item'].format(item=item),
            reverse('cutting:rate_add', args=[item.pk]): KO['add_rate_title'].format(item=item),
            reverse('cutting:rate_edit', args=[item.rates.get().pk]): KO['edit_rate_title'].format(item=item),
        }
        for url, heading in pages.items():
            response = self.client.get(url)
            self.assertContains(response, 'lang="ko"', msg_prefix=url)
            self.assertContains(response, escape(heading), msg_prefix=url)


STATIC_TAG = re.compile(r"""\{%\s*static\s+['"]([^'"]+)['"]""")


class AssetTests(SimpleTestCase):
    def test_every_static_file_the_templates_use_exists(self):
        # Production uses a manifest storage: a {% static %} file that doesn't exist is a 500.
        templates = Path(settings.BASE_DIR, 'templates', 'cutting')
        used = {path for page in templates.glob('*.html') for path in STATIC_TAG.findall(page.read_text('utf-8'))}
        self.assertTrue({'css/cutting.css', 'js/cutting_entry.js'} <= used)
        for path in sorted(used):
            self.assertIsNotNone(finders.find(path), path)

    def test_won_filter(self):
        self.assertEqual(won(4500), '4,500')
        self.assertEqual(won(Decimal('3300')), '3,300')
        self.assertEqual(won(None), '')
