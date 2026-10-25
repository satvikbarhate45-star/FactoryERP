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
