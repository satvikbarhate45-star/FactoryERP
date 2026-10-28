from django.apps import AppConfig
import sys

class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.accounts'

    def ready(self):
        skip_cmds = {'makemigrations', 'collectstatic', 'check', 'test'}
        if any(arg in skip_cmds for arg in sys.argv):
            return

        try:
            from .schema_guard import start_background_schema_guard
            start_background_schema_guard()
        except Exception:
            pass
