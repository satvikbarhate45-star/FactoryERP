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
    supervisor = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='allocated_employees')
