"""Phase 4: locking a paid month, the change log, and re-pricing after a backdated price change."""
import uuid
from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from . import services
from .i18n import STRINGS
from .models import AuditAction, AuditEntry, CutBatch, CutRecord, MonthLock, PriceRate
from .reports import month_bounds
from .test_entry import EntryTestCase
from .tests import make_user, message_texts

EN, KO = STRINGS['en'], STRINGS['ko']
SEPT = date(2026, 9, 1)
DAY = date(2026, 9, 10)


def next_month_start():
    today = timezone.localdate()
    return (today.replace(day=28) + timedelta(days=4)).replace(day=1)


class LockTestCase(EntryTestCase):
    """September 2026: one entry on the 10th — Kim 통포 7 × 10 (₩40,000), Lee 통포 7 × 3 (₩12,000)."""

    def setUp(self):
        super().setUp()
        self.batch = services.save_batch(work_date=DAY, entered_by=self.manager, token=uuid.uuid4(),
                                         rows=[(self.kim, self.tongpo7, 10), (self.lee, self.tongpo7, 3)])
        self.kim_row = CutRecord.objects.get(cutter=self.kim)
        self.lee_row = CutRecord.objects.get(cutter=self.lee)

    def lock(self):
        return services.lock_month(SEPT, user=self.manager)

    def log(self, action):
        return list(AuditEntry.objects.filter(action=action).order_by('pk'))

    def september_total(self):
        return sum(record.total for record in CutRecord.objects.filter(work_date__month=9))


# ─── The lock, at the service layer ───────────────────────────

class MonthLockServiceTests(LockTestCase):
    def test_a_month_can_be_locked_from_its_last_day(self):
        self.assertFalse(services.can_lock(SEPT, today=date(2026, 9, 29)))
        self.assertTrue(services.can_lock(SEPT, today=date(2026, 9, 30)))
        self.assertTrue(services.can_lock(SEPT, today=date(2026, 10, 1)))
        with self.assertRaises(services.MonthNotOver):
            services.lock_month(SEPT, user=self.manager, today=date(2026, 9, 29))
        self.assertFalse(MonthLock.objects.exists())
        self.assertFalse(AuditEntry.objects.exists())

    def test_locking_twice_changes_nothing(self):
        first, second = self.lock(), self.lock()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(MonthLock.objects.count(), 1)
        self.assertEqual(len(self.log(AuditAction.LOCK)), 1)
        self.assertEqual(first.locked_by_name, 'manager')

    def test_a_locked_month_refuses_every_change(self):
        self.lock()
        attempts = {
            'save': lambda: services.save_batch(work_date=date(2026, 9, 20), entered_by=self.manager,
                                                token=uuid.uuid4(), rows=[(self.park, self.tongpo7, 1)]),
            'edit': lambda: services.update_record(self.kim_row, item=self.tongpo12, boxes=99, user=self.manager),
            'delete row': lambda: services.delete_record(self.kim_row, user=self.manager),
            'delete entry': lambda: services.delete_batch(self.batch, user=self.manager),
            'reprice': lambda: services.reprice_month(SEPT, user=self.manager),
        }
        for name, attempt in attempts.items():
            with self.subTest(name), self.assertRaises(services.MonthLocked):
                attempt()
        self.kim_row.refresh_from_db()
        self.assertEqual((self.kim_row.boxes, self.kim_row.total), (10, 40000))
        self.assertEqual(CutRecord.objects.count(), 2)
        self.assertEqual(CutBatch.objects.count(), 1)
        self.assertEqual(AuditEntry.objects.exclude(action=AuditAction.LOCK).count(), 0)

    def test_other_months_stay_open(self):
        self.lock()
        services.save_batch(work_date=date(2026, 10, 1), entered_by=self.manager, token=uuid.uuid4(),
                            rows=[(self.park, self.tongpo7, 1)])
        services.save_batch(work_date=date(2026, 8, 31), entered_by=self.manager, token=uuid.uuid4(),
                            rows=[(self.park, self.tongpo7, 1)])
        self.assertEqual(CutRecord.objects.filter(cutter=self.park).count(), 2)

    def test_unlocking_reopens_the_month_and_is_logged_with_its_reason(self):
        self.lock()
        self.assertTrue(services.unlock_month(SEPT, user=self.manager, reason='Kim was short one box'))
        self.assertFalse(MonthLock.objects.exists())
        [entry] = self.log(AuditAction.UNLOCK)
        self.assertEqual(entry.reason, 'Kim was short one box')
        self.assertEqual(entry.before['locked_by'], 'manager')
        self.assertEqual(entry.month, SEPT)
        services.update_record(self.kim_row, item=self.tongpo7, boxes=11, user=self.manager)
        self.assertEqual(self.kim_row.total, 44000)
        self.assertFalse(services.unlock_month(SEPT, user=self.manager, reason='again'))
        self.assertEqual(len(self.log(AuditAction.UNLOCK)), 1)


# ─── The change log, at the service layer ─────────────────────

class ChangeLogServiceTests(LockTestCase):
    def test_a_correction_is_logged_with_before_and_after(self):
        services.update_record(self.kim_row, item=self.tongpo7, boxes=12, user=self.manager, reason='recount')
        [entry] = self.log(AuditAction.EDIT)
        self.assertEqual(entry.before, {'style': 'tongpo', 'size': '7', 'boxes': 10, 'unit_price': 4000, 'total': 40000})
        self.assertEqual(entry.after, {'style': 'tongpo', 'size': '7', 'boxes': 12, 'unit_price': 4000, 'total': 48000})
        self.assertEqual((entry.cutter_name, entry.work_date, entry.month), ('Kim', DAY, SEPT))
        self.assertEqual((entry.record_id, entry.batch_id), (self.kim_row.pk, self.batch.pk))
        self.assertEqual((entry.reason, entry.user_name), ('recount', 'manager'))

    def test_saving_a_row_unchanged_writes_nothing(self):
        services.update_record(self.kim_row, item=self.tongpo7, boxes=10, user=self.manager)
        self.assertFalse(AuditEntry.objects.exists())

    def test_a_deleted_row_is_kept_in_the_log(self):
        services.delete_record(self.lee_row, user=self.manager)
        [entry] = self.log(AuditAction.DELETE_RECORD)
        self.assertEqual(entry.cutter_name, 'Lee')
        self.assertEqual(entry.before['total'], 12000)
        self.assertEqual(entry.before['entered_by'], 'manager')
        self.assertRegex(entry.before['saved_at'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}')
        self.assertFalse(CutRecord.objects.filter(pk=self.lee_row.pk).exists())

    def test_deleting_a_whole_entry_logs_every_row(self):
        batch_pk = self.batch.pk  # Django clears .pk on delete
        services.delete_batch(self.batch, user=self.manager)
        entries = self.log(AuditAction.DELETE_BATCH)
        self.assertEqual(sorted(e.cutter_name for e in entries), ['Kim', 'Lee'])
        self.assertEqual({e.batch_id for e in entries}, {batch_pk})
        self.assertFalse(CutBatch.objects.exists())

    def test_the_log_outlives_the_supervisors_account(self):
        supervisor = make_user('sup2', is_admin=True, first_name='Han', last_name='Mira')
        services.delete_record(self.lee_row, user=supervisor)
        supervisor.delete()
        [entry] = self.log(AuditAction.DELETE_RECORD)
        self.assertIsNone(entry.user)
        self.assertEqual(entry.user_name, 'Han Mira')


# ─── Re-pricing ───────────────────────────────────────────────

class RepriceTests(LockTestCase):
    def backdate(self, price=4200, start=SEPT):
        return PriceRate.objects.create(item=self.tongpo7, unit_price=price, effective_from=start)

    def test_a_backdated_rate_leaves_saved_work_alone_until_re_priced(self):
        self.backdate()
        self.kim_row.refresh_from_db()
        self.assertEqual(self.kim_row.unit_price, 4000)  # snapshots never move on their own
        stale = services.stale_records(SEPT)
        self.assertEqual([(record.pk, price) for record, price in stale],
                         [(self.kim_row.pk, 4200), (self.lee_row.pk, 4200)])

        changed, delta = services.reprice_month(SEPT, user=self.manager)
        self.assertEqual((changed, delta), (2, 2600))  # 13 boxes × ₩200
        self.kim_row.refresh_from_db()
        self.assertEqual((self.kim_row.unit_price, self.kim_row.total), (4200, 42000))
        self.assertEqual(self.september_total(), 54600)
        entries = self.log(AuditAction.REPRICE)
        self.assertEqual([(e.before['unit_price'], e.after['unit_price']) for e in entries], [(4000, 4200)] * 2)
        self.assertEqual(services.stale_records(SEPT), [])

    def test_a_rate_starting_after_the_work_does_not_touch_it(self):
        self.backdate(start=date(2026, 9, 11))
        self.assertEqual(services.stale_records(SEPT), [])

    def test_work_with_no_rate_left_is_listed_but_left_as_saved(self):
        PriceRate.objects.filter(item=self.tongpo7).delete()
        self.backdate(start=date(2026, 9, 15))  # the only rate now starts after the work
        stale = services.stale_records(SEPT)
        self.assertEqual({price for _, price in stale}, {None})
        self.assertEqual(services.reprice_month(SEPT, user=self.manager), (0, 0))
        self.kim_row.refresh_from_db()
        self.assertEqual(self.kim_row.unit_price, 4000)

    def test_a_plan_that_changed_after_review_is_refused(self):
        self.backdate()
        token = services.plan_token(services.repriceable(SEPT))
        PriceRate.objects.filter(item=self.tongpo7, effective_from=SEPT).update(unit_price=4300)
        with self.assertRaises(services.PlanChanged):
            services.reprice_month(SEPT, user=self.manager, expected=token)
        self.kim_row.refresh_from_db()
        self.assertEqual(self.kim_row.unit_price, 4000)
        self.assertFalse(AuditEntry.objects.exists())

    def test_the_review_page_and_applying_it(self):
        self.backdate()
        url = reverse('cutting:reprice', args=[SEPT])
        page = self.client.get(url)
        self.assertEqual(page.context['fixable'], 2)
        self.assertContains(page, '+₩2,000')  # Kim: 10 boxes × ₩200
        self.assertContains(page, escape(EN['reprice_total_change'].format(delta='+₩2,600')))
        response = self.client.post(url, {'plan': page.context['plan_token']}, follow=True)
        self.assertIn(EN['reprice_done'].format(count=2, delta='+₩2,600'), message_texts(response))
        self.assertEqual(self.september_total(), 54600)

    def test_applying_an_out_of_date_review_changes_nothing(self):
        self.backdate()
        response = self.client.post(reverse('cutting:reprice', args=[SEPT]), {'plan': 'not-what-was-shown'}, follow=True)
        self.assertIn(EN['reprice_changed'], message_texts(response))
        self.assertEqual(self.september_total(), 52000)

    def test_the_month_page_points_to_re_pricing(self):
        month_url = reverse('cutting:month', args=[SEPT])
        self.assertNotContains(self.client.get(month_url), reverse('cutting:reprice', args=[SEPT]))
        self.backdate()
        response = self.client.get(month_url)
        self.assertContains(response, escape(EN['stale_notice'].format(count=2)))
        self.assertContains(response, reverse('cutting:reprice', args=[SEPT]))

    def test_a_locked_month_cannot_be_re_priced(self):
        self.backdate()
        self.lock()
        response = self.client.get(reverse('cutting:reprice', args=[SEPT]), follow=True)
        self.assertIn(EN['err_month_locked'].format(month='2026-09'), message_texts(response))
        self.assertNotContains(self.client.get(reverse('cutting:month', args=[SEPT])), EN['stale_review'])
        self.client.post(reverse('cutting:reprice', args=[SEPT]), {'plan': 'x'})
        self.assertEqual(self.september_total(), 52000)

    def test_signed_amounts(self):
        from .templatetags.cutting_tags import signed_won
        self.assertEqual((signed_won(2600), signed_won(-3000), signed_won(0)), ('+₩2,600', '−₩3,000', '+₩0'))


# ─── The pages ────────────────────────────────────────────────

class LockPageTests(LockTestCase):
    def month_url(self, month=SEPT):
        return reverse('cutting:month', args=[month])

    def test_lock_from_the_month_page(self):
        page = self.client.get(self.month_url())
        self.assertContains(page, EN['lock_month'])
        self.assertContains(page, reverse('cutting:month_lock', args=[SEPT]))
        response = self.client.post(reverse('cutting:month_lock', args=[SEPT]), follow=True)
        self.assertIn(EN['month_locked_done'].format(month='2026-09'), message_texts(response))
        self.assertTrue(MonthLock.objects.filter(month=SEPT).exists())
        self.assertContains(response, 'class="cut-locked"')
        self.assertContains(response, reverse('cutting:month_unlock', args=[SEPT]))
        self.assertNotContains(response, reverse('cutting:month_lock', args=[SEPT]))

    def test_a_month_that_is_not_over_cannot_be_locked(self):
        upcoming = next_month_start()
        last_day = month_bounds(upcoming)[1].isoformat()
        page = self.client.get(self.month_url(upcoming))
        self.assertNotContains(page, reverse('cutting:month_lock', args=[upcoming]))
        self.assertContains(page, escape(EN['lock_not_yet'].format(date=last_day)))
        response = self.client.post(reverse('cutting:month_lock', args=[upcoming]), follow=True)
        self.assertFalse(MonthLock.objects.exists())
        self.assertIn(EN['err_lock_early'].format(month=f'{upcoming:%Y-%m}', date=last_day), message_texts(response))

    def test_the_day_page_of_a_locked_month_offers_no_changes(self):
        day_url = reverse('cutting:day', args=[DAY])
        self.assertContains(self.client.get(day_url), reverse('cutting:record_edit', args=[self.kim_row.pk]))
        self.lock()
        page = self.client.get(day_url)
        self.assertContains(page, 'class="cut-locked"')
        for url in (reverse('cutting:record_edit', args=[self.kim_row.pk]),
                    reverse('cutting:record_delete', args=[self.kim_row.pk]),
                    reverse('cutting:batch_delete', args=[self.batch.pk]),
                    reverse('cutting:entry')):
            self.assertNotContains(page, url)
        self.assertContains(page, '₩52,000')  # the work itself is still shown

    def test_changes_posted_to_a_locked_month_are_refused(self):
        self.lock()
        refused = EN['err_month_locked'].format(month='2026-09')
        responses = [
            self.post('cutting:record_delete', self.kim_row.pk),
            self.post('cutting:batch_delete', self.batch.pk),
            self.post('cutting:record_edit', self.kim_row.pk, data={'item': self.tongpo7.pk, 'boxes': 1}),
            self.client.get(reverse('cutting:record_edit', args=[self.kim_row.pk]), follow=True),
        ]
        for response in responses:
            self.assertIn(refused, message_texts(response))
            self.assertEqual(response.redirect_chain[-1][0], reverse('cutting:day', args=[DAY]))
        self.assertEqual(CutRecord.objects.count(), 2)
        self.kim_row.refresh_from_db()
        self.assertEqual(self.kim_row.boxes, 10)

    def test_new_work_for_a_locked_month_is_refused_with_nothing_saved(self):
        self.lock()
        response = self.save_entry({self.park: 5}, day=date(2026, 9, 20))
        self.assertContains(response, escape(EN['err_month_locked'].format(month='2026-09')))
        self.assertFalse(CutRecord.objects.filter(cutter=self.park).exists())

    def test_unlocking_needs_a_reason(self):
        self.lock()
        unlock = reverse('cutting:month_unlock', args=[SEPT])
        response = self.client.post(unlock, {'reason': '   '}, follow=True)
        self.assertIn(EN['err_unlock_reason'], message_texts(response))
        self.assertTrue(MonthLock.objects.exists())
        response = self.client.post(unlock, {'reason': 'Lee was paid twice'}, follow=True)
        self.assertIn(EN['month_unlocked'].format(month='2026-09'), message_texts(response))
        self.assertFalse(MonthLock.objects.exists())
        self.assertEqual(AuditEntry.objects.get(action=AuditAction.UNLOCK).reason, 'Lee was paid twice')

    def test_cutter_page_and_korean_month_page_show_the_lock(self):
        self.lock()
        self.assertContains(self.client.get(reverse('cutting:cutter_month', args=[SEPT, self.kim.pk])),
                            'class="cut-locked"')
        self.use_korean()
        page = self.client.get(self.month_url())
        self.assertContains(page, '정산 잠김')
        self.assertContains(page, KO['unlock_month'])


class ChangeLogPageTests(LockTestCase):
    def test_corrections_made_on_the_pages_are_logged_with_their_reason(self):
        self.post('cutting:record_edit', self.kim_row.pk,
                  data={'item': self.tongpo7.pk, 'boxes': 12, 'reason': 'recount at the end of the day'})
        self.post('cutting:record_delete', self.lee_row.pk)
        page = self.client.get(reverse('cutting:audit'))
        self.assertContains(page, EN['action_edit'])
        self.assertContains(page, EN['action_delete_record'])
        self.assertContains(page, '<del>통포 7 · 10 × ₩4,000 = ₩40,000</del>', html=True)
        self.assertContains(page, '<ins>통포 7 · 12 × ₩4,000 = ₩48,000</ins>', html=True)
        self.assertContains(page, 'recount at the end of the day')
        self.assertContains(page, 'entered by manager at ')  # who first entered the deleted row

    def test_price_changes_are_logged(self):
        self.post('cutting:rate_add', self.tongpo7.pk, data={'unit_price': '4,500', 'effective_from': '2026-11-01'})
        rate = PriceRate.objects.get(item=self.tongpo7, effective_from=date(2026, 11, 1))
        self.post('cutting:rate_edit', rate.pk, data={'unit_price': '4600', 'effective_from': '2026-11-01'})
        self.post('cutting:rate_edit', rate.pk, data={'unit_price': '4600', 'effective_from': '2026-11-01'})  # no change
        self.post('cutting:rate_delete', rate.pk)
        self.post('cutting:prices', data={'style': 'tongpo', 'size': '14', 'unit_price': '8000',
                                          'effective_from': '2026-10-01'})
        actions = list(AuditEntry.objects.order_by('pk').values_list('action', flat=True))
        self.assertEqual(actions, ['rate_add', 'rate_edit', 'rate_delete', 'rate_add'])
        edit = AuditEntry.objects.get(action=AuditAction.RATE_EDIT)
        self.assertEqual((edit.before['unit_price'], edit.after['unit_price']), (4500, 4600))
        self.assertEqual(edit.month, date(2026, 11, 1))
        page = self.client.get(reverse('cutting:audit'))
        self.assertContains(page, escape(EN['rate_line'].format(item='통포 7', price='4,600', date='2026-11-01')))

    def test_filter_by_month_and_pages(self):
        for n in range(55):
            services.log(AuditAction.LOCK, user=self.manager, month=SEPT)
        services.log(AuditAction.LOCK, user=self.manager, month=date(2026, 8, 1))
        page = self.client.get(reverse('cutting:audit'), {'month': '2026-09'})
        self.assertEqual(page.context['page'].paginator.count, 55)
        self.assertEqual(len(page.context['rows']), 50)
        self.assertContains(page, '?month=2026-09&amp;page=2')
        second = self.client.get(reverse('cutting:audit'), {'month': '2026-09', 'page': 2})
        self.assertEqual(len(second.context['rows']), 5)
        self.assertEqual(self.client.get(reverse('cutting:audit')).context['page'].paginator.count, 56)
        self.assertEqual(self.client.get(reverse('cutting:audit'), {'month': 'nonsense'}).status_code, 200)

    def test_the_change_log_in_korean(self):
        services.delete_record(self.lee_row, user=self.manager)
        self.lock()
        self.use_korean()
        page = self.client.get(reverse('cutting:audit'))
        self.assertContains(page, 'lang="ko"')
        self.assertContains(page, KO['audit_title'])
        self.assertContains(page, KO['action_delete_record'])
        self.assertContains(page, KO['action_lock'])

    def test_hub_and_month_page_link_to_the_log(self):
        self.assertContains(self.client.get(reverse('cutting:hub')), reverse('cutting:audit'))
        self.assertContains(self.client.get(reverse('cutting:month', args=[SEPT])),
                            f"{reverse('cutting:audit')}?month=2026-09")


class Phase4AccessTests(LockTestCase):
    def urls(self):
        return {
            'get': [reverse('cutting:audit'), reverse('cutting:reprice', args=[SEPT])],
            'post': [reverse('cutting:month_lock', args=[SEPT]), reverse('cutting:month_unlock', args=[SEPT]),
                     reverse('cutting:reprice', args=[SEPT])],
        }

    def test_only_managers_can_lock_re_price_or_read_the_log(self):
        self.client.logout()
        for url in self.urls()['get']:
            self.assertTrue(self.client.get(url)['Location'].startswith('/login/'), url)
        self.client.force_login(make_user('worker', is_employee=True))
        for url in self.urls()['get']:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        for url in self.urls()['post']:
            self.assertEqual(self.client.post(url, {'reason': 'x', 'plan': 'x'}).status_code, 403, url)
        self.assertFalse(MonthLock.objects.exists())

    def test_lock_and_unlock_are_post_only(self):
        for url in self.urls()['post'][:2]:
            self.assertEqual(self.client.get(url).status_code, 405, url)

    def test_the_admin_can_read_locks_and_the_log_but_not_change_them(self):
        lock = self.lock()
        entry = AuditEntry.objects.get()
        self.client.force_login(make_user('root', is_superuser=True, is_staff=True))
        for name, pk in (('monthlock', lock.pk), ('auditentry', entry.pk)):
            self.assertEqual(self.client.get(reverse(f'admin:cutting_{name}_changelist')).status_code, 200)
            self.assertEqual(self.client.get(reverse(f'admin:cutting_{name}_change', args=[pk])).status_code, 200)
            self.assertEqual(self.client.get(reverse(f'admin:cutting_{name}_add')).status_code, 403)
            delete = reverse(f'admin:cutting_{name}_delete', args=[pk])
            self.assertEqual(self.client.post(delete, {'post': 'yes'}).status_code, 403)
        self.assertTrue(MonthLock.objects.exists())
        self.assertTrue(AuditEntry.objects.exists())
