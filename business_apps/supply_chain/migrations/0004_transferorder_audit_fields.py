from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('supply_chain', '0003_outboundorderitem_sales_order_item'),
    ]

    operations = [
        migrations.AddField(
            model_name='transferorder',
            name='submitted_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='提交时间'),
        ),
        migrations.AddField(
            model_name='transferorder',
            name='submitted_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='submitted_transfer_orders', to=settings.AUTH_USER_MODEL, verbose_name='提交人'),
        ),
        migrations.AddField(
            model_name='transferorder',
            name='approved_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='审核时间'),
        ),
        migrations.AddField(
            model_name='transferorder',
            name='approved_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approved_transfer_orders', to=settings.AUTH_USER_MODEL, verbose_name='审核人'),
        ),
        migrations.AddField(
            model_name='transferorder',
            name='outbound_confirmed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='调出确认时间'),
        ),
        migrations.AddField(
            model_name='transferorder',
            name='outbound_confirmed_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='outbound_confirmed_transfer_orders', to=settings.AUTH_USER_MODEL, verbose_name='调出确认人'),
        ),
        migrations.AddField(
            model_name='transferorder',
            name='inbound_confirmed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='调入确认时间'),
        ),
        migrations.AddField(
            model_name='transferorder',
            name='inbound_confirmed_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='inbound_confirmed_transfer_orders', to=settings.AUTH_USER_MODEL, verbose_name='调入确认人'),
        ),
    ]
