import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from apps.production.ml_scheduler import autonomous_gap_detection_and_imputation

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Autonomous gap detection and ML pipeline imputation across past operational days'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=14,
            help='Number of preceding days to check and backfill missing operational data (default: 14)'
        )

    def handle(self, *args, **options):
        days_back = options.get('days') or 14
        self.stdout.write(self.style.NOTICE(
            f"Starting Autonomous Gap Detection & ML Imputation for the past {days_back} days..."
        ))

        try:
            autonomous_gap_detection_and_imputation(days_back=days_back)
            self.stdout.write(self.style.SUCCESS(
                f"Successfully completed ML gap detection and backfill for {days_back} days. Monday, Tuesday, and past gaps resolved."
            ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(
                f"Autonomous gap detection encountered an error: {e}"
            ))
            logger.exception("Error executing daily_imputation management command:")
