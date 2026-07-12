from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0008_alter_inventorytransaction_operator_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="stocktake",
            name="approved_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="审核时间"),
        ),
        migrations.AddField(
            model_name="stocktake",
            name="approved_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name="approved_stocktakes", to=settings.AUTH_USER_MODEL, verbose_name="审核人"),
        ),
        migrations.AddField(
            model_name="stocktake",
            name="submitted_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="提交时间"),
        ),
        migrations.AddField(
            model_name="stocktake",
            name="submitted_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name="submitted_stocktakes", to=settings.AUTH_USER_MODEL, verbose_name="提交人"),
        ),
        migrations.AlterField(
            model_name="stocktake",
            name="status",
            field=models.CharField(choices=[("DRAFT", "草稿"), ("IN_PROGRESS", "盘点中"), ("PENDING_APPROVAL", "待审核"), ("APPROVED", "已审核"), ("COMPLETED", "已完成"), ("CANCELLED", "已取消")], default="DRAFT", max_length=20, verbose_name="状态"),
        ),
    ]
