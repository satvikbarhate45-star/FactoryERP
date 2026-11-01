import logging
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.production.models import ProductionLog, SalaryPayroll
from apps.accounts.models import User
from apps.production.local_ml_pipeline import LocalPharmaMLForecastingPipeline
from apps.production.monthly_payroll import sync_all_monthly_payrolls

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Backfills continuous chronological shift logs, eliminates zero metrics, and syncs capped monthly payroll history.'

    def handle(self, *args, **options):
        today = timezone.localdate()
        self.stdout.write(self.style.NOTICE(f"[BACKFILL] Starting continuous data integrity check up to {today}..."))

        # 1. Purge invalid zero-output records
        del_out, _ = ProductionLog.objects.filter(output_kg__lte=0).delete()
        del_mat, _ = ProductionLog.objects.filter(material_used__lte=0).delete()
        self.stdout.write(self.style.SUCCESS(f"[PURGE] Purged {del_out} zero-output logs and {del_mat} zero-material logs."))

        # 2. Ensure continuous chronological logging for October 1, 2026 through today (November 1, 2026)
        start_oct = date(2026, 10, 1)
        cur = start_oct
        pipeline = LocalPharmaMLForecastingPipeline()
        employees = list(User.objects.filter(role='EM'))
        if not employees:
            employees = list(User.objects.all())

        backfilled_days = 0
        while cur <= today:
            valid_logs = ProductionLog.objects.filter(date=cur, output_kg__gt=0).count()
            # If any employee is missing logs on this day, run forecast
            if valid_logs < len(employees):
                pipeline.forecast_for_date(cur)
                backfilled_days += 1
            cur += timedelta(days=1)

        self.stdout.write(self.style.SUCCESS(f"[CONTINUOUS LOGS] Verified and backfilled {backfilled_days} days between {start_oct} and {today}."))

        # 3. Synchronize monthly payroll history across all cycles
        res = sync_all_monthly_payrolls(start_date=date(2026, 8, 25), end_date=today, clear_daily_records=True)
        self.stdout.write(self.style.SUCCESS(f"[MONTHLY PAYROLL] Synchronized monthly payroll: {res}"))

        # 4. Strict Safety Enforcement: Cap any completion percentage exceeding 100.0%
        over_100_count = SalaryPayroll.objects.filter(completion_percentage__gt=100.0).update(completion_percentage=100.0)
        if over_100_count > 0:
            self.stdout.write(self.style.WARNING(f"[EFFICIENCY CAP] Strictly capped {over_100_count} payroll records exceeding 100% to exactly 100.0%."))

        self.stdout.write(self.style.SUCCESS("[BACKFILL COMPLETE] Continuous shift logs, zero-metric elimination, and monthly payroll history locked in."))
