from django.test import SimpleTestCase

from business_apps.ar_receivable.module import MODULE as AR_MODULE
from business_apps.ar_receivable.views import ReceivableViewSet
from business_apps.ap_payable.module import MODULE as AP_MODULE
from business_apps.ap_payable.views import APAccountViewSet
from business_apps.inventory.views import InventoryTransactionViewSet
from business_apps.purchase.views import PurchaseOrderViewSet
from business_apps.sales.views import SalesOrderViewSet
from core_apps.system.views import OperationLogViewSet
from core_apps.erp_auth.permission_dependencies import ERP_PERMISSION_DEPENDENCIES
from business_apps.inventory.module import MODULE as INVENTORY_MODULE
from business_apps.inventory.views import InventoryViewSet, ProductCategoryViewSet, UnitViewSet
from business_apps.supply_chain.module import MODULE as SUPPLY_CHAIN_MODULE
from business_apps.supply_chain.views import InventoryAlertViewSet


class ListActionPermissionContractTest(SimpleTestCase):
    def test_ar_aging_analysis_uses_declared_page_action_permission(self):
        permission_codes = {permission["code"] for permission in AR_MODULE.permissions}

        self.assertIn("ar:aging:view", permission_codes)
        self.assertEqual(ReceivableViewSet.permission_map["aging_analysis"], "ar:aging:view")

    def test_standalone_pages_use_their_own_view_permissions(self):
        ap_codes = {permission["code"] for permission in AP_MODULE.permissions}
        self.assertTrue({"ap:summary:view", "ap:aging:view"}.issubset(ap_codes))
        self.assertEqual(APAccountViewSet.permission_map["supplier_summary"], "ap:summary:view")
        self.assertEqual(APAccountViewSet.permission_map["aging"], "ap:aging:view")
        self.assertEqual(SalesOrderViewSet.permission_map["statistics"], "sales:stats:view")
        self.assertEqual(PurchaseOrderViewSet.permission_map["statistics"], "purchase:stats:view")
        self.assertEqual(InventoryTransactionViewSet.permission_map["list"], "inventory:transaction:view")
        self.assertEqual(OperationLogViewSet.permission_map["list"], "system:log:view")

    def test_aging_view_permissions_include_selector_reference_dependencies(self):
        self.assertIn("crm:customer:reference", ERP_PERMISSION_DEPENDENCIES["ar:aging:view"])
        self.assertIn("supplier:supplier:reference", ERP_PERMISSION_DEPENDENCIES["ap:aging:view"])

    def test_inventory_list_action_permissions_match_viewsets(self):
        permission_codes = {permission["code"] for permission in INVENTORY_MODULE.permissions}
        expected_codes = {
            "inventory:category:view",
            "inventory:category:create",
            "inventory:category:update",
            "inventory:category:delete",
            "inventory:unit:view",
            "inventory:unit:create",
            "inventory:unit:update",
            "inventory:unit:delete",
            "inventory:inventory:adjust",
        }

        self.assertTrue(expected_codes.issubset(permission_codes))
        self.assertEqual(ProductCategoryViewSet.permission_map["destroy"], "inventory:category:delete")
        self.assertEqual(UnitViewSet.permission_map["partial_update"], "inventory:unit:update")
        self.assertEqual(InventoryViewSet.permission_map["adjust"], "inventory:inventory:adjust")

    def test_alert_scan_uses_declared_action_permission(self):
        permission_codes = {permission["code"] for permission in SUPPLY_CHAIN_MODULE.permissions}

        self.assertIn("supply_chain:alert:scan", permission_codes)
        self.assertEqual(InventoryAlertViewSet.permission_map["scan"], "supply_chain:alert:scan")
