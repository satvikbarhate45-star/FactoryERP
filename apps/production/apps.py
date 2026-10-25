from django.apps import AppConfig
import os
import sys

class ProductionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.production'

    def ready(self):
        # Prevent running multiple times or during management commands (like loaddata/migrate)
        if 'runserver' in sys.argv and os.environ.get('RUN_MAIN') == 'true':
            from .ml_scheduler import start_scheduler
            start_scheduler()

