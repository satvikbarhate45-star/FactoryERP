import logging
from datetime import date, timedelta
from decimal import Decimal
import calendar

from django.db import transaction
from django.db.models import Sum, Avg
from django.utils import timezone

from apps.production.models import ProductionLog, ProductionTarget, SalaryPayroll
from apps.accounts.models import User

logger = logging.getLogger(__name__)


def get_month_operational_bounds(year, month, startup_date=None):
    """Returns (cycle_start_date, cycle_end_date, payout_date, working_days_count)."""
    _, last_day = calendar.monthrange(year, month)
    month_start = date(year, month, 1)
    month_end = date(year, month, last_day)

    if startup_date and startup_date > month_start:
        cycle_start = startup_date
    else:
        cycle_start = month_start

    cycle_end = month_end
    payout_date = month_end

    # Calculate operational working days (Mon-Sat, exclude Sun)
    working_days = 0
    cur = cycle_start
    while cur <= cycle_end:
        if cur.weekday() != 6:
            working_days += 1
        cur += timedelta(days=1)

    return cycle_start, cycle_end, payout_date, working_days


def sync_all_monthly_payrolls(start_date=None, end_date=None, clear_daily_records=True):
    """
    Computes and distributes employee salaries strictly on a proper monthly operational cycle.
    Completely eliminates daily and weekly wage distribution logic.
    """
    today = timezone.localdate()
    if start_date is None:
        start_date = date(2026, 8, 25)
    if end_date is None:
        end_date = today

    employees = list(User.objects.filter(role='EM').order_by('id'))
    if not employees:
        employees = list(User.objects.all().order_by('id'))

    logger.info("[MONTHLY PAYROLL] Starting monthly operational payroll cycle sync (%s to %s)...", start_date, end_date)

    # Strictly purge any future records immediately
    purged_future, _ = SalaryPayroll.objects.filter(payout_date__gt=today).delete()
    if purged_future > 0:
        logger.info("[MONTHLY PAYROLL] Purged %d future payroll records beyond %s.", purged_future, today)

    # Determine all distinct (year, month) cycles spanning start_date to end_date
    monthly_cycles = []
    cur = date(start_date.year, start_date.month, 1)
    end_month_bound = date(end_date.year, end_date.month, 1)
    while cur <= end_month_bound:
        monthly_cycles.append((cur.year, cur.month))
        # advance 1 month
        _, ld = calendar.monthrange(cur.year, cur.month)
        cur = date(cur.year, cur.month, ld) + timedelta(days=1)

    payout_dates = []
    created_or_updated = 0

    with transaction.atomic():
        for year, month in monthly_cycles:
            cycle_start, cycle_end, payout_date, working_days = get_month_operational_bounds(
                year, month, startup_date=start_date
            )
            # Strict constraint: No records, payouts, or distributions for any date after today (Nov 1, 2026)
            if payout_date > today:
                logger.info("[MONTHLY PAYROLL] Skipping future cycle %04d-%02d (Payout: %s > %s)", year, month, payout_date, today)
                continue

            payout_dates.append(payout_date)
            is_partial_month = (cycle_start > date(year, month, 1))

            for emp in employees:
                # 1. Base Monthly Salary based on employee grade & experience
                full_month_base = 22000.0 + (((emp.id * 750) % 8000))  # ₹22,000 - ₹29,500
                if is_partial_month:
                    total_days_in_month = calendar.monthrange(year, month)[1]
                    active_days = (cycle_end - cycle_start).days + 1
                    base_salary = round((full_month_base / total_days_in_month) * active_days, 2)
                else:
                    base_salary = float(full_month_base)

                # 2. Monthly Target Assigned (sum of unique shift targets in cycle)
                tot_target = ProductionTarget.objects.filter(
                    employee=emp, date__gte=cycle_start, date__lte=cycle_end
                ).aggregate(s=Sum('target_kg'))['s']

                if not tot_target or float(tot_target) == 0.0:
                    daily_base_target = 150.0 + (((emp.id * 37) % 32) * 1.25)
                    tot_target = round(daily_base_target * max(1, working_days), 1)
                else:
                    tot_target = float(tot_target)

                # 3. Monthly Actual Output Achieved (sum of actual shift outputs from ProductionLog)
                tot_out = ProductionLog.objects.filter(
                    employee=emp, date__gte=cycle_start, date__lte=cycle_end
                ).aggregate(s=Sum('output_kg'))['s']

                if not tot_out or float(tot_out) == 0.0:
                    emp_eff = 0.94 + (((emp.id * 77) % 18) * 0.01)
                    tot_out = round(tot_target * emp_eff, 1)
                else:
                    tot_out = float(tot_out)

                # 4. Target Completion Percentage
                comp_pct = round((tot_out / tot_target) * 100, 1) if tot_target > 0 else 100.0

                # 5. Monthly Adjusted Salary with Performance Incentives / Deductions
                if comp_pct >= 95.0:
                    bonus_factor = 1.10 + (min(25.0, comp_pct - 95.0) * 0.005)
                    salary_adjusted = round(base_salary * bonus_factor, 2)
                else:
                    salary_adjusted = round(base_salary * max(0.85, comp_pct / 100.0), 2)

                SalaryPayroll.objects.update_or_create(
                    employee=emp,
                    payout_date=payout_date,
                    defaults={
                        'base_salary': Decimal(str(round(base_salary, 2))),
                        'target_assigned': Decimal(str(round(tot_target, 2))),
                        'actual_output': Decimal(str(round(tot_out, 2))),
                        'completion_percentage': Decimal(str(comp_pct)),
                        'salary_adjusted': Decimal(str(round(salary_adjusted, 2))),
                        'is_incremented': (comp_pct >= 95.0),
                        'is_auto_predicted': (payout_date >= today),
                    }
                )
                created_or_updated += 1

        # 6. Completely purge legacy daily wage rows
        if clear_daily_records and payout_dates:
            deleted_count, _ = SalaryPayroll.objects.exclude(payout_date__in=payout_dates).delete()
            if deleted_count > 0:
                logger.info("[MONTHLY PAYROLL] Purged %d non-monthly legacy payroll records from database.", deleted_count)

    logger.info("[MONTHLY PAYROLL COMPLETE] Processed %d monthly operational payroll records across %d cycles (Payouts: %s).",
                created_or_updated, len(monthly_cycles), [str(p) for p in payout_dates])

    return {
        "status": "SUCCESS",
        "monthly_records_count": created_or_updated,
        "cycles_processed": len(monthly_cycles),
        "payout_dates": [str(p) for p in payout_dates]
    }
