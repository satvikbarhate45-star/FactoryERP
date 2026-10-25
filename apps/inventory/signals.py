from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import InwardShipment

@receiver(post_save, sender=InwardShipment)
def increase_stock_on_inward_shipment(sender, instance, created, **kwargs):
    if created:
        instance.material.quantity += instance.quantity
        instance.material.save()
        print(f"[INBOUND SYNC] Automatically increased warehouse stock for {instance.material.material} by {instance.quantity} {instance.material.unit}.")
