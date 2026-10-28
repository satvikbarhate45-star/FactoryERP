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
    is_auto_predicted = models.BooleanField(default=False)
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

class WarningLetter(models.Model):
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='warnings')
    reason = models.TextField()
    issued_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class MaterialRequest(models.Model):
    material_name = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    months_supply = models.IntegerField(default=1)
    status = models.CharField(max_length=20, default='Pending')
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class SystemOverview(models.Model):
    date = models.DateField(unique=True)
    total_output_kg = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    total_material_used_kg = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    active_machines_count = models.IntegerField(null=True, blank=True)
    is_auto_filled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class SystemAlert(models.Model):
    class AlertType(models.TextChoices):
        CRITICAL = 'CRITICAL', _('Critical Warning')
        LOW_STOCK = 'LOW_STOCK', _('Low Stock Warning')
        LOW_EFFICIENCY = 'LOW_EFFICIENCY', _('Low Efficiency Alert')

    alert_type = models.CharField(max_length=20, choices=AlertType.choices)
    message = models.TextField()
    decision_taken = models.TextField(null=True, blank=True)
    is_autonomous = models.BooleanField(default=True)
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

class SalaryPayroll(models.Model):
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payrolls')
    base_salary = models.DecimalField(max_digits=10, decimal_places=2)
    target_assigned = models.DecimalField(max_digits=10, decimal_places=2)
    actual_output = models.DecimalField(max_digits=10, decimal_places=2)
    completion_percentage = models.DecimalField(max_digits=10, decimal_places=2)
    salary_adjusted = models.DecimalField(max_digits=10, decimal_places=2)
    is_incremented = models.BooleanField(default=False)
    payout_date = models.DateField()
    is_auto_predicted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

