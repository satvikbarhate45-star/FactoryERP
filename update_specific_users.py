import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pharma_erp.settings')
django.setup()

from apps.accounts.models import User

# Data to update
updates = [
    {'role': 'PM', 'first_name': 'Pooja', 'last_name': 'Chine', 'email': 'pooja.chine@pharmaerp.local', 'username': 'pchine'},
    {'role': 'MA', 'first_name': 'Shyam', 'last_name': 'Chavan', 'email': 'shyam.chavan@pharmaerp.local', 'username': 'schavan'},
    {'role': 'LO', 'first_name': 'Krishna', 'last_name': 'Borbane', 'email': 'krishna.borbane@pharmaerp.local', 'username': 'kborbane'},
    {'role': 'SU', 'first_name': 'Ritesh', 'last_name': 'Dhakate', 'email': 'ritesh.dhakate@pharmaerp.local', 'username': 'rdhakate'},
]

for item in updates:
    user = User.objects.filter(role=item['role']).exclude(is_superuser=True).first()
    if not user:
        user = User(role=item['role'])
        user.set_password('password123')
    
    user.first_name = item['first_name']
    user.last_name = item['last_name']
    user.email = item['email']
    user.username = item['username']
    user.save()
    print(f"Updated {item['role']} to {item['first_name']} {item['last_name']} (Username: {item['username']})")

print("User update complete.")
