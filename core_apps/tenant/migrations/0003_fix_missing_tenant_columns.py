from django.db import migrations


def add_missing_tenant_columns(apps, schema_editor):
    Tenant = apps.get_model("tenant", "Tenant")
    table_name = Tenant._meta.db_table
    existing_columns = {
        column.name
        for column in schema_editor.connection.introspection.get_table_description(
            schema_editor.connection.cursor(),
            table_name,
        )
    }
    for field_name in ("instance", "user_limit"):
        field = Tenant._meta.get_field(field_name)
        if field.column not in existing_columns:
            schema_editor.add_field(Tenant, field)


class Migration(migrations.Migration):

    dependencies = [
        ("tenant", "0002_tenant_instance_tenant_user_limit"),
        ("blueprints", "0003_alter_systeminstance_status"),
    ]

    operations = [
        migrations.RunPython(add_missing_tenant_columns, migrations.RunPython.noop),
    ]
