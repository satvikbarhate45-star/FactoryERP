import os
import django
import random
from datetime import timedelta
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pharma_erp.settings')
django.setup()

from apps.accounts.models import User
from apps.maintenance.models import Machine, MachineHistoricalMetrics, MaintenanceTicket
from apps.inventory.models import WarehouseStock, InwardShipment
from apps.production.models import ProductionLog, ProductionTarget, MonthlyTarget, Bonus, Complaint, LeaveRequest

def seed_data():
    today = timezone.now().date()
    start_date = today - timedelta(days=40)
    
    users = list(User.objects.all())
    machines = list(Machine.objects.all())
    
    # 1. Warehouse / Inventory Seed
    print("Seeding Warehouse data...")
    materials = [
        ("Active Pharmaceutical Ingredient A", "kg", 500.00),
        ("Active Pharmaceutical Ingredient B", "kg", 200.00),
        ("Excipient Alpha", "kg", 1000.00),
        ("Excipient Beta", "kg", 800.00),
        ("Coating Solution", "L", 300.00),
        ("Packaging Blisters", "units", 50000.00),
    ]
    
    stocks = []
    for mat_name, unit, reorder in materials:
        stock, _ = WarehouseStock.objects.get_or_create(
            material=mat_name,
            defaults={
                'quantity': random.uniform(reorder * 1.5, reorder * 5),
                'unit': unit,
                'reorder_level': reorder
            }
        )
        stocks.append(stock)
        
    for i in range(41):
        d = start_date + timedelta(days=i)
        # Random inward shipments
        if random.random() > 0.7:
            InwardShipment.objects.create(
                supplier=f"Supplier {random.choice(['GlobalChem', 'MedSupply', 'PharmaMat'])}",
                material=random.choice(stocks),
                quantity=random.uniform(100, 1000),
                cost=random.uniform(5000, 50000),
                received_on=d
            )

    # 2. Maintenance Seed (Historical Metrics & Tickets)
    print("Seeding Maintenance data...")
    for machine in machines:
        # Base stats per machine type
        base_temp = 60.0
        base_vib = 2.0
        
        for i in range(41):
            d = start_date + timedelta(days=i)
            
            # Find matching production log to sync metrics
            plog = ProductionLog.objects.filter(machine=machine, date=d).first()
            output = float(plog.output_kg) if plog else random.uniform(100, 300)
            
            # Generate metrics
            temp = base_temp + (output * 0.05) + random.uniform(-2, 2)
            vib = base_vib + (output * 0.005) + random.uniform(-0.5, 0.5)
            
            # Create metric
            MachineHistoricalMetrics.objects.get_or_create(
                machine=machine,
                date=d,
                defaults={
                    'temperature': temp,
                    'vibration': vib,
                    'output': output
                }
            )
            
            # Occasional ticket
            if random.random() > 0.98: # 2% chance per day per machine
                MaintenanceTicket.objects.create(
                    machine=machine,
                    cause=f"Routine check requested by operator due to abnormal noise.",
                    status='C' if (today - d).days > 3 else 'O',
                    opened_at=timezone.now() - timedelta(days=(today-d).days)
                )

    # 3. Production / HR Seed
    print("Seeding HR / Production Targets...")
    operators = [u for u in users if u.role == 'EM']
    supervisors = [u for u in users if u.role == 'SU']
    
    if not supervisors: supervisors = users
    if not operators: operators = users
    
    # Monthly Targets
    month_start = today.replace(day=1)
    prev_month_start = (month_start - timedelta(days=1)).replace(day=1)
    
    MonthlyTarget.objects.get_or_create(month=month_start, defaults={'factory_target_kg': 150000, 'bonus_amount': 500})
    MonthlyTarget.objects.get_or_create(month=prev_month_start, defaults={'factory_target_kg': 140000, 'bonus_amount': 400})
    
    for i in range(41):
        d = start_date + timedelta(days=i)
        
        # Leaves & Complaints
        if random.random() > 0.8:
            LeaveRequest.objects.create(
                employee=random.choice(users),
                start_date=d,
                end_date=d + timedelta(days=random.randint(1,3)),
                reason="Personal/Medical Leave",
                status=random.choice(['A', 'R', 'P']),
                reviewed_by=random.choice(supervisors)
            )
            
        if random.random() > 0.95:
            Complaint.objects.create(
                employee=random.choice(operators),
                machine=random.choice(machines),
                description="Minor issue with control panel responding slowly.",
                status=random.choice(['O', 'R'])
            )

    print("All modules seeded successfully with 40 days of historical data!")

if __name__ == '__main__':
    seed_data()
