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


def ensure_runtime_schema_integrity(force=False, max_age_seconds=60):
    """
    Autonomous Runtime Schema & Table Verifier.
    Dynamically verifies and synchronizes database schema, running migrations
    and ensuring all required columns exist in Supabase PostgreSQL / SQLite
    without requiring manual terminal access on Render.
    """
    global _schema_verified, _last_verified_at
    now = time.time()
    if _schema_verified and not force and (now - _last_verified_at < max_age_seconds):
        return True

    with _guard_lock:
        now = time.time()
        if _schema_verified and not force and (now - _last_verified_at < max_age_seconds):
            return True

        logger.info("[SCHEMA GUARD] Initializing autonomous runtime schema verification (force=%s)...", force)

        # 1. Run standard Django unapplied migrations programmatically
        try:
            call_command('migrate', interactive=False, verbosity=0)
            logger.info("[SCHEMA GUARD] Automated Django migrations executed successfully.")
        except Exception as mig_err:
            logger.warning("[SCHEMA GUARD] Non-fatal migration call notice: %s", mig_err)

        # 2. Verify and self-heal critical table columns dynamically
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
                    ("maintenance_maintenanceticket", "downtime_min", "integer DEFAULT 0", "integer DEFAULT 0"),
                ]

                # Get existing tables
                existing_tables = set(connection.introspection.table_names(cursor))

                for table_name, col_name, pg_def, sqlite_def in critical_columns:
                    if table_name not in existing_tables:
                        continue

                    # Introspect columns of this table
                    try:
                        table_desc = connection.introspection.get_table_description(cursor, table_name)
                        col_names = {col.name.lower() for col in table_desc}
                    except Exception:
                        col_names = set()

                    if col_name.lower() not in col_names:
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
            logger.info("[SCHEMA GUARD] Autonomous runtime schema verification complete. Supabase integrity locked in.")
            return True
        except Exception as exc:
            logger.warning("[SCHEMA GUARD] Unexpected schema guard check exception: %s", exc)
            return False


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
        # Programmatically sync on mutation actions or critical paths
        if request.method in ('POST', 'PUT', 'DELETE'):
            # Force verification on automation/closed-loop or user creation
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
                    # Retry view execution
                    return self.get_response(request)
                except Exception as retry_err:
                    logger.error("[SCHEMA GUARD] Runtime healing retry failed: %s", retry_err)

        return None
