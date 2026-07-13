from django.db import migrations


def bind_legacy_super_admin_roles(apps, schema_editor):
    ERPUser = apps.get_model("erp_auth", "ERPUser")
    ERPRole = apps.get_model("erp_auth", "ERPRole")
    ERPPermission = apps.get_model("erp_auth", "ERPPermission")

    all_permission_ids = list(ERPPermission.objects.values_list("id", flat=True))
    for user in ERPUser.objects.filter(is_super_admin=True):
        role = user.roles.filter(is_system=True, data_scope="ALL").order_by("id").first()
        if role is None:
            role, _ = ERPRole.objects.get_or_create(
                tenant_id=user.tenant_id,
                code=f"tenant-{user.tenant_id}-tenant-admin",
                defaults={
                    "name": "租户超级管理员",
                    "data_scope": "ALL",
                    "status": True,
                    "is_system": True,
                },
            )
        role.name = "租户超级管理员"
        role.data_scope = "ALL"
        role.status = True
        role.is_system = True
        role.save(update_fields=["name", "data_scope", "status", "is_system"])
        role.permissions.set(all_permission_ids)
        user.roles.add(role)


class Migration(migrations.Migration):
    dependencies = [("erp_auth", "0004_role_scope_label")]

    operations = [
        migrations.RunPython(bind_legacy_super_admin_roles, migrations.RunPython.noop),
        migrations.RemoveField(model_name="erpuser", name="is_super_admin"),
    ]
