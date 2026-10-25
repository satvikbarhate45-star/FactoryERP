from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _

# ==========================================
# MODULE 1: AUTHENTICATION & ACCESS CONTROL
# ==========================================

class Shift(models.Model):
    name = models.CharField(max_length=50) # e.g., Morning, Evening, Night
    start_time = models.TimeField()
    end_time = models.TimeField()

    def __str__(self):
        return self.name

class Machine(models.Model):
    class Status(models.TextChoices):
        OPERATIONAL = 'OP', _('Operational')
        PENDING_INSPECTION = 'PI', _('Pending Inspection')
        UNDER_MAINTENANCE = 'UM', _('Under Maintenance')

    code = models.CharField(max_length=20, unique=True) # e.g., M-03
    name = models.CharField(max_length=100)
    status = models.CharField(max_length=2, choices=Status.choices, default=Status.OPERATIONAL)
    last_inspection = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.code} - {self.name}"

class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'AD', _('Admin')
        PROD_MANAGER = 'PM', _('Production Manager')
        SUPERVISOR = 'SU', _('Supervisor')
        EMPLOYEE = 'EM', _('Employee')
        LOGISTICS = 'LO', _('Logistics')
        MAINTENANCE = 'MA', _('Maintenance')

    role = models.CharField(max_length=2, choices=Role.choices, default=Role.EMPLOYEE)
    language = models.CharField(max_length=10, default='en') # en, hi, mr
    theme = models.CharField(max_length=10, default='light') # light, dark
    
    # Optional fields as not all roles will have a specific shift or machine
    shift = models.ForeignKey(Shift, on_delete=models.SET_NULL, null=True, blank=True)
    machine = models.ForeignKey(Machine, on_delete=models.SET_NULL, null=True, blank=True)


# ==========================================
# MODULE 2: EMPLOYEE PORTAL & FLOOR EXECUTION
# ==========================================

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


# ==========================================
# MODULE 3: PRODUCTION TARGET AUTOMATION
# ==========================================

class ProductionTarget(models.Model):
    date = models.DateField()
    employee = models.ForeignKey(User, on_delete=models.CASCADE)
    target_kg = models.DecimalField(max_digits=10, decimal_places=2)
    set_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='set_targets')
    is_rollover = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class MonthlyTarget(models.Model):
    month = models.DateField() # Store the first day of the month
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


# ==========================================
# MODULE 4: PREDICTIVE DOWNTIME ENGINE
# ==========================================

class MachineHistoricalMetrics(models.Model):
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE)
    date = models.DateField()
    temperature = models.DecimalField(max_digits=6, decimal_places=2)
    vibration = models.DecimalField(max_digits=6, decimal_places=2)
    output = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['machine', 'date']),
        ]

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


# ==========================================
# MODULE 5 & 6: WAREHOUSE, LOGISTICS & DISPATCH
# ==========================================

class WarehouseStock(models.Model):
    material = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit = models.CharField(max_length=20) # e.g., kg, liters
    reorder_level = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.material} ({self.quantity} {self.unit})"

class InwardShipment(models.Model):
    supplier = models.CharField(max_length=200)
    material = models.ForeignKey(WarehouseStock, on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    cost = models.DecimalField(max_digits=12, decimal_places=2)
    received_on = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

class Dispatch(models.Model):
    customer = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    transport_id = models.CharField(max_length=100)
    transporter = models.CharField(max_length=200)
    maps_location_id = models.CharField(max_length=200)
    cost = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)


# ==========================================
# MODULE 7: AI CHATBOT & LOGS
# ==========================================

class ChatLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    prompt = models.TextField()
    response = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
