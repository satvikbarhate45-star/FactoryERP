import os
import django
import random
from datetime import timedelta
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pharma_erp.settings')
django.setup()

from apps.accounts.models import User
from apps.production.models import ProductionLog, ProductionTarget

def generate_targets():
    print("Seeding Production Targets for Supervisors...")
    today = timezone.now().date()
    start_date = today - timedelta(days=40)

    supervisors = list(User.objects.filter(role='SU'))
    operators = list(User.objects.filter(role='EM'))
    
    if not supervisors or not operators:
        print("Missing supervisors or operators.")
        return

    # Seed past 40 days of targets
    count = 0
    for i in range(41):
        d = start_date + timedelta(days=i)
        
        # We assign a daily target for each active operator
        for op in operators:
            # Check if there is an existing log to make the target somewhat realistic
            log = ProductionLog.objects.filter(employee=op, date=d).first()
            if log:
                # The target was around what they produced (maybe they overperformed/underperformed)
                target = float(log.output_kg) * random.uniform(0.9, 1.15)
            else:
                target = random.uniform(200.0, 400.0)
                
            ProductionTarget.objects.get_or_create(
                date=d,
                employee=op,
                defaults={
                    'target_kg': round(target, 2),
                    'set_by': random.choice(supervisors),
                    'is_rollover': random.random() > 0.9 # 10% chance it was a rollover
                }
            )
            count += 1

    print(f"Successfully generated {count} Production Targets!")

if __name__ == '__main__':
    generate_targets()
