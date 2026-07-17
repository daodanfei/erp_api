from django.db.models import Q
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from core_apps.common.permissions import ERPActionPermission, ERPUserOnly, ModuleEnabledPermission
from core_apps.common.utils.data_scope import get_data_scope_filter
from core_apps.erp_auth.models import ERPUser
from core_apps.system.operation_log import OperationLogModelViewSetMixin
from core_apps.tenant.models import Tenant


def _collect_erp_tenant_paths(model, *, depth: int = 2, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for field in model._meta.get_fields():
        if getattr(field, "auto_created", False) or not getattr(field, "is_relation", False):
            continue
        remote_field = getattr(field, "remote_field", None)
        remote_model = getattr(remote_field, "model", None)
        if remote_model is None:
            continue
        current_path = f"{prefix}{field.name}"
        if remote_model is Tenant:
            paths.add(current_path)
            continue
        if remote_model is ERPUser:
            paths.add(f"{current_path}__tenant")
            continue
        if depth <= 0 or not hasattr(remote_model, "_meta"):
            continue
        paths.update(_collect_erp_tenant_paths(remote_model, depth=depth - 1, prefix=f"{current_path}__"))
    return paths


def apply_erp_tenant_scope(queryset, *, user):
    if not isinstance(user, ERPUser):
        return queryset
    tenant_filter = Q()
    for path in sorted(_collect_erp_tenant_paths(queryset.model)):
        tenant_filter |= Q(**{path: user.tenant})
    if not tenant_filter.children:
        return queryset
    return queryset.filter(tenant_filter).distinct()


def build_erp_tenant_save_kwargs(model, *, user) -> dict:
    if not isinstance(user, ERPUser):
        return {}
    try:
        tenant_field = model._meta.get_field("tenant")
    except Exception:
        return {}
    remote_model = getattr(getattr(tenant_field, "remote_field", None), "model", None)
    if remote_model is not Tenant:
        return {}
    return {"tenant": user.tenant}


def validate_erp_related_tenant_scope(model, *, validated_data: dict, user) -> None:
    if not isinstance(user, ERPUser):
        return
    tenant = user.tenant
    for field in model._meta.get_fields():
        if getattr(field, "auto_created", False) or not getattr(field, "is_relation", False):
            continue
        if field.name not in validated_data:
            continue
        related_obj = validated_data[field.name]
        if getattr(field, "many_to_many", False):
            invalid_related = [
                obj for obj in related_obj
                if getattr(obj, "tenant_id", None) is not None and getattr(obj, "tenant_id", None) != tenant.id
            ]
            if invalid_related:
                raise ValidationError({field.name: "不能关联其他租户的数据"})
            continue
        related_tenant_id = getattr(related_obj, "tenant_id", None)
        if related_tenant_id is not None and related_tenant_id != tenant.id:
            raise ValidationError({field.name: "不能关联其他租户的数据"})


class ModuleAwareModelViewSet(OperationLogModelViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [ERPUserOnly, ModuleEnabledPermission, ERPActionPermission]
    module_key = ""
    data_permission_default_type = "BASIC"
    data_permission_resource = ""
    special_scope_field = "pk"

    def get_tenant_scoped_queryset(self):
        queryset = super().get_queryset()
        return apply_erp_tenant_scope(queryset, user=self.request.user)

    def get_scoped_related_queryset(self, queryset):
        queryset = apply_erp_tenant_scope(queryset, user=self.request.user)
        return self.apply_related_data_permission_scope(queryset)

    def get_tenant_scoped_related_object(self, queryset, **lookup):
        """Resolve a selectable relation inside the current tenant only."""
        return apply_erp_tenant_scope(queryset, user=self.request.user).get(**lookup)

    def apply_related_data_permission_scope(self, queryset):
        from core_apps.erp_auth.data_permissions import BUSINESS, RESOURCE_BY_CODE, SPECIAL, get_resource_code, get_special_scope_q, resolve_permission_type

        resource_code = get_resource_code(queryset.model)
        definition = RESOURCE_BY_CODE.get(resource_code)
        if definition is None:
            return queryset
        permission_type = resolve_permission_type(
            user=self.request.user, resource_code=resource_code, default_type=definition.default_type
        )
        if permission_type == BUSINESS:
            return queryset.filter(get_data_scope_filter(
                self.request.user,
                dept_field=definition.business_dept_field,
                user_field=definition.business_user_field,
            )).distinct()
        if permission_type == SPECIAL:
            return queryset.filter(get_special_scope_q(
                user=self.request.user,
                resource_code=resource_code,
                scope_field=definition.special_scope_field,
            )).distinct()
        return queryset

    def get_scoped_related_object(self, queryset, **lookup):
        return self.get_scoped_related_queryset(queryset).get(**lookup)

    def get_queryset(self):
        return self.get_data_permission_scoped_queryset()

    def get_data_permission_scoped_queryset(self):
        queryset = self.get_tenant_scoped_queryset()
        if getattr(self, "action", None) == "reference_options":
            return queryset
        return self.apply_data_permission_scope(queryset)

    def get_data_permission_type(self, queryset=None):
        from core_apps.erp_auth.data_permissions import get_resource_code, resolve_permission_type

        queryset = queryset if queryset is not None else self.queryset
        resource_code = self.data_permission_resource or get_resource_code(queryset.model)
        return resolve_permission_type(
            user=self.request.user,
            resource_code=resource_code,
            default_type=self.data_permission_default_type,
        )

    def apply_data_permission_scope(self, queryset):
        from core_apps.erp_auth.data_permissions import BUSINESS, RESOURCE_BY_CODE, SPECIAL, get_resource_code, get_special_scope_q

        resource_code = self.data_permission_resource or get_resource_code(queryset.model)
        permission_type = self.get_data_permission_type(queryset)
        if permission_type == BUSINESS:
            definition = RESOURCE_BY_CODE.get(resource_code)
            return queryset.filter(get_data_scope_filter(
                self.request.user,
                dept_field=definition.business_dept_field if definition else getattr(self, "dept_field", "dept"),
                user_field=definition.business_user_field if definition else getattr(self, "user_field", "created_by"),
            )).distinct()
        if permission_type == SPECIAL:
            definition = RESOURCE_BY_CODE.get(resource_code)
            scope_field = definition.special_scope_field if definition else self.special_scope_field
            return queryset.filter(get_special_scope_q(
                user=self.request.user, resource_code=resource_code, scope_field=scope_field
            )).distinct()
        return queryset

    def perform_create(self, serializer):
        validate_erp_related_tenant_scope(self.queryset.model, validated_data=serializer.validated_data, user=self.request.user)
        serializer.save(**build_erp_tenant_save_kwargs(self.queryset.model, user=self.request.user))

    def perform_update(self, serializer):
        validate_erp_related_tenant_scope(self.queryset.model, validated_data=serializer.validated_data, user=self.request.user)
        serializer.save()


class ModuleAwareReadOnlyViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [ERPUserOnly, ModuleEnabledPermission, ERPActionPermission]
    module_key = ""
    data_permission_default_type = "BASIC"
    data_permission_resource = ""
    special_scope_field = "pk"

    def get_tenant_scoped_queryset(self):
        queryset = super().get_queryset()
        return apply_erp_tenant_scope(queryset, user=self.request.user)

    def get_scoped_related_queryset(self, queryset):
        queryset = apply_erp_tenant_scope(queryset, user=self.request.user)
        return ModuleAwareModelViewSet.apply_related_data_permission_scope(self, queryset)

    get_tenant_scoped_related_object = ModuleAwareModelViewSet.get_tenant_scoped_related_object

    def get_scoped_related_object(self, queryset, **lookup):
        return self.get_scoped_related_queryset(queryset).get(**lookup)

    def get_queryset(self):
        return ModuleAwareModelViewSet.get_data_permission_scoped_queryset(self)

    get_data_permission_type = ModuleAwareModelViewSet.get_data_permission_type
    apply_data_permission_scope = ModuleAwareModelViewSet.apply_data_permission_scope
    apply_related_data_permission_scope = ModuleAwareModelViewSet.apply_related_data_permission_scope


class BaseBusinessViewSet(ModuleAwareModelViewSet):
    """
    Base ViewSet for all business modules.
    Automatically applies data scope filtering.
    """
    dept_field = 'dept'
    user_field = 'created_by'
    data_permission_default_type = "BUSINESS"

    def get_queryset(self):
        return self.get_data_permission_scoped_queryset()

    def perform_create(self, serializer):
        # Automatically record creator and department
        kwargs = {}
        validate_erp_related_tenant_scope(self.queryset.model, validated_data=serializer.validated_data, user=self.request.user)
        kwargs.update(build_erp_tenant_save_kwargs(self.queryset.model, user=self.request.user))
        try:
            user_field = self.queryset.model._meta.get_field(self.user_field)
        except Exception:
            user_field = None
        if user_field is not None and getattr(user_field, "remote_field", None) is not None:
            if user_field.remote_field.model == self.request.user.__class__:
                kwargs[self.user_field] = self.request.user
        if hasattr(self.request.user, "dept") and hasattr(self.queryset.model, self.dept_field):
            kwargs[self.dept_field] = self.request.user.dept
            
        serializer.save(**kwargs)

    def perform_update(self, serializer):
        validate_erp_related_tenant_scope(self.queryset.model, validated_data=serializer.validated_data, user=self.request.user)
        serializer.save()
