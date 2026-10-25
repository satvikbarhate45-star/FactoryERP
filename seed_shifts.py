import os
import django
import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pharma_erp.settings')
django.setup()

from apps.accounts.models import Shift

shifts = [
    {"name": "Morning", "start": datetime.time(6, 0), "end": datetime.time(14, 0)},
    {"name": "Evening", "start": datetime.time(15, 0), "end": datetime.time(23, 0)},
    {"name": "Night", "start": datetime.time(21, 0), "end": datetime.time(5, 0)},
]

for s in shifts:
    Shift.objects.get_or_create(
        name=s["name"],
        defaults={
            "start_time": s["start"],
            "end_time": s["end"]
        }
    )
    print(f"Ensured shift exists: {s['name']}")
