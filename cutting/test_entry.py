import uuid
from datetime import date, timedelta
from unittest import mock

from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from . import services
from .i18n import STRINGS
from .models import CutBatch, CutRecord, Cutter, PriceItem, PriceRate
from .tests import ManagerTestCase, make_user, message_texts

EN, KO = STRINGS['en'], STRINGS['ko']
WORK_DAY = date(2026, 10, 10)


def price_line(style, size):
    return PriceItem.objects.get(style=style, size=size)


class EntryTestCase(ManagerTestCase):
    """A small crew and three seeded sizes: 통포 7 (₩4,000), 통포 12 (₩7,000), 통할복 9 (₩2,500)."""

    def setUp(self):
        super().setUp()
        self.kim = Cutter.objects.create(name='Kim')
        self.lee = Cutter.objects.create(name='Lee')
        self.park = Cutter.objects.create(name='Park')
        self.tongpo7 = price_line('tongpo', '7')
        self.tongpo12 = price_line('tongpo', '12')
        self.halbok9 = price_line('tonghalbok', '9')

    def entry_data(self, rows, *, day=WORK_DAY, style='tongpo', item=None, token=None):
        """`rows` maps each ticked cutter to its boxes, or to (boxes, its own size)."""
        data = {
            'token': str(token or uuid.uuid4()),
            'work_date': day.isoformat(),
            'style': style,
            'item': str((item or self.tongpo7).pk),
        }
        for cutter, value in rows.items():
            boxes, own_item = value if isinstance(value, tuple) else (value, None)
            data[f'include_{cutter.pk}'] = 'on'
            data[f'boxes_{cutter.pk}'] = str(boxes)
            if own_item:
                data[f'item_{cutter.pk}'] = str(own_item.pk)
        return data

    def save_entry(self, rows, **kwargs):
        return self.client.post(reverse('cutting:entry'), self.entry_data(rows, **kwargs), follow=True)

    def record_of(self, cutter):
        return CutRecord.objects.get(cutter=cutter)


# ─── The entry screen ─────────────────────────────────────────

class EntryPageTests(EntryTestCase):
    def test_lists_every_active_cutter_but_not_inactive_ones(self):
        self.park.is_active = False
        self.park.save()
        response = self.client.get(reverse('cutting:entry'))
        self.assertEqual([row['cutter'].name for row in response.context['rows']], ['Kim', 'Lee'])

    def test_starts_on_today_with_the_first_size(self):
        form = self.client.get(reverse('cutting:entry')).context['form']
        self.assertEqual(form.initial['work_date'], timezone.localdate())
        self.assertEqual(form.initial['style'], 'tongpo')
        self.assertEqual(form.initial['item'], str(self.tongpo7.pk))

    def test_date_can_come_from_the_day_page_but_never_from_the_future(self):
        url = reverse('cutting:entry')
        self.assertEqual(self.client.get(url, {'date': '2026-10-01'}).context['form'].initial['work_date'],
                         date(2026, 10, 1))
        future = (timezone.localdate() + timedelta(days=3)).isoformat()
        self.assertEqual(self.client.get(url, {'date': future}).context['form'].initial['work_date'],
                         timezone.localdate())

    def test_explains_what_is_missing(self):
        Cutter.objects.update(is_active=False)
        self.assertContains(self.client.get(reverse('cutting:entry')), EN['no_active_cutters'])
        Cutter.objects.update(is_active=True)
        PriceItem.objects.update(is_active=False)
        self.assertContains(self.client.get(reverse('cutting:entry')), EN['no_active_items'])

    def test_page_carries_the_rates_for_the_live_preview(self):
        data = self.client.get(reverse('cutting:entry')).context['price_data']
        self.assertEqual(data[str(self.tongpo7.pk)], {'style': 'tongpo', 'rates': [['2026-01-01', 4000]]})

    def test_korean_page(self):
        self.use_korean()
        response = self.client.get(reverse('cutting:entry'))
        self.assertContains(response, 'lang="ko"')
        self.assertContains(response, KO['select_all'])


# ─── Saving a batch ───────────────────────────────────────────

class SaveBatchTests(EntryTestCase):
    def test_every_ticked_row_is_saved_with_its_price_snapshot(self):
        response = self.save_entry({self.kim: 10, self.lee: 5})
        batch = CutBatch.objects.get()
        self.assertEqual((batch.work_date, batch.entered_by), (WORK_DAY, self.manager))
        kim = self.record_of(self.kim)
        self.assertEqual((kim.style, kim.size, kim.boxes, kim.unit_price, kim.total), ('tongpo', '7', 10, 4000, 40000))
        self.assertEqual(self.record_of(self.lee).total, 20000)
        self.assertIn(EN['batch_saved'].format(count=2, date='2026-10-10', total='60,000'), message_texts(response))
        self.assertEqual(response.redirect_chain[-1][0], reverse('cutting:day', args=[WORK_DAY]))

    def test_unticked_rows_are_ignored_even_with_boxes_typed(self):
        data = self.entry_data({self.kim: 10})
        data[f'boxes_{self.lee.pk}'] = '7'  # typed, then unticked: not working today
        self.client.post(reverse('cutting:entry'), data)
        self.assertEqual(list(CutRecord.objects.values_list('cutter__name', flat=True)), ['Kim'])

    def test_a_row_can_use_its_own_style_and_size(self):
        self.save_entry({self.kim: 10, self.lee: (4, self.halbok9)})
        lee = self.record_of(self.lee)
        self.assertEqual((lee.style, lee.size, lee.unit_price, lee.total), ('tonghalbok', '9', 2500, 10000))
        self.assertEqual(self.record_of(self.kim).unit_price, 4000)

    def test_the_rate_in_force_on_the_work_date_is_used(self):
        rise = timezone.localdate() - timedelta(days=1)  # relative to today: work can't be entered for the future
        PriceRate.objects.create(item=self.tongpo7, unit_price=4500, effective_from=rise)
        self.save_entry({self.kim: 1}, day=rise - timedelta(days=10))
        self.save_entry({self.lee: 1}, day=rise)
        self.assertEqual(self.record_of(self.kim).unit_price, 4000)  # a rise doesn't reach back to earlier work
        self.assertEqual(self.record_of(self.lee).unit_price, 4500)

    def test_saved_pay_does_not_follow_later_price_list_changes(self):
        self.save_entry({self.kim: 10})
        self.tongpo7.rates.update(unit_price=9999)
        record = self.record_of(self.kim)
        self.assertEqual((record.unit_price, record.total), (4000, 40000))

    def test_one_bad_row_means_nothing_is_saved(self):
        response = self.save_entry({self.kim: 10, self.lee: 'abc'})
        self.assertFalse(CutBatch.objects.exists())
        self.assertFalse(CutRecord.objects.exists())
        self.assertIn(EN['err_batch_rows'], message_texts(response))
        self.assertContains(response, escape(EN['err_boxes_range']))

    def test_a_ticked_row_needs_its_boxes(self):
        response = self.save_entry({self.kim: 10, self.lee: ''})
        self.assertContains(response, escape(EN['err_boxes_required']))
        self.assertFalse(CutRecord.objects.exists())

    def test_box_counts_must_be_whole_numbers_from_1_to_9999(self):
        for boxes in ('0', '-3', '10000', '2.5'):
            with self.subTest(boxes=boxes):
                response = self.save_entry({self.kim: boxes})
                self.assertContains(response, escape(EN['err_boxes_range']))
        self.assertFalse(CutRecord.objects.exists())

    def test_at_least_one_cutter_must_be_ticked(self):
        response = self.save_entry({})
        self.assertContains(response, escape(EN['err_no_rows']))
        self.assertFalse(CutBatch.objects.exists())

    def test_future_dates_are_refused(self):
        response = self.save_entry({self.kim: 1}, day=timezone.localdate() + timedelta(days=1))
        self.assertContains(response, escape(EN['err_future_date']))
        self.assertFalse(CutRecord.objects.exists())

    def test_a_size_without_a_rate_on_the_work_date_is_refused(self):
        later = PriceItem.objects.create(style='tongpo', size='14', sort_order=60)
        PriceRate.objects.create(item=later, unit_price=8000, effective_from=date(2026, 11, 1))
        response = self.save_entry({self.kim: 3}, item=later)
        self.assertContains(response, escape(EN['err_no_rate'].format(item=later, date='2026-10-10')))
        self.assertFalse(CutRecord.objects.exists())

    def test_the_size_must_belong_to_the_chosen_style(self):
        response = self.save_entry({self.kim: 3}, style='tonghalbok', item=self.tongpo7)
        self.assertContains(response, escape(EN['err_style_mismatch']))
        self.assertFalse(CutRecord.objects.exists())

    def test_hidden_sizes_cannot_be_used(self):
        self.halbok9.is_active = False
        self.halbok9.save()
        response = self.save_entry({self.kim: 3, self.lee: (2, self.halbok9)})
        self.assertContains(response, escape(EN['err_choice']))
        self.assertFalse(CutRecord.objects.exists())

    def test_a_cutter_deactivated_while_the_form_was_open_is_refused(self):
        data = self.entry_data({self.kim: 3, self.lee: 2})
        Cutter.objects.filter(pk=self.lee.pk).update(is_active=False)
        response = self.client.post(reverse('cutting:entry'), data, follow=True)
        self.assertContains(response, escape(EN['err_cutter_inactive'].format(name='Lee')))
        self.assertFalse(CutRecord.objects.exists())

    def test_a_double_tap_saves_once(self):
        token = uuid.uuid4()
        self.save_entry({self.kim: 10}, token=token)
        response = self.save_entry({self.kim: 10}, token=token)
        self.assertEqual(CutBatch.objects.count(), 1)
        self.assertEqual(CutRecord.objects.count(), 1)
        self.assertIn(EN['batch_already_saved'], message_texts(response))

    def test_a_simultaneous_second_save_is_caught_by_the_database(self):
        token = uuid.uuid4()
        first = services.save_batch(work_date=WORK_DAY, rows=[(self.kim, self.tongpo7, 10)],
                                    entered_by=self.manager, token=token)  # saved by the other request
        with mock.patch('cutting.views.saved_batch', side_effect=[None, first]):  # the race window
            response = self.save_entry({self.kim: 10}, token=token)
        self.assertEqual(CutBatch.objects.count(), 1)
        self.assertEqual(CutRecord.objects.count(), 1)
        self.assertIn(EN['batch_already_saved'], message_texts(response))

    def spent_notice(self, batch):
        time = timezone.localtime(batch.created_at).strftime('%H:%M')
        return EN['err_token_spent'].format(date=batch.work_date.isoformat(), time=time)

    def test_new_rows_on_a_form_brought_back_with_back_are_kept_for_saving_not_dropped(self):
        token = uuid.uuid4()
        self.save_entry({self.kim: 10, self.lee: 8}, token=token)  # the morning batch
        morning = CutBatch.objects.get()
        afternoon = {self.kim: 20, self.lee: (15, self.halbok9)}
        response = self.save_entry(afternoon, token=token)  # typed into the restored form
        self.assertEqual(CutBatch.objects.count(), 1)  # not filed without the supervisor seeing it...
        texts = message_texts(response)
        self.assertNotIn(EN['batch_already_saved'], texts)  # ...and no false "already saved"
        self.assertIn(self.spent_notice(morning), texts)
        form = response.context['form']
        fresh = form['token'].value()
        self.assertNotEqual(str(fresh), str(token))
        self.assertEqual(form[f'boxes_{self.kim.pk}'].value(), '20')  # what they typed is still there
        self.client.post(reverse('cutting:entry'), self.entry_data(afternoon, token=fresh))  # Save again
        self.assertEqual(CutBatch.objects.count(), 2)
        self.assertEqual(CutRecord.objects.get(cutter=self.lee, style='tonghalbok').total, 37500)  # 15 × ₩2,500

    def test_a_simultaneous_save_of_different_rows_is_not_called_a_double_tap(self):
        token = uuid.uuid4()
        first = services.save_batch(work_date=WORK_DAY, rows=[(self.kim, self.tongpo7, 10)],
                                    entered_by=self.manager, token=token)
        with mock.patch('cutting.views.saved_batch', side_effect=[None, first]):
            response = self.save_entry({self.kim: 3, self.lee: 4}, token=token)
        self.assertEqual(CutRecord.objects.count(), 1)
        self.assertIn(self.spent_notice(first), message_texts(response))

    def test_typos_in_unticked_rows_are_ignored(self):
        data = self.entry_data({self.kim: 5})
        data[f'boxes_{self.lee.pk}'] = '0'  # "didn't work"
        data[f'boxes_{self.park.pk}'] = 'abc'
        data[f'item_{self.park.pk}'] = '999999'
        self.client.post(reverse('cutting:entry'), data)
        self.assertEqual(list(CutRecord.objects.values_list('cutter__name', flat=True)), ['Kim'])

    def test_a_cutter_deleted_while_the_form_was_open_is_refused(self):
        data = self.entry_data({self.kim: 3, self.lee: 2})
        Cutter.objects.filter(pk=self.lee.pk).delete()
        response = self.client.post(reverse('cutting:entry'), data, follow=True)
        self.assertContains(response, escape(EN['err_cutter_gone']))
        self.assertFalse(CutRecord.objects.exists())

    def test_save_batch_is_all_or_nothing(self):
        unpriced = PriceItem.objects.create(style='tongpo', size='15', sort_order=70)
        rows = [(self.kim, self.tongpo7, 5), (self.lee, unpriced, 5)]
        with self.assertRaises(services.NoRate):
            services.save_batch(work_date=WORK_DAY, rows=rows, entered_by=self.manager, token=uuid.uuid4())
        self.assertFalse(CutBatch.objects.exists())
        self.assertFalse(CutRecord.objects.exists())

    def test_korean_validation_messages(self):
        self.use_korean()
        response = self.save_entry({self.kim: '0'})
        self.assertContains(response, escape(KO['err_boxes_range']))
        self.assertIn(KO['err_batch_rows'], message_texts(response))


# ─── The day page and corrections ─────────────────────────────

class DayPageTests(EntryTestCase):
    def setUp(self):
        super().setUp()
        self.batch = services.save_batch(
            work_date=WORK_DAY, entered_by=self.manager, token=uuid.uuid4(),
            rows=[(self.kim, self.tongpo7, 10), (self.lee, self.tongpo7, 5)],
        )

    def day_url(self, day=WORK_DAY):
        return reverse('cutting:day', args=[day])

    def test_lists_each_batch_with_its_rows_and_totals(self):
        response = self.client.get(self.day_url())
        self.assertContains(response, '₩40,000')
        self.assertContains(response, '₩20,000')
        self.assertEqual(response.context['day_total'], 60000)

    def test_an_empty_day(self):
        self.assertContains(self.client.get(self.day_url(date(2026, 10, 11))), EN['no_entries'])

    def test_no_next_day_or_entry_button_beyond_today(self):
        today = self.client.get(reverse('cutting:day_today')).context
        self.assertIsNone(today['next_day'])
        self.assertTrue(today['can_enter'])
        future = self.client.get(self.day_url(timezone.localdate() + timedelta(days=2))).context
        self.assertFalse(future['can_enter'])

    def test_go_to_date_box(self):
        response = self.client.get(reverse('cutting:day_today'), {'date': '2026-10-10'})
        self.assertRedirects(response, self.day_url())

    def test_an_impossible_date_is_a_404(self):
        self.assertEqual(self.client.get('/cutting/day/2026-02-30/').status_code, 404)

    def test_changing_only_the_boxes_keeps_the_saved_rate(self):
        self.tongpo7.rates.update(unit_price=9999)
        record = self.record_of(self.kim)
        self.post('cutting:record_edit', record.pk, data={'item': str(self.tongpo7.pk), 'boxes': '12'})
        record.refresh_from_db()
        self.assertEqual((record.boxes, record.unit_price, record.total), (12, 4000, 48000))

    def test_moving_a_row_to_another_size_takes_that_rate_on_the_work_date(self):
        record = self.record_of(self.kim)
        self.post('cutting:record_edit', record.pk, data={'item': str(self.halbok9.pk), 'boxes': '10'})
        record.refresh_from_db()
        self.assertEqual((record.style, record.size, record.unit_price, record.total), ('tonghalbok', '9', 2500, 25000))

    def test_moving_a_row_to_a_size_with_no_rate_that_day_is_refused(self):
        later = PriceItem.objects.create(style='tongpo', size='14', sort_order=60)
        PriceRate.objects.create(item=later, unit_price=8000, effective_from=date(2026, 11, 1))
        record = self.record_of(self.kim)
        response = self.post('cutting:record_edit', record.pk, data={'item': str(later.pk), 'boxes': '10'})
        self.assertContains(response, escape(EN['err_no_rate'].format(item=later, date='2026-10-10')))
        record.refresh_from_db()
        self.assertEqual(record.item, self.tongpo7)

    def test_deleting_the_last_row_removes_the_batch(self):
        self.post('cutting:record_delete', self.record_of(self.kim).pk)
        self.assertTrue(CutBatch.objects.filter(pk=self.batch.pk).exists())
        self.post('cutting:record_delete', self.record_of(self.lee).pk)
        self.assertFalse(CutBatch.objects.filter(pk=self.batch.pk).exists())

    def test_delete_a_whole_batch(self):
        response = self.post('cutting:batch_delete', self.batch.pk)
        self.assertFalse(CutRecord.objects.exists())
        self.assertIn(EN['batch_deleted'].format(count=2), message_texts(response))

    def test_a_cutter_with_work_records_cannot_be_deleted(self):
        Cutter.objects.filter(pk=self.kim.pk).update(is_active=False)
        response = self.post('cutting:cutter_delete', self.kim.pk)
        self.assertTrue(Cutter.objects.filter(pk=self.kim.pk).exists())
        self.assertIn(EN['cutter_in_use'].format(name='Kim'), message_texts(response))

    def test_a_size_with_work_records_cannot_be_deleted(self):
        PriceItem.objects.filter(pk=self.tongpo7.pk).update(is_active=False)
        response = self.post('cutting:item_delete', self.tongpo7.pk)
        self.assertTrue(PriceItem.objects.filter(pk=self.tongpo7.pk).exists())
        self.assertTrue(self.tongpo7.rates.exists())
        self.assertIn(EN['item_in_use'].format(item=self.tongpo7), message_texts(response))

    def test_who_entered_a_batch_survives_their_account_being_deleted(self):
        supervisor = make_user('sup2', is_admin=True, first_name='Han', last_name='Mira')
        batch = services.save_batch(work_date=date(2026, 10, 9), entered_by=supervisor, token=uuid.uuid4(),
                                    rows=[(self.kim, self.tongpo7, 1)])
        supervisor.delete()
        batch.refresh_from_db()
        self.assertIsNone(batch.entered_by)
        self.assertEqual(batch.entered_by_name, 'Han Mira')
        self.assertContains(self.client.get(self.day_url(date(2026, 10, 9))), 'Han Mira')

    def test_the_admin_can_look_at_work_records_but_not_change_them(self):
        record = self.record_of(self.kim)
        self.client.force_login(make_user('root', is_superuser=True, is_staff=True))
        self.assertEqual(self.client.get(reverse('admin:cutting_cutrecord_changelist')).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:cutting_cutrecord_change', args=[record.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:cutting_cutbatch_change', args=[self.batch.pk])).status_code, 200)
        for url in (reverse('admin:cutting_cutrecord_add'), reverse('admin:cutting_cutbatch_add')):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        delete = reverse('admin:cutting_cutrecord_delete', args=[record.pk])
        self.assertEqual(self.client.post(delete, {'post': 'yes'}).status_code, 403)
        self.assertTrue(CutRecord.objects.filter(pk=record.pk).exists())

    def test_hub_shows_what_was_entered_today(self):
        services.save_batch(work_date=timezone.localdate(), entered_by=self.manager, token=uuid.uuid4(),
                            rows=[(self.kim, self.tongpo12, 3)])
        response = self.client.get(reverse('cutting:hub'))
        self.assertContains(response, EN['stat_today_value'].format(rows=1, total='21,000'))


class EntryAccessTests(EntryTestCase):
    def test_only_managers_can_enter_or_correct_work(self):
        batch = services.save_batch(work_date=WORK_DAY, entered_by=self.manager, token=uuid.uuid4(),
                                    rows=[(self.kim, self.tongpo7, 1)])
        record = batch.records.get()
        pages = [reverse('cutting:entry'), reverse('cutting:day_today'),
                 reverse('cutting:day', args=[WORK_DAY]), reverse('cutting:record_edit', args=[record.pk])]
        actions = [reverse('cutting:record_delete', args=[record.pk]), reverse('cutting:batch_delete', args=[batch.pk])]

        self.client.logout()
        for url in pages + actions:
            self.assertTrue(self.client.get(url)['Location'].startswith('/login/'), url)

        self.client.force_login(make_user('worker', is_employee=True))
        for url in pages:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        for url in actions:
            self.assertEqual(self.client.post(url).status_code, 403, url)
        self.assertEqual(self.client.post(reverse('cutting:entry'), self.entry_data({self.kim: 9})).status_code, 403)
        self.assertEqual(CutRecord.objects.count(), 1)
