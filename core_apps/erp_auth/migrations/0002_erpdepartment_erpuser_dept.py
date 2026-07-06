import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("erp_auth", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ERPDepartment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, verbose_name="部门名称")),
                ("order", models.IntegerField(default=0, verbose_name="排序")),
                ("leader", models.CharField(blank=True, max_length=50, verbose_name="负责人")),
                ("phone", models.CharField(blank=True, max_length=20, verbose_name="联系电话")),
                ("email", models.EmailField(blank=True, max_length=254, verbose_name="邮箱")),
                ("status", models.BooleanField(default=True, verbose_name="状态")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="children",
                        to="erp_auth.erpdepartment",
                        verbose_name="上级部门",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="erp_departments",
                        to="tenant.tenant",
                        verbose_name="租户",
                    ),
                ),
            ],
            options={
                "verbose_name": "ERP 部门",
                "verbose_name_plural": "ERP 部门",
                "db_table": "erp_departments",
                "ordering": ["tenant_id", "order", "id"],
            },
        ),
        migrations.AddField(
            model_name="erpuser",
            name="dept",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="users",
                to="erp_auth.erpdepartment",
                verbose_name="所属部门",
            ),
        ),
        migrations.AddConstraint(
            model_name="erpdepartment",
            constraint=models.UniqueConstraint(
                fields=("tenant", "name"),
                name="uniq_erp_department_name_per_tenant",
            ),
        ),
    ]
