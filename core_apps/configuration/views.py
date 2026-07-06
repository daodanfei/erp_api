from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from core_apps.common.permissions import PlatformUserOnly
from core_apps.modules import get_business_modules, get_core_modules

from .services import ConfigurationService


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
