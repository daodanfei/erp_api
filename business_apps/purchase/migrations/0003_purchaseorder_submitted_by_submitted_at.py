from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('purchase', '0002_rename_purchase_approval_po_idx_purchase_pu_purchas_38a19d_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchaseorder',
            name='submitted_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='提交时间'),
        ),
        migrations.AddField(
            model_name='purchaseorder',
            name='submitted_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='submitted_purchase_orders', to=settings.AUTH_USER_MODEL, verbose_name='提交人'),
        ),
    ]
