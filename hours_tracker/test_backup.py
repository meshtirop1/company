import gzip
import io
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest import mock

from django.core.management import CommandError, call_command
from django.db import connection
from django.test import TransactionTestCase

from .models import CustomUser


class BackupCommandTests(TransactionTestCase):
    """manage.py backup_db — run by deploy.sh before every migration and by cron every night.
    A TransactionTestCase, so the rows are committed and the copy can see them."""

    def setUp(self):
        self.dir = self.temp_dir()

    def temp_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def backup(self, **options):
        call_command('backup_db', backup_dir=str(self.dir), stdout=io.StringIO(), **options)
        return sorted(self.dir.glob('db-*.sqlite3.gz'))

    def open_copy(self, path):
        raw = self.temp_dir() / 'restored.sqlite3'
        raw.write_bytes(gzip.decompress(path.read_bytes()))
        return sqlite3.connect(raw)

    def test_the_copy_holds_the_data(self):
        CustomUser.objects.create_user(username='kim', email='kim@example.com', password='not-a-real-pass-123')
        [copy] = self.backup(label='predeploy')
        self.assertRegex(copy.name, r'^db-\d{8}-\d{6}-predeploy\.sqlite3\.gz$')
        self.assertEqual([path.name for path in self.dir.iterdir()], [copy.name])  # no temp file left
        restored = self.open_copy(copy)
        try:
            names = [row[0] for row in restored.execute('SELECT username FROM hours_tracker_customuser')]
            self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        finally:
            restored.close()
        self.assertEqual(names, ['kim'])

    def test_old_copies_are_pruned_but_the_newest_always_stay(self):
        month_ago = time.time() - 30 * 86400
        for day in range(1, 8):
            old = self.dir / f'db-2026090{day}-030000-nightly.sqlite3.gz'
            old.write_bytes(b'old')
            os.utime(old, (month_ago + day, month_ago + day))
        unrelated = self.dir / 'notes.txt'
        unrelated.write_text('keep me')
        os.utime(unrelated, (month_ago, month_ago))

        copies = self.backup(label='nightly', keep_days=14, keep_min=3)
        names = [path.name for path in copies]
        # The new copy plus the two newest old ones (keep_min=3); the other five are gone.
        self.assertEqual(len(names), 3)
        self.assertIn('db-20260907-030000-nightly.sqlite3.gz', names)
        self.assertIn('db-20260906-030000-nightly.sqlite3.gz', names)
        self.assertTrue(unrelated.exists())

    def test_recent_copies_are_kept(self):
        for n in range(4):
            recent = self.dir / f'db-2026101{n}-030000-nightly.sqlite3.gz'
            recent.write_bytes(b'recent')
        self.assertEqual(len(self.backup(keep_days=14, keep_min=1)), 5)

    def test_a_bad_label_or_another_database_is_refused(self):
        with self.assertRaises(CommandError):
            self.backup(label='../../etc')
        with mock.patch.object(connection, 'vendor', 'postgresql'), self.assertRaises(CommandError):
            self.backup()
        self.assertEqual(list(self.dir.iterdir()), [])
