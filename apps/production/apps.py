from django.apps import AppConfig
import os
import sys

class ProductionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.production'

    def ready(self):
        # Prevent running during management commands (like migrate, collectstatic, shell)
        skip_cmds = {'migrate', 'makemigrations', 'collectstatic', 'test', 'loaddata', 'dumpdata', 'createsuperuser', 'check'}
        if any(arg in skip_cmds for arg in sys.argv):
            return

        # Start scheduler for web servers (Gunicorn, uWSGI) and dev server (runserver main process)
        is_runserver = 'runserver' in sys.argv
        is_runserver_main = os.environ.get('RUN_MAIN') == 'true'
        is_production_server = not is_runserver and ('gunicorn' in sys.argv[0] or 'manage.py' not in sys.argv[0] or 'runapscheduler' in sys.argv or 'wsgi' in os.environ.get('DJANGO_SETTINGS_MODULE', ''))

        if (is_runserver and is_runserver_main) or is_production_server or os.environ.get('START_SCHEDULER') == 'true':
            if os.environ.get('DISABLE_SCHEDULER', '').lower() not in ('true', '1'):
                try:
                    from .ml_scheduler import start_scheduler
                    start_scheduler()
                except Exception as exc:
                    import logging
                    logging.getLogger(__name__).warning("Could not auto-start ML scheduler in ready(): %s", exc)


