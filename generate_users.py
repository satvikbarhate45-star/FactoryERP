import os
import django
import random

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pharma_erp.settings')
django.setup()

from apps.accounts.models import User
from apps.production.models import ProductionLog

def generate_users_and_update_history():
    print("Generating 32 new users...")

    roles_distribution = {
        'MA': 5, # Maintenance
        'SU': 4, # Supervisor
        'PM': 3, # Production Manager
        'EM': 15, # Operator (Equipment Manager)
        'LO': 5  # Logistics
    }

    names = [
        "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Ayaan", "Krishna", "Ishaan",
        "Shaurya", "Atharv", "Advik", "Pranav", "Kabir", "Ritvik", "Aarush", "Dhruv", "Rudra", "Aryan",
        "Diya", "Aadhya", "Ananya", "Navya", "Kavya", "Myra", "Saanvi", "Pari", "Ira", "Riya", "Aarohi", "Zara"
    ]

    surnames = [
        "Sharma", "Verma", "Patel", "Gupta", "Singh", "Kumar", "Das", "Bose", "Jain", "Mehta"
    ]

    new_users = []
    name_idx = 0
    
    for role, count in roles_distribution.items():
        for _ in range(count):
            if name_idx < len(names):
                first_name = names[name_idx]
            else:
                first_name = f"User{name_idx}"
                
            last_name = random.choice(surnames)
            username = f"{first_name.lower()}.{last_name.lower()}{random.randint(10,99)}"
            email = f"{username}@pharmaerp.com"
            
            user, created = User.objects.get_or_create(username=username, defaults={
                'email': email,
                'first_name': first_name,
                'last_name': last_name,
                'role': role,
                'is_active': True # Auto approve KYC
            })
            if created:
                user.set_password("1234")
                user.save()
                
            new_users.append(user)
            name_idx += 1
            
    print(f"Created {len(new_users)} users.")

    # Re-assign history
    print("Updating production logs history...")
    operators = [u for u in new_users if u.role == 'EM']
    if not operators:
        operators = new_users # Fallback
        
    logs = ProductionLog.objects.all()
    updated_count = 0
    for log in logs:
        log.employee = random.choice(operators)
        log.save()
        updated_count += 1
        
    print(f"Successfully reassigned {updated_count} production logs to the new operators.")

if __name__ == '__main__':
    generate_users_and_update_history()
