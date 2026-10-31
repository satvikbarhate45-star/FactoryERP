from django.db import models

class Dispatch(models.Model):
    customer = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    transport_id = models.CharField(max_length=100)
    transporter = models.CharField(max_length=200)
    maps_location_id = models.CharField(max_length=200)
    cost = models.DecimalField(max_digits=12, decimal_places=2)
    dispatch_type = models.CharField(max_length=20, default='EXPORT')
    is_automated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
