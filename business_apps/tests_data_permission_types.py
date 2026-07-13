from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from business_apps.crm.models import Customer
from business_apps.crm.views import CustomerViewSet
from business_apps.inventory.models import Product, ProductCategory, Unit, Warehouse
from business_apps.inventory.views import ProductViewSet, WarehouseViewSet
from business_apps.purchase.models import PurchaseReceipt
from core_apps.common.viewsets import validate_erp_related_tenant_scope
from core_apps.erp_auth.models import (
    ERPDataPermissionPolicy,
    ERPDataSpecialGrant,
    ERPDepartment,
    ERPPermission,
    ERPRole,
    ERPUser,
)
from core_apps.tenant.models import Tenant


class TenantDataPermissionTypeTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="scope-tree", name="Scope Tree")
        self.parent_dept = ERPDepartment.objects.create(tenant=self.tenant, name="销售中心")
        self.child_dept = ERPDepartment.objects.create(tenant=self.tenant, name="销售一部", parent=self.parent_dept)
        self.grandchild_dept = ERPDepartment.objects.create(tenant=self.tenant, name="华东组", parent=self.child_dept)
        self.sibling_dept = ERPDepartment.objects.create(tenant=self.tenant, name="财务部")
        self.role = ERPRole.objects.create(
            tenant=self.tenant, name="销售经理", code="sales_manager", data_scope="DEPARTMENT"
        )
        self.manager = ERPUser.objects.create_user(
            tenant=self.tenant, username="manager", password="pass", dept=self.parent_dept
        )
        self.manager.roles.add(self.role)
        self.child_user = ERPUser.objects.create_user(
            tenant=self.tenant, username="child", password="pass", dept=self.grandchild_dept
        )
        self.other_user = ERPUser.objects.create_user(
            tenant=self.tenant, username="other", password="pass", dept=self.sibling_dept
        )

    def _query(self, view_class):
        view = view_class()
        view.request = SimpleNamespace(user=self.manager, query_params={})
        view.action = "list"
        view.kwargs = {}
        return view.get_queryset()

    def test_department_business_scope_includes_all_descendants(self):
        own = Customer.objects.create(
            tenant=self.tenant, customer_code="C-OWN", customer_name="经理客户",
            owner=self.manager, dept=self.parent_dept, created_by=self.manager,
        )
        descendant = Customer.objects.create(
            tenant=self.tenant, customer_code="C-CHILD", customer_name="下级客户",
            owner=self.child_user, dept=self.grandchild_dept, created_by=self.child_user,
        )
        Customer.objects.create(
            tenant=self.tenant, customer_code="C-OTHER", customer_name="其他部门客户",
            owner=self.other_user, dept=self.sibling_dept, created_by=self.other_user,
        )

        self.assertSetEqual(set(self._query(CustomerViewSet)), {own, descendant})

    def test_basic_data_ignores_role_business_scope(self):
        category = ProductCategory.objects.create(tenant=self.tenant, name="通用分类")
        unit = Unit.objects.create(tenant=self.tenant, name="件", code="UNIT-SCOPE-TREE")
        own = Product.objects.create(
            tenant=self.tenant, product_code="P-OWN", name="本人商品", category=category,
            unit=unit, dept=self.parent_dept, created_by=self.manager,
        )
        other = Product.objects.create(
            tenant=self.tenant, product_code="P-OTHER", name="其他部门商品", category=category,
            unit=unit, dept=self.sibling_dept, created_by=self.other_user,
        )

        self.assertSetEqual(set(self._query(ProductViewSet)), {own, other})

        ERPDataPermissionPolicy.objects.create(
            tenant=self.tenant, resource_code="inventory.product", permission_type="BUSINESS"
        )
        self.assertSetEqual(set(self._query(ProductViewSet)), {own})

    def test_special_data_requires_independent_grant(self):
        granted = Warehouse.objects.create(
            tenant=self.tenant, warehouse_code="WH-GRANTED", warehouse_name="授权仓"
        )
        Warehouse.objects.create(
            tenant=self.tenant, warehouse_code="WH-HIDDEN", warehouse_name="未授权仓"
        )
        self.assertFalse(self._query(WarehouseViewSet).exists())

        ERPDataSpecialGrant.objects.create(
            tenant=self.tenant,
            resource_code="inventory.warehouse",
            object_id=str(granted.id),
            department=self.parent_dept,
        )
        self.assertSetEqual(set(self._query(WarehouseViewSet)), {granted})

    def test_super_admin_system_role_sees_all_special_data(self):
        first = Warehouse.objects.create(
            tenant=self.tenant, warehouse_code="WH-SUPER-1", warehouse_name="超级管理员仓一"
        )
        second = Warehouse.objects.create(
            tenant=self.tenant, warehouse_code="WH-SUPER-2", warehouse_name="超级管理员仓二"
        )
        super_role = ERPRole.objects.create(
            tenant=self.tenant,
            name="租户超级管理员",
            code="tenant-super-admin",
            data_scope="ALL",
            status=True,
            is_system=True,
        )
        self.manager.roles.add(super_role)

        self.assertSetEqual(set(self._query(WarehouseViewSet)), {first, second})

    def test_reference_visibility_equals_view_visibility(self):
        warehouse = Warehouse.objects.create(
            tenant=self.tenant, warehouse_code="WH-REFERENCE", warehouse_name="引用仓"
        )
        with self.assertRaises(ValidationError):
            validate_erp_related_tenant_scope(
                PurchaseReceipt, validated_data={"warehouse": warehouse}, user=self.manager
            )

        ERPDataSpecialGrant.objects.create(
            tenant=self.tenant,
            resource_code="inventory.warehouse",
            object_id=str(warehouse.id),
            user=self.manager,
        )
        validate_erp_related_tenant_scope(
            PurchaseReceipt, validated_data={"warehouse": warehouse}, user=self.manager
        )


class TenantDataPermissionConfigApiTest(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="scope-config", name="Scope Config")
        self.dept = ERPDepartment.objects.create(tenant=self.tenant, name="业务部")
        permission = ERPPermission.objects.create(name="角色管理", code="system:role", type="MENU")
        self.role = ERPRole.objects.create(
            tenant=self.tenant, name="管理员", code="config_admin", data_scope="ALL"
        )
        self.role.permissions.add(permission)
        self.user = ERPUser.objects.create_user(
            tenant=self.tenant, username="config-admin", password="pass", dept=self.dept
        )
        self.user.roles.add(self.role)
        self.client.force_authenticate(self.user)

    def test_tenant_can_configure_resource_type_and_special_grant(self):
        permission_patch = patch("core_apps.common.permissions.has_erp_role_permission", return_value=True)
        permission_patch.start()
        self.addCleanup(permission_patch.stop)
        response = self.client.get("/api/erp-auth/data-permissions/resources/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        resources = response.data
        product = next(item for item in resources if item["code"] == "inventory.product")
        self.assertEqual(product["permission_type"], "BASIC")

        response = self.client.put(
            "/api/erp-auth/data-permissions/resources/",
            {"resources": [{"code": "inventory.product", "permission_type": "BUSINESS"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(ERPDataPermissionPolicy.objects.filter(
            tenant=self.tenant, resource_code="inventory.product", permission_type="BUSINESS"
        ).exists())

        warehouse = Warehouse.objects.create(
            tenant=self.tenant, warehouse_code="WH-API", warehouse_name="API授权仓"
        )
        response = self.client.post(
            "/api/erp-auth/data-permissions/grants/",
            {
                "resource_code": "inventory.warehouse",
                "object_id": str(warehouse.id),
                "role": self.role.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
