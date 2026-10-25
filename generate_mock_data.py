import os
import django
import random
from datetime import timedelta
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pharma_erp.settings')
django.setup()

from apps.maintenance.models import Machine
from apps.production.models import ProductionLog
from apps.accounts.models import User

def generate_data():
    print("Generating mock data...")

    # Ensure we have at least one user to assign as operator
    user = User.objects.filter(role='EM').first()
    if not user:
        user = User.objects.filter(is_superuser=True).first()
    if not user:
        user = User.objects.create(username='operator1', email='op1@example.com', role='EM')
        user.set_password('password123')
        user.save()

    machine_types = [
        ("MIX", "Mixing Tank", "Siemens MixPro", "High Viscosity Liquids"),
        ("CT", "Coating Machine", "Bosch CoatMaster", "Tablet Coating"),
        ("PK", "Packaging Line", "Uhlmann Pack 200", "Blister Packaging"),
        ("BIO", "Bioreactor", "Sartorius BioSTAT", "Cell Culture"),
        ("CEN", "Centrifuge", "Thermo Sorvall", "Separation"),
        ("DRY", "Fluid Bed Dryer", "Glatt Pro", "Granulation Drying"),
        ("TBL", "Tablet Press", "Fette Compacting", "High Speed Press")
    ]

    # Create 21 machines
    machines = []
    for i in range(1, 22):
        m_type = random.choice(machine_types)
        code = f"{m_type[0]}-{i:02d}"
        name = f"{m_type[1]} {i}"
        
        machine, created = Machine.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'model_name': m_type[2],
                'featured_for': m_type[3],
                'ai_enabled': random.choice([True, False]),
                'status': 'OP'
            }
        )
        machines.append(machine)
        if created:
            print(f"Created machine {code}")

    # Generate 40 days of data for each machine
    today = timezone.now().date()
    start_date = today - timedelta(days=40)
    
    total_logs = 0
    for machine in machines:
        for i in range(41): # 0 to 40 days
            current_date = start_date + timedelta(days=i)
            
            # Check if log already exists
            if not ProductionLog.objects.filter(machine=machine, date=current_date).exists():
                # Random output
                raw = round(random.uniform(100.0, 500.0), 2)
                # Yield between 80% and 98%
                yield_pct = random.uniform(0.80, 0.98)
                output = round(raw * yield_pct, 2)
                
                ProductionLog.objects.create(
                    date=current_date,
                    employee=user,
                    machine=machine,
                    material_used=raw,
                    output_kg=output
                )
                total_logs += 1

    print(f"Successfully generated 21 machines and {total_logs} production logs.")

if __name__ == '__main__':
    generate_data()
