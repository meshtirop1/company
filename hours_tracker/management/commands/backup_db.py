"""Copy the SQLite database to settings.BACKUP_DIR as a compressed, checked snapshot.

    python manage.py backup_db --label nightly

deploy/deploy.sh runs it before every migration (label "predeploy") and cron runs it every
night (deploy/backup.sh, label "nightly"). Old copies are pruned: anything older than
--keep-days goes, but the newest --keep-min always stay, so a broken schedule never leaves
you with nothing.

To restore: stop the site, gunzip a copy over db.sqlite3, start the site again
(see deploy/backup.sh).
"""
import gzip
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

BACKUP_GLOB = 'db-*.sqlite3.gz'


class Command(BaseCommand):
    help = 'Back up the SQLite database to BACKUP_DIR (gzip, integrity-checked) and prune old copies.'

    def add_arguments(self, parser):
        parser.add_argument('--label', default='manual', help='Added to the file name, e.g. nightly or predeploy.')
        parser.add_argument('--dir', dest='backup_dir', help='Where to write (default: settings.BACKUP_DIR).')
        parser.add_argument('--keep-days', type=int, default=14, help='Delete copies older than this many days.')
        parser.add_argument('--keep-min', type=int, default=5, help='Always keep at least this many newest copies.')

    def handle(self, *args, label, backup_dir, keep_days, keep_min, **options):
        if connection.vendor != 'sqlite':
            raise CommandError(f'backup_db only handles SQLite; this database is {connection.vendor}.')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,30}', label):
            raise CommandError('--label may only use letters, digits, - and _.')

        backup_dir = Path(backup_dir or settings.BACKUP_DIR)
        backup_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(backup_dir, 0o700)  # the database holds bank accounts and pay

        stamp = timezone.localtime().strftime('%Y%m%d-%H%M%S')
        target = backup_dir / f'db-{stamp}-{label}.sqlite3.gz'
        snapshot = backup_dir / f'.{target.name}.tmp'
        try:
            self.snapshot_to(snapshot)
            self.verify(snapshot)
            with open(snapshot, 'rb') as raw, gzip.open(target, 'wb') as packed:
                shutil.copyfileobj(raw, packed)
            os.chmod(target, 0o600)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        finally:
            snapshot.unlink(missing_ok=True)

        removed = self.prune(backup_dir, keep_days, keep_min)
        self.stdout.write(f'Backed up to {target} ({target.stat().st_size:,} bytes); removed {removed} old copies.')

    def snapshot_to(self, path):
        """SQLite's online backup: a consistent copy even while the site is writing."""
        connection.ensure_connection()
        copy = sqlite3.connect(path)
        try:
            connection.connection.backup(copy)
        finally:
            copy.close()

    def verify(self, path):  # not check(): BaseCommand.check runs the system checks
        copy = sqlite3.connect(path)
        try:
            result = copy.execute('PRAGMA integrity_check').fetchone()[0]
        finally:
            copy.close()
        if result != 'ok':
            raise CommandError(f'The copy failed its integrity check: {result}')

    def prune(self, backup_dir, keep_days, keep_min):
        copies = sorted(backup_dir.glob(BACKUP_GLOB), key=lambda path: path.stat().st_mtime, reverse=True)
        cutoff = time.time() - keep_days * 86400
        removed = 0
        for path in copies[keep_min:]:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        return removed
