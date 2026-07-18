from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

import seed_menu
from core_apps.modules.checks import ModuleRegistryError, validate_modules
from core_apps.modules.loader import load_business_modules, load_core_modules
from core_apps.modules.registry import (
    ModuleDefinition,
    get_business_modules,
    get_business_urlpatterns,
    get_core_modules,
    get_permission_modules,
)


def module_definition(
    key: str,
    *,
    django_app: str | None = None,
    api_prefix: str | None = None,
    depends_on: tuple[str, ...] = (),
    menus: tuple[dict, ...] = (),
    permissions: tuple[dict, ...] = (),
) -> ModuleDefinition:
    normalized_key = key.replace("-", "_")
    return ModuleDefinition(
        key=key,
        label=key.title(),
        django_app=django_app or f"business_apps.{normalized_key}",
        api_prefix=api_prefix or f"api/{key.replace('_', '-')}/",
        depends_on=depends_on,
        menus=menus,
        permissions=permissions,
        features=(),
        workflows=(),
        field_rules=(),
        default_rules=(),
        public_services=(),
    )


class ModuleRegistryTests(SimpleTestCase):
    def setUp(self):
        get_business_modules.cache_clear()
        get_core_modules.cache_clear()
        get_permission_modules.cache_clear()

    def tearDown(self):
        get_business_modules.cache_clear()
        get_core_modules.cache_clear()
        get_permission_modules.cache_clear()

    def test_load_business_modules_discovers_and_sorts_by_dependency(self):
        packages = [
            SimpleNamespace(name="inventory", ispkg=True),
            SimpleNamespace(name="platform", ispkg=True),
            SimpleNamespace(name="sales", ispkg=True),
        ]
        manifests = {
            "business_apps.inventory.module": SimpleNamespace(
                MODULE=module_definition("inventory", depends_on=("platform",))
            ),
            "business_apps.platform.module": SimpleNamespace(
                MODULE=module_definition("platform")
            ),
            "business_apps.sales.module": SimpleNamespace(
                MODULE=module_definition("sales", depends_on=("inventory",))
            ),
        }

        with (
            patch("core_apps.modules.loader.iter_modules", return_value=packages),
            patch(
                "core_apps.modules.loader.find_spec",
                side_effect=lambda dotted: object() if dotted in manifests else None,
            ),
            patch(
                "core_apps.modules.loader.import_module",
                side_effect=lambda dotted: manifests[dotted],
            ),
        ):
            modules = load_business_modules()

        self.assertEqual([module.key for module in modules], ["platform", "inventory", "sales"])

    def test_validate_modules_rejects_duplicate_keys(self):
        with self.assertRaisesMessage(ModuleRegistryError, "Duplicate module key values"):
            validate_modules(
                [
                    module_definition("inventory"),
                    module_definition("inventory", django_app="business_apps.inventory_v2"),
                ]
            )

    def test_load_core_modules_discovers_manifests_without_manual_registry_list(self):
        packages = [
            SimpleNamespace(name="modules", ispkg=True),
            SimpleNamespace(name="system", ispkg=True),
            SimpleNamespace(name="authentication", ispkg=True),
            SimpleNamespace(name="common", ispkg=True),
        ]
        manifests = {
            "core_apps.system.module": SimpleNamespace(
                MODULE=module_definition("system", django_app="core_apps.system")
            ),
            "core_apps.authentication.module": SimpleNamespace(
                MODULE=module_definition(
                    "authentication",
                    django_app="core_apps.authentication",
                )
            ),
        }

        with (
            patch("core_apps.modules.loader.iter_modules", return_value=packages),
            patch(
                "core_apps.modules.loader.find_spec",
                side_effect=lambda dotted: object() if dotted in manifests else None,
            ),
            patch(
                "core_apps.modules.loader.import_module",
                side_effect=lambda dotted: manifests[dotted],
            ),
        ):
            modules = load_core_modules()

        self.assertEqual([module.key for module in modules], ["authentication", "system"])

    def test_validate_modules_rejects_missing_dependency(self):
        with self.assertRaisesMessage(ModuleRegistryError, "Unknown module dependencies"):
            validate_modules([module_definition("inventory", depends_on=("platform",))])

    def test_validate_modules_rejects_role_editor_button_on_module_root(self):
        module = module_definition(
            "inventory",
            menus=(
                {"code": "inventory", "name": "库存", "path": "/inventory"},
                {"code": "inventory:product", "name": "商品", "path": "/inventory/products", "component": "inventory/ProductList", "parent": "inventory"},
            ),
            permissions=(
                {"code": "inventory:product:view", "name": "查看商品", "parent": "inventory:product"},
                {"code": "inventory:product:update", "name": "编辑商品", "parent": "inventory"},
            ),
        )
        with self.assertRaisesMessage(ModuleRegistryError, "must belong to visible page menus"):
            validate_modules([module])

    def test_validate_modules_allows_internal_button_on_module_root(self):
        module = module_definition(
            "inventory",
            menus=({"code": "inventory", "name": "库存", "path": "/inventory"},),
            permissions=(
                {"code": "inventory:export:view", "name": "导出任务", "parent": "inventory", "role_editor_visible": False},
            ),
        )
        validate_modules([module])

    def test_validate_modules_rejects_visible_page_without_view_permission(self):
        module = module_definition(
            "inventory",
            menus=(
                {"code": "inventory", "name": "库存", "path": "/inventory"},
                {"code": "inventory:transaction", "name": "库存流水", "path": "/inventory/transactions", "component": "inventory/TransactionList", "parent": "inventory"},
            ),
        )
        with self.assertRaisesMessage(ModuleRegistryError, "must declare a role-editor view permission"):
            validate_modules([module])

    def test_load_business_modules_reports_missing_manifest_file(self):
        packages = [SimpleNamespace(name="inventory", ispkg=True)]

        with (
            patch("core_apps.modules.loader.iter_modules", return_value=packages),
            patch("core_apps.modules.loader.find_spec", return_value=None),
        ):
            with self.assertRaisesMessage(
                ModuleRegistryError,
                "Missing module manifest for business app 'inventory'",
            ):
                load_business_modules()

    def test_get_business_urlpatterns_builds_from_manifests(self):
        modules = (
            module_definition("inventory"),
            module_definition("sales"),
        )

        with patch("core_apps.modules.registry.load_business_modules", return_value=modules):
            get_business_modules.cache_clear()
            url_patterns = get_business_urlpatterns()

        self.assertEqual(
            url_patterns,
            [
                ("api/inventory/", "business_apps.inventory.urls"),
                ("api/sales/", "business_apps.sales.urls"),
            ],
        )

    def test_permission_modules_aggregate_menu_and_permission_definitions(self):
        business_module = module_definition(
            "inventory",
            menus=(
                {"code": "inventory", "name": "库存管理", "path": "/inventory"},
            ),
            permissions=(
                {
                    "code": "inventory:product:view",
                    "name": "查看商品",
                    "parent": "inventory",
                },
            ),
        )

        with patch("core_apps.modules.registry.load_business_modules", return_value=(business_module,)):
            get_business_modules.cache_clear()
            get_permission_modules.cache_clear()
            permission_modules = get_permission_modules()

        menu_codes = {
            menu["code"]
            for module in permission_modules
            for menu in module.menus
        }
        permission_codes = {
            permission["code"]
            for module in permission_modules
            for permission in module.permissions
        }

        self.assertIn("system", menu_codes)
        self.assertIn("inventory", menu_codes)
        self.assertIn("inventory:product:view", permission_codes)

    def test_seed_menu_aggregates_defined_codes_from_manifests(self):
        business_module = module_definition(
            "inventory",
            menus=(
                {"code": "inventory", "name": "库存管理", "path": "/inventory"},
            ),
            permissions=(
                {
                    "code": "inventory:product:view",
                    "name": "查看商品",
                    "parent": "inventory",
                },
            ),
        )

        with patch("seed_menu.get_permission_modules", return_value=(business_module,)):
            codes = seed_menu.get_defined_permission_codes()

        self.assertEqual(codes, {"inventory", "inventory:product:view"})
