from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from core_apps.common.permissions import PlatformUserOnly
from core_apps.erp_auth.permission_dependencies import ERP_PERMISSION_DEPENDENCIES
from core_apps.modules import get_business_modules, get_core_modules, get_erp_permission_modules

from .services import ConfigurationService
from .navigation import build_navigation_catalog


class ConfigurationValidationView(APIView):
    permission_classes = [permissions.IsAuthenticated, PlatformUserOnly]

    def post(self, request):
        normalized = ConfigurationService.validate_blueprint_config(
            request.data.get("config_json"),
        )
        return Response(
            {
                "config_json": normalized,
                "enabled_modules": normalized["enabled_modules"],
            }
        )


class ConfigurationModuleCatalogView(APIView):
    permission_classes = [permissions.IsAuthenticated, PlatformUserOnly]

    def get(self, request):
        modules = (*get_core_modules(), *get_business_modules())
        return Response(
            [
                {
                    "key": module.key,
                    "label": module.label,
                    "api_prefix": module.api_prefix,
                    "depends_on": list(module.depends_on),
                    "features": list(module.features),
                    "workflows": list(module.workflows),
                    "field_rules": list(module.field_rules),
                    "default_rules": list(module.default_rules),
                    "public_services": list(module.public_services),
                    "config_template": ConfigurationService.get_module_configuration_catalog().get(module.key, {}),
                }
                for module in modules
            ]
        )


class ConfigurationNavigationCatalogView(APIView):
    permission_classes = [permissions.IsAuthenticated, PlatformUserOnly]

    def get(self, request):
        modules = (*get_core_modules(), *get_business_modules())
        return Response(build_navigation_catalog(modules))


class ConfigurationPermissionDependencyView(APIView):
    permission_classes = [permissions.IsAuthenticated, PlatformUserOnly]

    def get(self, request):
        permission_labels = _build_erp_permission_label_map()
        return Response(
            [
                {
                    "trigger_code": trigger_code,
                    "trigger_name": permission_labels.get(trigger_code, trigger_code),
                    "required_permissions": [
                        {
                            "code": required_code,
                            "name": permission_labels.get(required_code, required_code),
                        }
                        for required_code in required_codes
                    ],
                }
                for trigger_code, required_codes in sorted(ERP_PERMISSION_DEPENDENCIES.items())
            ]
        )


def _build_erp_permission_label_map() -> dict[str, str]:
    labels: dict[str, str] = {}
    for module in get_erp_permission_modules():
        for item in (*module.menus, *module.permissions):
            code = item.get("code")
            name = item.get("name")
            if code and name:
                labels[code] = name
    return labels
