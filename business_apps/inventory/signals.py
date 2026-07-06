from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Product

@receiver(post_save, sender=Product)
def product_saved_handler(sender, instance, created, **kwargs):
    """
    Example signal handler. 
    In a real ERP, this might notify the finance module to update asset valuation.
    """
    if created:
        print(f"Signal: New product created: {instance.name}")
    else:
        print(f"Signal: Product updated: {instance.name}")
