from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("erp_auth", "0002_erpdepartment_erpuser_dept"), ("tenant", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="ERPDataPermissionPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("resource_code", models.CharField(max_length=100, verbose_name="数据资源标识")),
                ("permission_type", models.CharField(choices=[("BASIC", "基础数据"), ("BUSINESS", "业务数据"), ("SPECIAL", "特殊数据")], max_length=20, verbose_name="数据权限类型")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="erp_data_permission_policies", to="tenant.tenant")),
            ],
            options={"db_table": "erp_data_permission_policies"},
        ),
        migrations.CreateModel(
            name="ERPDataSpecialGrant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("resource_code", models.CharField(max_length=100, verbose_name="数据资源标识")),
                ("object_id", models.CharField(max_length=64, verbose_name="授权对象标识")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("department", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="data_special_grants", to="erp_auth.erpdepartment")),
                ("role", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="data_special_grants", to="erp_auth.erprole")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="erp_data_special_grants", to="tenant.tenant")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="data_special_grants", to="erp_auth.erpuser")),
            ],
            options={"db_table": "erp_data_special_grants"},
        ),
        migrations.AddConstraint(model_name="erpdatapermissionpolicy", constraint=models.UniqueConstraint(fields=("tenant", "resource_code"), name="uniq_erp_data_policy_per_tenant")),
        migrations.AddIndex(model_name="erpdataspecialgrant", index=models.Index(fields=["tenant", "resource_code", "object_id"], name="erp_data_sp_tenant_94a421_idx")),
    ]
