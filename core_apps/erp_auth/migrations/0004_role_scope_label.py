from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp_auth", "0003_data_permission_policy")]
    operations = [
        migrations.AlterField(
            model_name="erprole",
            name="data_scope",
            field=models.CharField(
                choices=[("ALL", "全部数据"), ("SELF", "仅本人数据"), ("DEPARTMENT", "本部门及下级部门数据")],
                default="SELF",
                max_length=20,
                verbose_name="数据权限范围",
            ),
        )
    ]
