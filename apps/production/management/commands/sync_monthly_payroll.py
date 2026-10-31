import logging
from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.production.monthly_payroll import sync_all_monthly_payrolls
from apps.production.models import SalaryPayroll

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Synchronizes employee payroll strictly on a monthly operational cycle and purges daily/weekly records'

    def add_arguments(self, parser):
        parser.add_argument(
            '--start-date',
            type=str,
            default='2026-08-25',
            help='Company startup or cycle start date (YYYY-MM-DD)'
        )
        parser.add_argument(
            '--end-date',
            type=str,
            default='today',
            help='Cycle end date (YYYY-MM-DD or today)'
        )
        parser.add_argument(
            '--keep-daily',
            action='store_true',
            help='Do not delete daily payroll records (default is to purge them)'
        )

    def handle(self, *args, **options):
        start_str = options.get('start_date') or '2026-08-25'
        end_str = options.get('end_date') or 'today'
        clear_daily = not options.get('keep_daily', False)

        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
        except ValueError:
            self.stdout.write(self.style.ERROR(f"Invalid start date: {start_str}"))
            return

        today = timezone.localdate()
        if end_str.lower() == 'today':
            end_date = today
        else:
            try:
                end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
            except ValueError:
                self.stdout.write(self.style.ERROR(f"Invalid end date: {end_str}"))
                return

        self.stdout.write(self.style.NOTICE(
            "==================================================================\n"
            "MONTHLY OPERATIONAL PAYROLL CYCLE SYNCHRONIZATION\n"
            f"Range: {start_date} to {end_date} | Purge Daily Records: {clear_daily}\n"
            "=================================================================="
        ))

        result = sync_all_monthly_payrolls(
            start_date=start_date,
            end_date=end_date,
            clear_daily_records=clear_daily
        )

        total_payrolls = SalaryPayroll.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"[PAYROLL SYNC COMPLETE]\n"
            f"Cycles: {result.get('cycles_processed')} | Payout Dates: {result.get('payout_dates')}\n"
            f"Monthly Records Created/Updated: {result.get('monthly_records_count')}\n"
            f"Current Total SalaryPayroll Count in DB: {total_payrolls}"
        ))
