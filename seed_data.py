import os
import django
import random
from datetime import timedelta
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pharma_erp.settings')
django.setup()

from django.contrib.auth import get_user_model
from apps.maintenance.models import Machine, MachineHistoricalMetrics, MaintenanceTicket, MachinePrediction
from apps.production.models import ProductionLog, ProductionTarget, MonthlyTarget, WarningLetter
from apps.inventory.models import WarehouseStock
from apps.logistics.models import Dispatch

User = get_user_model()

def seed():
    print("Clearing old data...")
    Machine.objects.all().delete()
    User.objects.all().delete()
    WarehouseStock.objects.all().delete()
    Dispatch.objects.all().delete()
    MonthlyTarget.objects.all().delete()
    WarningLetter.objects.all().delete()
    
    # 1. Create Users (29 Employees + 1 Admin + 1 PM)
    user = User.objects.create_user(username='Aniket', email='aniket@pharmaerp.com', password='Aniket@123', role='AD', is_superuser=True, is_staff=True)
    pm = User.objects.create_user(username='ProdManager', email='pm@pharmaerp.com', password='password123', role='PM')
    print("Created user: Aniket (Admin) and ProdManager (PM)")
    
    employees = []
    for i in range(1, 30):
        emp = User.objects.create_user(username=f'employee_{i}', email=f'emp{i}@pharmaerp.com', password='password123', role='EM')
        employees.append(emp)
    print("Created 29 employees")

    # 2. Create Machines (24 Machines)
    machines = []
    for i in range(1, 25):
        m = Machine.objects.create(code=f'M-{i:02d}', name=f'Machine-Alpha-{i:02d}', status='OP')
        machines.append(m)
    print("Created 24 machines")

    # 3. Create 40 days of Historical Data & Production Data
    today = timezone.now().date()
    start_date = today - timedelta(days=40)
    
    print("Generating 40 days of stable trend data...")
    
    # Initialize baseline metrics for each machine to create a stable trend
    machine_state = {}
    for m in machines:
        machine_state[m.code] = {
            'vib': 2.0,
            'temp': 60.0,
            'yield': 0.95
        }
        
    for i in range(40):
        current_date = start_date + timedelta(days=i)
        
        for m in machines:
            state = machine_state[m.code]
            
            # Random walk: small daily drifts instead of massive jumps
            state['vib'] += random.uniform(-0.1, 0.15)
            state['temp'] += random.uniform(-0.5, 0.6)
            state['yield'] += random.uniform(-0.01, 0.015)
            
            # Keep within logical physical bounds
            state['vib'] = max(1.2, min(state['vib'], 3.2))
            state['temp'] = max(50.0, min(state['temp'], 70.0))
            state['yield'] = max(0.85, min(state['yield'], 0.99))
            
            # Artificial spike for M-07 recently
            if m.code == 'M-07' and i > 35:
                state['vib'] += 0.5 
                state['temp'] += 3.0
                state['yield'] -= 0.03
                
            MachineHistoricalMetrics.objects.create(
                machine=m,
                date=current_date,
                vibration=state['vib'],
                temperature=state['temp'],
                output=random.uniform(240.0, 260.0)
            )
            
            # Production Log
            raw = 250.0 + random.uniform(-5.0, 5.0) # Stable raw material usage
            ProductionLog.objects.create(
                date=current_date,
                employee=random.choice(employees),
                machine=m,
                material_used=raw,
                output_kg=raw * state['yield']
            )
            
    # Set M-07 to PI (Pending Inspection)
    m07 = Machine.objects.get(code='M-07')
    m07.status = 'PI'
    m07.save()
    
    # 4. Predictions & Tickets
    MachinePrediction.objects.create(
        machine=m07,
        date=today,
        predicted_vibration=5.5,
        predicted_temp=82.0,
        reason='AI predicted high vibration (>5.0 mm/s)'
    )
    MaintenanceTicket.objects.create(
        machine=m07,
        cause='AI predicted high vibration (>5.0 mm/s)',
        status='O'
    )
    MaintenanceTicket.objects.create(
        machine=machines[2], # M-12
        cause='Motor replaced, waiting on final calibration run.',
        status='I'
    )
    # 5 Closed Tickets
    for i in range(5):
        MaintenanceTicket.objects.create(
            machine=machines[0],
            cause='Routine preventative maintenance completed. Filters changed.',
            status='C',
            closed_at=today - timedelta(days=random.randint(1, 10))
        )
    
    # 5. Inventory Stock
    stock_data = [
        {'material': 'Eucalyptus Pulp', 'qty': 14500, 'reorder': 5000, 'unit': 'kg'},
        {'material': 'Chemical Agent X-4', 'qty': 1200, 'reorder': 2000, 'unit': 'L'},
        {'material': 'Binding Agent Z', 'qty': 8400, 'reorder': 3000, 'unit': 'kg'},
        {'material': 'Cardboard Packaging', 'qty': 45000, 'reorder': 10000, 'unit': 'units'},
    ]
    for s in stock_data:
        WarehouseStock.objects.create(
            material=s['material'],
            quantity=s['qty'],
            reorder_level=s['reorder'],
            unit=s['unit']
        )
        
    # 6. Dispatches
    customers = ['Apollo Hospitals', 'MedLife Distributors', 'PharmaCorp EU', 'CareNet Health']
    gmaps_ids = ['ChIJydSuSkwVrjs', 'ChIJP3Sa8ziY', 'ChIJY_123456789', 'ChIJZ_987654321']
    for i in range(8):
        Dispatch.objects.create(
            transport_id=f"TR-884{90+i}",
            transporter='BlueDart Express',
            customer=random.choice(customers),
            quantity=random.randint(1000, 5000),
            maps_location_id=random.choice(gmaps_ids),
            cost=random.uniform(500, 2000)
        )

    # 7. Targets and Warnings
    MonthlyTarget.objects.create(
        month=today.replace(day=1),
        factory_target_kg=45000.0,
        bonus_amount=4500.0
    )
    
    # Randomly assign warnings to a few employees
    for i in range(3):
        WarningLetter.objects.create(
            employee=random.choice(employees),
            reason='Unexcused absenteeism and low daily yield.',
            issued_by=pm
        )

    print("Successfully seeded 40 days of data across all modules!")

if __name__ == '__main__':
    seed()
