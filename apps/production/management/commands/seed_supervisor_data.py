import random
from datetime import timedelta
from django.utils import timezone
from django.core.management.base import BaseCommand
from apps.accounts.models import User
from apps.production.models import ProductionLog, ProductionTarget, SalaryPayroll

class Command(BaseCommand):
    help = 'Seeds initial Master Supervisor data, allocates employees, and auto-imputes historical payrolls.'

    def handle(self, *args, **kwargs):
        # 1. Ensure Master Supervisor exists
        supervisor, created = User.objects.get_or_create(
            username='supervisor',
            defaults={
                'email': 'supervisor@erp.com',
                'role': 'SU',
                'first_name': 'Master',
                'last_name': 'Supervisor',
                'is_active': True
            }
        )
        if created:
            supervisor.set_password('supervisor123')
            supervisor.save()
            self.stdout.write(self.style.SUCCESS('Created Master Supervisor (supervisor/supervisor123)'))
        else:
            supervisor.set_password('supervisor123')
            supervisor.save()
            self.stdout.write(self.style.SUCCESS('Master Supervisor exists, updated password to supervisor123'))

        # 2. Allocate employees to this supervisor
        employees = User.objects.filter(role='EM')
        for emp in employees:
            emp.supervisor = supervisor
            emp.save()
        self.stdout.write(self.style.SUCCESS(f'Allocated {employees.count()} employees to Master Supervisor'))

        # 3. Seed historical auto-imputation and payroll
        today = timezone.localdate()
        base_salary_per_day = 500.0  # arbitrary daily wage
        bonus_increment = 100.0

        for emp in employees:
            for i in range(30, 0, -1):
                past_date = today - timedelta(days=i)
                
                # Check if a log exists, if not, auto-impute
                log = ProductionLog.objects.filter(employee=emp, date=past_date).first()
                target_obj = ProductionTarget.objects.filter(employee=emp, date=past_date).first()
                
                # Zero-Manual Historical Auto-Imputation Logic
                is_auto = False
                if not log:
                    is_auto = True
                    # Impute output based on historical trends or fixed random if none
                    actual_output = random.uniform(250.0, 350.0)
                else:
                    actual_output = float(log.output_kg)

                if not target_obj:
                    target_assigned = 300.0
                else:
                    target_assigned = float(target_obj.target_kg)

                completion_percentage = (actual_output / target_assigned) * 100 if target_assigned > 0 else 0

                # Payroll Logic
                is_incremented = False
                salary_adjusted = base_salary_per_day

                if completion_percentage >= 100:
                    salary_adjusted += bonus_increment
                    is_incremented = True
                else:
                    # proportional penalty
                    penalty = base_salary_per_day * (1 - (completion_percentage / 100))
                    salary_adjusted -= penalty
                    # ensure it doesn't go negative
                    if salary_adjusted < 0:
                        salary_adjusted = 0

                # Create or Update Payroll
                SalaryPayroll.objects.update_or_create(
                    employee=emp,
                    payout_date=past_date,
                    defaults={
                        'base_salary': base_salary_per_day,
                        'target_assigned': target_assigned,
                        'actual_output': actual_output,
                        'completion_percentage': completion_percentage,
                        'salary_adjusted': salary_adjusted,
                        'is_incremented': is_incremented,
                        'is_auto_predicted': is_auto
                    }
                )

        self.stdout.write(self.style.SUCCESS('Successfully seeded historical payroll and imputed missing data.'))
