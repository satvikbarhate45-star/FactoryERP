from django.db import models
from django.utils.translation import gettext_lazy as _

class Machine(models.Model):
    class Status(models.TextChoices):
        OPERATIONAL = 'OP', _('Operational')
        PENDING_INSPECTION = 'PI', _('Pending Inspection')
        UNDER_MAINTENANCE = 'UM', _('Under Maintenance')

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    model_name = models.CharField(max_length=100, blank=True, null=True)
    featured_for = models.CharField(max_length=200, blank=True, null=True)
    ai_enabled = models.BooleanField(default=True, verbose_name="Gemini Smart Analytics Enabled")
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
