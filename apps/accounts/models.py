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

    class KYCStatus(models.TextChoices):
        PENDING = 'PENDING', _('Pending')
        APPROVED = 'APPROVED', _('Approved')
        REJECTED = 'REJECTED', _('Rejected')

    role = models.CharField(max_length=2, choices=Role.choices, default=Role.EMPLOYEE)
    language = models.CharField(max_length=10, default='en')
    theme = models.CharField(max_length=10, default='light')
    shift = models.ForeignKey(Shift, on_delete=models.SET_NULL, null=True, blank=True)
    machine = models.ForeignKey(Machine, on_delete=models.SET_NULL, null=True, blank=True)
    supervisor = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='allocated_employees')

    # Employee KYC Verification & Approval Fields
    kyc_status = models.CharField(
        max_length=10,
        choices=KYCStatus.choices,
        default=KYCStatus.PENDING,
        db_index=True
    )
    rejection_reason = models.TextField(blank=True, null=True)
    phone = models.CharField(max_length=25, blank=True, null=True)
    whatsapp = models.CharField(max_length=25, blank=True, null=True)
    pan = models.CharField(max_length=20, blank=True, null=True)
    government_id = models.CharField(max_length=50, blank=True, null=True)
    account_number = models.CharField(max_length=50, blank=True, null=True)
    ifsc = models.CharField(max_length=20, blank=True, null=True)
    photo = models.ImageField(upload_to='kyc_photos/', blank=True, null=True)
    kyc_submitted_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    kyc_reviewed_at = models.DateTimeField(null=True, blank=True)
    kyc_reviewed_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_kycs'
    )

    def save(self, *args, **kwargs):
        if not self.kyc_status:
            self.kyc_status = self.KYCStatus.PENDING
        super().save(*args, **kwargs)

