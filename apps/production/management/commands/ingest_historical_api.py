import logging
from datetime import datetime, date, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.production.api_ingestion import ExternalPharmaAPIIngestionService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Fetches historical data strictly once using external REST/IoT telemetry APIs from company startup to yesterday'

    def add_arguments(self, parser):
        parser.add_argument(
            '--start-date',
            type=str,
            default='2026-08-25',
            help='Company startup/inception date (YYYY-MM-DD)'
        )
        parser.add_argument(
            '--end-date',
            type=str,
            default=None,
            help='End date (YYYY-MM-DD). Defaults to yesterday.'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force re-ingestion even if historical database has already been sealed'
        )

    def handle(self, *args, **options):
        start_str = options.get('start_date') or '2026-08-25'
        end_str = options.get('end_date')
        force = options.get('force', False)

        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
        except ValueError:
            self.stdout.write(self.style.ERROR(f"Invalid start date: {start_str}"))
            return

        today = timezone.localdate()
        yesterday = today - timedelta(days=1)

        if end_str:
            try:
                end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
            except ValueError:
                self.stdout.write(self.style.ERROR(f"Invalid end date: {end_str}"))
                return
        else:
            end_date = yesterday

        if end_date >= today:
            self.stdout.write(self.style.WARNING(
                f"End date ({end_date}) cannot include today ({today}). Clamping to yesterday ({yesterday})."
            ))
            end_date = yesterday

        self.stdout.write(self.style.NOTICE(
            "==================================================================\n"
            "EXTERNAL PHARMACEUTICAL & IOT TELEMETRY HISTORICAL INGESTION\n"
            f"Range: {start_date} to {end_date} (Startup to Yesterday)\n"
            "=================================================================="
        ))

        ingestor = ExternalPharmaAPIIngestionService()
        result = ingestor.ingest_historical_data(start_date=start_date, end_date=end_date, force=force)

        if result.get("status") == "SKIPPED_ALREADY_INGESTED":
            self.stdout.write(self.style.SUCCESS(
                f"[STRICTLY-ONCE ENFORCED] {result.get('message')}"
            ))
        elif result.get("status") == "SUCCESS":
            self.stdout.write(self.style.SUCCESS(
                f"[INGESTION SUCCESS] Ingested {result.get('total_records_ingested')} records.\n"
                f"Source: {result.get('source_status')}\n"
                f"Audit Checksum: {result.get('checksum')}\n"
                f"Sealed in Supabase PostgreSQL: {result.get('is_sealed')}"
            ))
        else:
            self.stdout.write(self.style.WARNING(f"Ingestion result: {result}"))
