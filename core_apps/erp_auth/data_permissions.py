from __future__ import annotations

from dataclasses import dataclass

from django.apps import apps
from django.db.models import Q

from .models import ERPDataPermissionPolicy, ERPDataSpecialGrant, ERPDepartment, ERPUser
from core_apps.common.authz import has_erp_super_admin_role

BASIC = "BASIC"
BUSINESS = "BUSINESS"
SPECIAL = "SPECIAL"
VALID_TYPES = {BASIC, BUSINESS, SPECIAL}


@dataclass(frozen=True)
class DataResource:
    code: str
    name: str
    module: str
    default_type: str
    special_object_model: str | None = None
    special_scope_field: str = "pk"
    business_dept_field: str = "dept"
    business_user_field: str = "created_by"


DATA_RESOURCES = (
    DataResource("inventory.productcategory", "商品分类", "库存管理", BASIC),
    DataResource("inventory.unit", "计量单位", "库存管理", BASIC),
    DataResource("inventory.product", "商品档案", "库存管理", BASIC),
    DataResource("inventory.producttag", "商品标签", "库存管理", BASIC),
    DataResource("inventory.warehouse", "仓库", "库存管理", SPECIAL, "inventory.Warehouse", business_dept_field="manager__dept", business_user_field="manager"),
    DataResource("inventory.inventory", "库存", "库存管理", SPECIAL, "inventory.Warehouse", "warehouse_id", "warehouse__manager__dept", "warehouse__manager"),
    DataResource("inventory.inventorytransaction", "库存流水", "库存管理", SPECIAL, "inventory.Warehouse", "warehouse_id", "warehouse__manager__dept", "warehouse__manager"),
    DataResource("inventory.stocktake", "盘点单", "库存管理", BUSINESS, business_dept_field="created_by__dept", business_user_field="created_by"),
    DataResource("crm.customer", "客户", "客户管理", BUSINESS, business_user_field="owner"),
    DataResource("supplier.supplier", "供应商", "供应商管理", BUSINESS, business_user_field="owner"),
    DataResource("purchase.purchaseorder", "采购订单", "采购管理", BUSINESS),
    DataResource("purchase.purchasereceipt", "采购入库单", "采购管理", BUSINESS, business_dept_field="purchase_order__dept"),
    DataResource("sales.salesorder", "销售订单", "销售管理", BUSINESS, business_dept_field="created_by__dept", business_user_field="created_by"),
    DataResource("supply_chain.outboundorder", "销售出库单", "供应链", BUSINESS),
    DataResource("supply_chain.transferorder", "调拨单", "供应链", BUSINESS),
    DataResource("supply_chain.salesreturnorder", "销售退货单", "供应链", BUSINESS),
    DataResource("supply_chain.purchasereturnorder", "采购退货单", "供应链", BUSINESS),
    DataResource("ar_receivable.receivable", "应收单", "应收管理", BUSINESS),
    DataResource("ar_receivable.receipt", "收款单", "应收管理", BUSINESS),
    DataResource("ar_receivable.customerrefund", "客户退款单", "应收管理", BUSINESS),
    DataResource("ap_payable.apaccount", "应付单", "应付管理", BUSINESS),
    DataResource("ap_payable.appayment", "付款单", "应付管理", BUSINESS),
    DataResource("ap_payable.supplierrefund", "供应商退款单", "应付管理", BUSINESS),
    DataResource("finance.cashaccount", "资金账户", "财务管理", SPECIAL, "finance.CashAccount"),
    DataResource("accounting.accountsubject", "会计科目", "财务管理", BASIC),
    DataResource("accounting.accountingperiod", "会计期间", "财务管理", BASIC),
    DataResource("accounting.voucher", "会计凭证", "财务管理", BUSINESS, business_dept_field="posted_by__dept", business_user_field="posted_by"),
    DataResource("platform.dicttype", "字典类型", "基础平台", BASIC),
    DataResource("platform.dictitem", "字典数据", "基础平台", BASIC),
    DataResource("platform.coderule", "编码规则", "基础平台", BASIC),
)
RESOURCE_BY_CODE = {item.code: item for item in DATA_RESOURCES}


def get_resource_code(model) -> str:
    return model._meta.label_lower


def get_department_descendant_ids(department: ERPDepartment | None) -> list[int]:
    if department is None:
        return []
    found = {department.id}
    pending = [department.id]
    while pending:
        child_ids = list(
            ERPDepartment.objects.filter(tenant_id=department.tenant_id, parent_id__in=pending)
            .exclude(id__in=found)
            .values_list("id", flat=True)
        )
        found.update(child_ids)
        pending = child_ids
    return list(found)


def get_department_ancestor_ids(department: ERPDepartment | None) -> list[int]:
    found = []
    current = department
    while current is not None and current.id not in found:
        found.append(current.id)
        current = current.parent
    return found


def resolve_permission_type(*, user, resource_code: str, default_type: str) -> str:
    definition = RESOURCE_BY_CODE.get(resource_code)
    default_type = definition.default_type if definition else default_type
    if not isinstance(user, ERPUser):
        return default_type
    return (
        ERPDataPermissionPolicy.objects.filter(tenant=user.tenant, resource_code=resource_code)
        .values_list("permission_type", flat=True)
        .first()
        or default_type
    )


def get_special_scope_q(*, user, resource_code: str, scope_field: str = "pk") -> Q:
    if not isinstance(user, ERPUser):
        return Q(pk__isnull=True)
    if has_erp_super_admin_role(user):
        return Q()
    grants = ERPDataSpecialGrant.objects.filter(tenant=user.tenant, resource_code=resource_code)
    role_ids = list(user.roles.filter(status=True).values_list("id", flat=True))
    dept_ids = get_department_ancestor_ids(user.dept)
    grants = grants.filter(Q(user=user) | Q(role_id__in=role_ids) | Q(department_id__in=dept_ids))
    object_ids = list(grants.values_list("object_id", flat=True))
    return Q(**{f"{scope_field}__in": object_ids})


def get_special_options(resource: DataResource, *, tenant):
    model = apps.get_model(resource.special_object_model or resource.code)
    queryset = model.objects.all()
    if any(field.name == "tenant" for field in model._meta.fields):
        queryset = queryset.filter(tenant=tenant)
    return [{"id": str(obj.pk), "name": str(obj)} for obj in queryset.order_by("pk")[:1000]]


def model_has_path(model, path: str) -> bool:
    current = model
    for part in path.split("__"):
        try:
            field = current._meta.get_field(part)
        except Exception:
            return False
        current = getattr(getattr(field, "remote_field", None), "model", None)
        if current is None and part != path.split("__")[-1]:
            return False
    return True


def supported_permission_types(resource: DataResource) -> list[str]:
    model = apps.get_model(resource.code)
    supported = [BASIC, SPECIAL]
    if model_has_path(model, resource.business_user_field) and model_has_path(model, resource.business_dept_field):
        supported.insert(1, BUSINESS)
    return supported
