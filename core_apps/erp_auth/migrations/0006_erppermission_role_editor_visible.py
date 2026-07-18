from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp_auth", "0005_remove_is_super_admin")]

    operations = [
        migrations.AddField(
            model_name="erppermission",
            name="role_editor_visible",
            field=models.BooleanField(default=True, verbose_name="在角色编辑器中显示"),
        ),
    ]
