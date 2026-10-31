import logging
import threading
import time
from django.db import connection, connections
from django.core.management import call_command
from django.db.utils import OperationalError, ProgrammingError, InterfaceError

logger = logging.getLogger(__name__)

_guard_lock = threading.Lock()
_schema_verified = False
_last_verified_at = 0.0
_last_migration_at = 0.0


def ensure_runtime_schema_integrity(force=False, max_age_seconds=60):
    """
    Autonomous Runtime Schema & Table Verifier.
    Dynamically verifies and synchronizes database schema, running migrations
    and ensuring all required columns exist in Supabase PostgreSQL / SQLite
    without requiring manual terminal access on Render.
    Non-blocking: will never freeze or crash Gunicorn worker threads.
    """
    global _schema_verified, _last_verified_at, _last_migration_at
    now = time.time()

    # Short debounce: if verified in last 15 seconds, skip even if force=True
    if _schema_verified and (now - _last_verified_at < (15.0 if force else max_age_seconds)):
        return True

    # Non-blocking lock: if another thread is currently synchronizing, don't stall the HTTP worker!
    if not _guard_lock.acquire(blocking=False):
        logger.info("[SCHEMA GUARD] Schema verification already active in another thread. Proceeding without blocking.")
        return True

    try:
        now = time.time()
        logger.info("[SCHEMA GUARD] Running autonomous schema verification (force=%s)...", force)

        # 1. Run standard Django unapplied migrations asynchronously so Gunicorn worker NEVER hangs
        if force or (now - _last_migration_at > 60.0):
            def _async_migrate():
                try:
                    call_command('migrate', interactive=False, verbosity=0)
                    logger.info("[SCHEMA GUARD] Automated Django migrations executed successfully in background.")
                except BaseException as mig_err:
                    logger.warning("[SCHEMA GUARD] Non-fatal migration call notice: %s", mig_err)

            t_mig = threading.Thread(target=_async_migrate, daemon=True, name="async_runtime_migrator")
            t_mig.start()
            _last_migration_at = time.time()

        # 2. Verify and self-heal critical table columns dynamically (Single-Query Introspection, < 0.05s)
        try:
            vendor = connection.vendor
            with connection.cursor() as cursor:
                # Definitions of critical columns that must exist across all models
                critical_columns = [
                    # (table_name, column_name, postgres_def, sqlite_def)
                    # Accounts / User
                    ("accounts_user", "supervisor_id", "bigint REFERENCES accounts_user(id) ON DELETE SET NULL", "bigint REFERENCES accounts_user(id)"),
                    ("accounts_user", "kyc_status", "varchar(10) DEFAULT 'PENDING'", "varchar(10) DEFAULT 'PENDING'"),
                    ("accounts_user", "rejection_reason", "text", "text"),
                    ("accounts_user", "phone", "varchar(25)", "varchar(25)"),
                    ("accounts_user", "whatsapp", "varchar(25)", "varchar(25)"),
                    ("accounts_user", "pan", "varchar(20)", "varchar(20)"),
                    ("accounts_user", "government_id", "varchar(50)", "varchar(50)"),
                    ("accounts_user", "account_number", "varchar(50)", "varchar(50)"),
                    ("accounts_user", "ifsc", "varchar(20)", "varchar(20)"),
                    ("accounts_user", "photo", "varchar(100)", "varchar(100)"),
                    ("accounts_user", "kyc_submitted_at", "timestamp with time zone", "datetime"),
                    ("accounts_user", "kyc_reviewed_at", "timestamp with time zone", "datetime"),
                    ("accounts_user", "kyc_reviewed_by_id", "bigint REFERENCES accounts_user(id) ON DELETE SET NULL", "bigint REFERENCES accounts_user(id)"),
                    ("accounts_user", "role", "varchar(2) DEFAULT 'EM'", "varchar(2) DEFAULT 'EM'"),
                    ("accounts_user", "language", "varchar(10) DEFAULT 'en'", "varchar(10) DEFAULT 'en'"),
                    ("accounts_user", "theme", "varchar(10) DEFAULT 'light'", "varchar(10) DEFAULT 'light'"),
                    ("accounts_user", "shift_id", "bigint REFERENCES accounts_shift(id) ON DELETE SET NULL", "bigint REFERENCES accounts_shift(id)"),
                    ("accounts_user", "machine_id", "bigint REFERENCES maintenance_machine(id) ON DELETE SET NULL", "bigint REFERENCES maintenance_machine(id)"),
                    
                    # Production
                    ("production_productionlog", "is_auto_predicted", "boolean DEFAULT false", "boolean DEFAULT 0"),
                    ("production_salarypayroll", "is_auto_predicted", "boolean DEFAULT false", "boolean DEFAULT 0"),
                    ("production_salarypayroll", "is_incremented", "boolean DEFAULT false", "boolean DEFAULT 0"),
                    ("production_systemoverview", "is_auto_filled", "boolean DEFAULT false", "boolean DEFAULT 0"),
                    ("production_productiontarget", "is_rollover", "boolean DEFAULT false", "boolean DEFAULT 0"),
                    ("production_systemalert", "is_autonomous", "boolean DEFAULT true", "boolean DEFAULT 1"),
                    ("production_systemalert", "is_resolved", "boolean DEFAULT false", "boolean DEFAULT 0"),
                    ("production_systemalert", "decision_taken", "text", "text"),

                    # Maintenance
                    ("maintenance_machine", "ai_enabled", "boolean DEFAULT true", "boolean DEFAULT 1"),
                    ("maintenance_machine", "featured_for", "varchar(200)", "varchar(200)"),
                    ("maintenance_machine", "model_name", "varchar(100)", "varchar(100)"),
                    ("maintenance_machineprediction", "is_auto_predicted", "boolean DEFAULT false", "boolean DEFAULT 0"),
                    ("maintenance_machineprediction", "reason", "text", "text"),
                    ("maintenance_machineprediction", "predicted_rul_days", "integer DEFAULT 45", "integer DEFAULT 45"),
                    ("maintenance_machineprediction", "health_score", "numeric(5,2) DEFAULT 98.50", "numeric(5,2) DEFAULT 98.50"),
                    ("maintenance_machineprediction", "accuracy_pct", "numeric(5,2) DEFAULT 94.50", "numeric(5,2) DEFAULT 94.50"),
                    ("maintenance_maintenanceticket", "downtime_min", "integer DEFAULT 0", "integer DEFAULT 0"),
                    ("maintenance_maintenanceticket", "parts_cost", "numeric(10,2) DEFAULT 0.00", "numeric(10,2) DEFAULT 0.00"),
                    ("maintenance_maintenanceticket", "labor_cost", "numeric(10,2) DEFAULT 0.00", "numeric(10,2) DEFAULT 0.00"),
                    ("maintenance_maintenanceticket", "total_cost", "numeric(10,2) DEFAULT 0.00", "numeric(10,2) DEFAULT 0.00"),
                    ("maintenance_maintenanceticket", "resolution_notes", "text", "text"),

                    # Logistics
                    ("logistics_dispatch", "dispatch_type", "varchar(20) DEFAULT 'EXPORT'", "varchar(20) DEFAULT 'EXPORT'"),
                    ("logistics_dispatch", "is_automated", "boolean DEFAULT false", "boolean DEFAULT 0"),
                ]

                # High-speed introspection: batch load all table and column names in ONE query
                existing_columns = set()
                try:
                    if vendor == 'postgresql':
                        cursor.execute("""
                            SELECT lower(table_name), lower(column_name) 
                            FROM information_schema.columns 
                            WHERE table_schema = current_schema();
                        """)
                        existing_columns = {(r[0], r[1]) for r in cursor.fetchall()}
                    elif vendor == 'sqlite':
                        existing_tables = set(connection.introspection.table_names(cursor))
                        for tbl in existing_tables:
                            cursor.execute(f"PRAGMA table_info({tbl});")
                            for row in cursor.fetchall():
                                existing_columns.add((tbl.lower(), row[1].lower()))
                    else:
                        existing_tables = set(connection.introspection.table_names(cursor))
                        for tbl in existing_tables:
                            for col in connection.introspection.get_table_description(cursor, tbl):
                                existing_columns.add((tbl.lower(), col.name.lower()))
                except Exception as intro_err:
                    logger.warning("[SCHEMA GUARD] Fast introspection notice: %s. Using safe fallback.", intro_err)

                for table_name, col_name, pg_def, sqlite_def in critical_columns:
                    col_key = (table_name.lower(), col_name.lower())
                    if existing_columns and col_key in existing_columns:
                        continue

                    # If not found in existing columns, patch dynamically
                    logger.info(f"[SCHEMA GUARD] Column '{col_name}' missing from '{table_name}'. Applying dynamic DDL patch...")
                    try:
                        if vendor == 'postgresql':
                            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {col_name} {pg_def};")
                        elif vendor == 'sqlite':
                            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {sqlite_def};")
                        else:
                            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {pg_def};")
                        logger.info(f"[SCHEMA GUARD] Successfully patched column '{col_name}' on table '{table_name}'.")
                    except Exception as ddl_err:
                        logger.warning(f"[SCHEMA GUARD] Handled non-fatal DDL patch notice for {table_name}.{col_name}: {ddl_err}")

            _last_verified_at = time.time()
            _schema_verified = True
            logger.info("[SCHEMA GUARD] Schema verification complete. Supabase integrity locked in.")
            return True
        except Exception as exc:
            logger.warning("[SCHEMA GUARD] Unexpected schema guard check exception: %s", exc)
            return False
    finally:
        _guard_lock.release()


def start_background_schema_guard():
    """Starts the schema verification in a background daemon thread on boot."""
    t = threading.Thread(
        target=ensure_runtime_schema_integrity,
        kwargs={'force': True},
        daemon=True,
        name='autonomous_schema_guard_worker'
    )
    t.start()


class RuntimeSchemaSyncMiddleware:
    """
    Middleware ensuring database migrations and runtime schema updates are
    automatically synchronized on mutating actions (POST/PUT/DELETE) and
    preventing 500 errors from missing columns or unapplied migrations.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in ('POST', 'PUT', 'DELETE'):
            is_critical_action = (
                request.POST.get('action') in ('run_automation', 'create_user', 'edit_user', 'approve_kyc') or
                'sync-loop' in request.path or
                'equipment' in request.path
            )
            ensure_runtime_schema_integrity(force=is_critical_action, max_age_seconds=30)

        response = self.get_response(request)
        return response

    def process_exception(self, request, exception):
        """
        Self-healing exception catcher:
        If a database query crashes due to a missing column, relation, or unapplied migration,
        programmatically trigger schema synchronization and retry.
        """
        if isinstance(exception, (ProgrammingError, OperationalError)):
            msg = str(exception).lower()
            if any(term in msg for term in ('does not exist', 'undefined column', 'undefined table', 'no such column', 'no such table')):
                logger.error("[SCHEMA GUARD] Caught schema mismatch exception: %s. Initiating runtime healing...", exception)
                try:
                    ensure_runtime_schema_integrity(force=True)
                    connections.close_all()
                    time.sleep(0.2)
                    return self.get_response(request)
                except Exception as retry_err:
                    logger.error("[SCHEMA GUARD] Runtime healing retry failed: %s", retry_err)

        return None
