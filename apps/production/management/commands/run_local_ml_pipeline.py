import logging
from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.production.local_ml_pipeline import LocalPharmaMLForecastingPipeline

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Executes local ML forecasting pipeline using stored historical baseline (Zero external API calls)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            default='today',
            help='Target forecast date (YYYY-MM-DD or today)'
        )
        parser.add_argument(
            '--days-ahead',
            type=int,
            default=0,
            help='Forecast upcoming days ahead from target date (default: 0)'
        )

    def handle(self, *args, **options):
        date_str = options.get('date') or 'today'
        days_ahead = options.get('days_ahead') or 0

        today = timezone.localdate()
        if date_str.lower() == 'today':
            target_date = today
        else:
            try:
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                self.stdout.write(self.style.ERROR(f"Invalid date format: {date_str}"))
                return

        self.stdout.write(self.style.NOTICE(
            "==================================================================\n"
            "LOCAL PHARMACEUTICAL ML FORECASTING PIPELINE (ZERO EXTERNAL API CALLS)\n"
            f"Forecast Target: {target_date} (Days Ahead: {days_ahead})\n"
            "=================================================================="
        ))

        pipeline = LocalPharmaMLForecastingPipeline()

        if days_ahead > 0:
            results = pipeline.forecast_upcoming_days(days_ahead=days_ahead)
            self.stdout.write(self.style.SUCCESS(
                f"[FORECAST COMPLETE] Forecasted {len(results)} days from {target_date} to {target_date + timezone.timedelta(days=days_ahead)}."
            ))
        else:
            res = pipeline.forecast_for_date(target_date)
            self.stdout.write(self.style.SUCCESS(
                f"[FORECAST COMPLETE] Date: {res.get('date')} | Output: {res.get('total_output_kg')} kg | "
                f"Machines: {res.get('active_machines_count')} | Employees: {res.get('employees_forecasted')}"
            ))
