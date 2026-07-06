from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from business_apps.supply_chain.models import OutboundOrder
from core_apps.policies.registry import get_policy
from .services import ARService


_outbound_status_cache = {}


@receiver(pre_save, sender=OutboundOrder)
def cache_outbound_status(sender, instance, **kwargs):
    if not instance.pk:
        return
    try:
        _outbound_status_cache[instance.pk] = OutboundOrder.objects.get(pk=instance.pk).status
    except OutboundOrder.DoesNotExist:
        pass


@receiver(post_save, sender=OutboundOrder)
def on_outbound_order_completed(sender, instance, created, **kwargs):
    if instance.status != 'COMPLETED' or not instance.sales_order_id:
        return

    old_status = None if created else _outbound_status_cache.pop(instance.pk, None)
    if old_status == 'COMPLETED':
        return

    try:
        sales_policy = get_policy("sales", user=instance.created_by)
        ar_policy = get_policy("ar_receivable", user=instance.created_by)
        if not sales_policy.outbound_auto_ar_enabled() or not ar_policy.auto_create_receivable_enabled():
            return
        ARService.generate_ar_from_outbound(instance, instance.created_by)
    except ValueError:
        # Existing service enforces duplicate and status checks.
        pass
