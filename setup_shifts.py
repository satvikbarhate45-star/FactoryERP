import os
import django
import random
from datetime import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pharma_erp.settings')
django.setup()

from apps.accounts.models import Shift, User

def run():
    # Create Shifts
    shifts_data = [
        {'name': 'Morning Shift', 'start_time': time(6, 0), 'end_time': time(14, 0)},
        {'name': 'Evening Shift', 'start_time': time(14, 0), 'end_time': time(22, 0)},
        {'name': 'Night Shift', 'start_time': time(22, 0), 'end_time': time(6, 0)},
    ]
    
    db_shifts = []
    for s in shifts_data:
        shift, created = Shift.objects.get_or_create(name=s['name'], defaults={'start_time': s['start_time'], 'end_time': s['end_time']})
        db_shifts.append(shift)
        
    print("Shifts created/verified in Database.")

    # Assign all employees to a random shift to populate the database
    employees = User.objects.filter(is_superuser=False)
    for i, emp in enumerate(employees):
        emp.shift = db_shifts[i % len(db_shifts)]
        emp.save()
        
    print(f"Successfully assigned {employees.count()} employees to Morning, Evening, and Night shifts in the database!")

if __name__ == '__main__':
    run()
