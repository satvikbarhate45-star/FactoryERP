"""
PharmaERP Dual-Database Architecture: Primary Supabase & Local SQLite Backup
=============================================================================
Non-blocking, thread-safe asynchronous dual-database synchronization.
1. PrimaryBackupRouter:
   - Routes all standard application READ/WRITE operations to Supabase PostgreSQL ('default').
   - Respects explicit 'sqlite_backup' targets for backup synchronization.
   - Authorizes schema migrations on both 'default' and 'sqlite_backup'.

2. Asynchronous Dual-Write Synchronization:
   - Uses a background worker thread pool to mirror writes and deletes to 'sqlite_backup'.
   - The primary Supabase HTTP transaction completes immediately without waiting or freezing.
   - Uses thread-local recursion guards (_local.is_mirroring) to prevent recursive signal loops.
   - Enforces a strict 3-second timeout on SQLite locks to eliminate blocking deadlocks.
"""

import threading
import logging
from concurrent.futures import ThreadPoolExecutor
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

logger = logging.getLogger(__name__)

# Exclude internal Django permission/contenttype tables to prevent integrity conflicts
EXCLUDED_APPS = {'contenttypes', 'auth'}
EXCLUDED_MODELS = {'contenttype', 'permission', 'migration'}

# Thread-local storage for recursion guard (replaces flawed global boolean)
_thread_local = threading.local()

# Dedicated background worker for non-blocking backup writes
_backup_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='sqlite_backup_sync')


class PrimaryBackupRouter:
    """
    Database Router enforcing Primary (Supabase) for all standard reads/writes,
    while permitting explicit routing and migrations on 'sqlite_backup'.
    """

    def db_for_read(self, model, **hints):
        if hints.get('target_db') == 'sqlite_backup':
            return 'sqlite_backup'
        instance = hints.get('instance')
        if instance and getattr(instance, '_state', None) and instance._state.db == 'sqlite_backup':
            return 'sqlite_backup'
        return 'default'

    def db_for_write(self, model, **hints):
        if hints.get('target_db') == 'sqlite_backup':
            return 'sqlite_backup'
        instance = hints.get('instance')
        if instance and getattr(instance, '_state', None) and instance._state.db == 'sqlite_backup':
            return 'sqlite_backup'
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return db in ('default', 'sqlite_backup')


def _execute_sqlite_mirror_save(sender, pk_val, field_values):
    """Worker function executed asynchronously in background thread."""
    try:
        _thread_local.is_mirroring = True
        sender.objects.using('sqlite_backup').update_or_create(
            pk=pk_val,
            defaults=field_values
        )
    except Exception as e:
        logger.warning(f"[ASYNC BACKUP WARNING] Failed to mirror save {sender._meta.label} (ID: {pk_val}) to sqlite_backup: {e}")
    finally:
        _thread_local.is_mirroring = False


def _execute_sqlite_mirror_delete(sender, pk_val):
    """Worker function executed asynchronously in background thread."""
    try:
        _thread_local.is_mirroring = True
        sender.objects.using('sqlite_backup').filter(pk=pk_val).delete()
    except Exception as e:
        logger.warning(f"[ASYNC BACKUP WARNING] Failed to mirror delete {sender._meta.label} (ID: {pk_val}) in sqlite_backup: {e}")
    finally:
        _thread_local.is_mirroring = False


# Master switch for local SQLite backup mirroring (Set to False to disable local disk write locks)
ENABLE_SQLITE_MIRRORING = False


@receiver(post_save)
def mirror_save_to_sqlite_backup(sender, instance, created, using, **kwargs):
    """
    Disabled per user instruction to eliminate local write locks.
    Database operations go 100% strictly to Supabase ('default').
    """
    if not ENABLE_SQLITE_MIRRORING:
        return


@receiver(post_delete)
def mirror_delete_to_sqlite_backup(sender, instance, using, **kwargs):
    """
    Disabled per user instruction to eliminate local write locks.
    Database operations go 100% strictly to Supabase ('default').
    """
    if not ENABLE_SQLITE_MIRRORING:
        return
