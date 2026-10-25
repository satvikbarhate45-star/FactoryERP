import os

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content.strip() + '\n')

def update_models():
    # 1. MAINTENANCE APP (Needs to be first so accounts.User can reference Machine)
    write_file('apps/maintenance/models.py', '''
from django.db import models
from django.utils.translation import gettext_lazy as _

class Machine(models.Model):
    class Status(models.TextChoices):
        OPERATIONAL = 'OP', _('Operational')
        PENDING_INSPECTION = 'PI', _('Pending Inspection')
        UNDER_MAINTENANCE = 'UM', _('Under Maintenance')

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    status = models.CharField(max_length=2, choices=Status.choices, default=Status.OPERATIONAL)
    last_inspection = models.DateTimeField(null=True, blank=True)

class MachineHistoricalMetrics(models.Model):
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE)
    date = models.DateField()
    temperature = models.DecimalField(max_digits=6, decimal_places=2)
    vibration = models.DecimalField(max_digits=6, decimal_places=2)
    output = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        indexes = [models.Index(fields=['machine', 'date'])]

class MachinePrediction(models.Model):
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE)
    date = models.DateField()
    predicted_temp = models.DecimalField(max_digits=6, decimal_places=2)
    predicted_vibration = models.DecimalField(max_digits=6, decimal_places=2)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class MaintenanceTicket(models.Model):
    class Status(models.TextChoices):
        OPEN = 'O', _('Open')
        IN_PROGRESS = 'I', _('In Progress')
        CLOSED = 'C', _('Closed')
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE)
    cause = models.TextField()
    status = models.CharField(max_length=1, choices=Status.choices, default=Status.OPEN)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    downtime_min = models.IntegerField(default=0)
''')

    # 2. ACCOUNTS APP
    write_file('apps/accounts/models.py', '''
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _
from apps.maintenance.models import Machine

class Shift(models.Model):
    name = models.CharField(max_length=50)
    start_time = models.TimeField()
    end_time = models.TimeField()

class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'AD', _('Admin')
        PROD_MANAGER = 'PM', _('Production Manager')
        SUPERVISOR = 'SU', _('Supervisor')
        EMPLOYEE = 'EM', _('Employee')
        LOGISTICS = 'LO', _('Logistics')
        MAINTENANCE = 'MA', _('Maintenance')

    role = models.CharField(max_length=2, choices=Role.choices, default=Role.EMPLOYEE)
    language = models.CharField(max_length=10, default='en')
    theme = models.CharField(max_length=10, default='light')
    shift = models.ForeignKey(Shift, on_delete=models.SET_NULL, null=True, blank=True)
    machine = models.ForeignKey(Machine, on_delete=models.SET_NULL, null=True, blank=True)
''')

    # 3. PRODUCTION APP
    write_file('apps/production/models.py', '''
from django.db import models
from django.utils.translation import gettext_lazy as _
from apps.accounts.models import User
from apps.maintenance.models import Machine

class ProductionLog(models.Model):
    date = models.DateField()
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='production_logs')
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE)
    output_kg = models.DecimalField(max_digits=10, decimal_places=2)
    material_used = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class LeaveRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'P', _('Pending')
        APPROVED = 'A', _('Approved')
        REJECTED = 'R', _('Rejected')
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='leave_requests')
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    status = models.CharField(max_length=1, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_leaves')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Complaint(models.Model):
    class Status(models.TextChoices):
        OPEN = 'O', _('Open')
        IN_PROGRESS = 'I', _('In Progress')
        RESOLVED = 'R', _('Resolved')
    employee = models.ForeignKey(User, on_delete=models.CASCADE)
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, null=True, blank=True)
    description = models.TextField()
    status = models.CharField(max_length=1, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class ProductionTarget(models.Model):
    date = models.DateField()
    employee = models.ForeignKey(User, on_delete=models.CASCADE)
    target_kg = models.DecimalField(max_digits=10, decimal_places=2)
    set_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='set_targets')
    is_rollover = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class MonthlyTarget(models.Model):
    month = models.DateField()
    factory_target_kg = models.DecimalField(max_digits=12, decimal_places=2)
    bonus_amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Bonus(models.Model):
    class Status(models.TextChoices):
        PENDING = 'P', _('Pending')
        PAID = 'D', _('Paid')
    employee = models.ForeignKey(User, on_delete=models.CASCADE)
    month = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=1, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
''')

    # 4. INVENTORY APP
    write_file('apps/inventory/models.py', '''
from django.db import models

class WarehouseStock(models.Model):
    material = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit = models.CharField(max_length=20)
    reorder_level = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class InwardShipment(models.Model):
    supplier = models.CharField(max_length=200)
    material = models.ForeignKey(WarehouseStock, on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    cost = models.DecimalField(max_digits=12, decimal_places=2)
    received_on = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
''')

    # 5. LOGISTICS APP
    write_file('apps/logistics/__init__.py', '')
    write_file('apps/logistics/apps.py', '''
from django.apps import AppConfig
class LogisticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.logistics'
''')
    write_file('apps/logistics/models.py', '''
from django.db import models

class Dispatch(models.Model):
    customer = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    transport_id = models.CharField(max_length=100)
    transporter = models.CharField(max_length=200)
    maps_location_id = models.CharField(max_length=200)
    cost = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
''')

    # 6. AI CHAT APP
    write_file('apps/ai_chat/__init__.py', '')
    write_file('apps/ai_chat/apps.py', '''
from django.apps import AppConfig
class AiChatConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.ai_chat'
''')
    write_file('apps/ai_chat/models.py', '''
from django.db import models
from apps.accounts.models import User

class ChatLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    prompt = models.TextField()
    response = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
''')

    # 7. Update Settings
    with open('pharma_erp/settings.py', 'r') as f:
        content = f.read()
    if "'apps.logistics'," not in content:
        content = content.replace("'apps.inventory',", "'apps.inventory',\n    'apps.logistics',\n    'apps.ai_chat',")
    with open('pharma_erp/settings.py', 'w') as f:
        f.write(content)

if __name__ == '__main__':
    update_models()
    print("Models updated.")
