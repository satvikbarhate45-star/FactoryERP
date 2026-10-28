import logging
import threading
from django.db import connection
from django.core.management import call_command

logger = logging.getLogger(__name__)

_guard_lock = threading.Lock()
_schema_verified = False


def ensure_runtime_schema_integrity(force=False):
    """
    Autonomous Runtime Schema & Table Verifier.
    Dynamically verifies and synchronizes database schema, running migrations
    and ensuring all required columns exist in Supabase PostgreSQL / SQLite
    without requiring manual terminal access on Render.
    """
    global _schema_verified
    if _schema_verified and not force:
        return True

    with _guard_lock:
        if _schema_verified and not force:
            return True

        logger.info("[SCHEMA GUARD] Initializing autonomous runtime schema verification...")

        # 1. Run standard Django unapplied migrations
        try:
            call_command('migrate', interactive=False, verbosity=0)
            logger.info("[SCHEMA GUARD] Automated Django migrations executed successfully.")
        except Exception as mig_err:
            logger.warning("[SCHEMA GUARD] Non-fatal migration call warning: %s", mig_err)

        # 2. Verify and self-heal critical table columns
        try:
            vendor = connection.vendor
            with connection.cursor() as cursor:
                # Definitions of critical columns that must exist across all models
                critical_columns = [
                    # (table_name, column_name, postgres_def, sqlite_def)
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
                    ("production_salarypayroll", "is_auto_predicted", "boolean DEFAULT false", "boolean DEFAULT 0"),
                    ("production_salarypayroll", "is_incremented", "boolean DEFAULT false", "boolean DEFAULT 0"),
                    ("production_systemoverview", "is_auto_filled", "boolean DEFAULT false", "boolean DEFAULT 0"),
                    ("production_productionlog", "is_auto_predicted", "boolean DEFAULT false", "boolean DEFAULT 0"),
                    ("maintenance_machineprediction", "is_auto_predicted", "boolean DEFAULT false", "boolean DEFAULT 0"),
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

            _schema_verified = True
            logger.info("[SCHEMA GUARD] Autonomous runtime schema verification complete. Supabase integrity locked in.")
            return True
        except Exception as exc:
            logger.warning("[SCHEMA GUARD] Unexpected schema guard check exception: %s", exc)
            return False


def start_background_schema_guard():
    """Starts the schema verification in a background daemon thread."""
    t = threading.Thread(
        target=ensure_runtime_schema_integrity,
        daemon=True,
        name='autonomous_schema_guard_worker'
    )
    t.start()
