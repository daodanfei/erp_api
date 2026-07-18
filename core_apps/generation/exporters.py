from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from .planners import GenerationPlan


BACKEND_IGNORE = shutil.ignore_patterns(
    "__pycache__",
    "*.pyc",
    ".DS_Store",
    "venv",
    "media",
    "db.sqlite3",
)
FRONTEND_IGNORE = shutil.ignore_patterns(
    "__pycache__",
    "*.pyc",
    ".DS_Store",
    "node_modules",
    "dist",
    "playwright-report",
    "test-results",
)
STATIC_THIRD_PARTY_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "rest_framework_simplejwt",
    "corsheaders",
]
STATIC_MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core_apps.tenant.middleware.TenantContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core_apps.system.middleware.OperationLogMiddleware",
]
KEEP_CORE_SUPPORT_DIRS = {"common", "modules", "policies"}


@dataclass(frozen=True, slots=True)
class ExportArtifact:
    artifact_path: str
    artifact_name: str
    artifact_size: int
    artifact_checksum: str


def _project_root() -> Path:
    return Path(settings.BASE_DIR).parent


def _artifact_root(job_key: str) -> Path:
    root = Path(settings.MEDIA_ROOT) / "generation_exports" / job_key
    root.mkdir(parents=True, exist_ok=True)
    return root


def export_code_package(
    *,
    job_key: str,
    blueprint_payload: dict,
    plan: GenerationPlan,
) -> ExportArtifact:
    project_root = _project_root()
    artifact_root = _artifact_root(job_key)
    bundle_root = artifact_root / "export_bundle"
    if bundle_root.exists():
        shutil.rmtree(bundle_root)
    bundle_root.mkdir(parents=True, exist_ok=True)

    _copy_project_scaffold(project_root=project_root, bundle_root=bundle_root)
    _prune_backend_modules(bundle_root=bundle_root, plan=plan)
    _prune_frontend_modules(bundle_root=bundle_root, plan=plan)
    _prune_backend_module_metadata(bundle_root=bundle_root, plan=plan)
    _prune_frontend_module_entries(bundle_root=bundle_root, plan=plan)
    _write_generated_backend_settings(bundle_root=bundle_root, plan=plan)
    _write_generated_backend_urls(bundle_root=bundle_root, plan=plan)
    _write_generated_frontend_registry(bundle_root=bundle_root, plan=plan)
    _write_export_metadata(bundle_root=bundle_root, job_key=job_key, blueprint_payload=blueprint_payload, plan=plan)

    zip_path = artifact_root / f"erp_export_{job_key}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in bundle_root.rglob("*"):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(artifact_root))

    checksum = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    return ExportArtifact(
        artifact_path=str(zip_path),
        artifact_name=zip_path.name,
        artifact_size=zip_path.stat().st_size,
        artifact_checksum=checksum,
    )


def _copy_project_scaffold(*, project_root: Path, bundle_root: Path) -> None:
    shutil.copytree(
        project_root / "backend",
        bundle_root / "backend",
        dirs_exist_ok=True,
        ignore=BACKEND_IGNORE,
    )
    shutil.copytree(
        project_root / "frontend",
        bundle_root / "frontend",
        dirs_exist_ok=True,
        ignore=FRONTEND_IGNORE,
    )


def _prune_backend_modules(*, bundle_root: Path, plan: GenerationPlan) -> None:
    retained_core = {
        app.split(".")[-1]
        for app in plan.retained_backend_apps
        if app.startswith("core_apps.")
    } | KEEP_CORE_SUPPORT_DIRS
    retained_business = {
        app.split(".")[-1]
        for app in plan.retained_backend_apps
        if app.startswith("business_apps.")
    }

    core_apps_root = bundle_root / "backend/core_apps"
    for path in core_apps_root.iterdir():
        if path.name.startswith(".") or not path.is_dir():
            continue
        if path.name not in retained_core:
            shutil.rmtree(path)

    business_apps_root = bundle_root / "backend/business_apps"
    for path in business_apps_root.iterdir():
        if path.name.startswith(".") or not path.is_dir():
            continue
        if path.name not in retained_business:
            shutil.rmtree(path)


def _prune_frontend_modules(*, bundle_root: Path, plan: GenerationPlan) -> None:
    modules_root = bundle_root / "frontend/src/modules"
    retained = set(plan.retained_frontend_modules)
    for path in modules_root.iterdir():
        if path.name.startswith(".") or not path.is_dir():
            continue
        if path.name not in retained:
            shutil.rmtree(path)


def _prune_backend_module_metadata(*, bundle_root: Path, plan: GenerationPlan) -> None:
    for module_key, contract in plan.module_feature_contracts.items():
        if not contract.get("prunable_route_paths") and not contract.get("prunable_permission_codes"):
            continue
        app_name = module_key
        module_path = bundle_root / "backend/business_apps" / app_name / "module.py"
        if not module_path.exists():
            continue
        source = module_path.read_text(encoding="utf-8")
        source = source.rstrip()
        source += _build_backend_module_pruning_block(
            prunable_route_paths=tuple(contract.get("prunable_route_paths", [])),
            prunable_permission_codes=tuple(contract.get("prunable_permission_codes", [])),
        )
        module_path.write_text(source + "\n", encoding="utf-8")


def _prune_frontend_module_entries(*, bundle_root: Path, plan: GenerationPlan) -> None:
    for contract in plan.module_feature_contracts.values():
        frontend_module_key = contract.get("frontend_module_key")
        if not frontend_module_key:
            continue
        if not contract.get("prunable_route_paths") and not contract.get("prunable_permission_codes"):
            continue
        module_path = bundle_root / "frontend/src/modules" / frontend_module_key / "module.tsx"
        if not module_path.exists():
            continue
        source = module_path.read_text(encoding="utf-8").rstrip()
        source += _build_frontend_module_pruning_block(
            prunable_route_paths=tuple(contract.get("prunable_route_paths", [])),
            prunable_permission_codes=tuple(contract.get("prunable_permission_codes", [])),
        )
        module_path.write_text(source + "\n", encoding="utf-8")


def _write_generated_backend_settings(*, bundle_root: Path, plan: GenerationPlan) -> None:
    installed_apps = STATIC_THIRD_PARTY_APPS + list(plan.retained_backend_apps)
    settings_path = bundle_root / "backend/core_project/settings.py"
    settings_path.write_text(
        "\n".join(
            [
                '"""Generated by ERP export."""',
                "",
                "import environ",
                "import os",
                "from datetime import timedelta",
                "from pathlib import Path",
                "",
                "BASE_DIR = Path(__file__).resolve().parent.parent",
                "",
                "env = environ.Env(DEBUG=(bool, False))",
                'environ.Env.read_env(os.path.join(BASE_DIR, ".env"))',
                "",
                'SECRET_KEY = env("SECRET_KEY", default="replace-me")',
                'DEBUG = env("DEBUG")',
                'ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])',
                "",
                "INSTALLED_APPS = [",
                *[f'    "{app}",' for app in installed_apps],
                "]",
                "",
                'AUTH_USER_MODEL = "authentication.User"',
                "",
                "REST_FRAMEWORK = {",
                '    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],',
                '    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework_simplejwt.authentication.JWTAuthentication"],',
                '    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend", "rest_framework.filters.SearchFilter"],',
                "}",
                "",
                "MIDDLEWARE = [",
                *[f'    "{middleware}",' for middleware in STATIC_MIDDLEWARE],
                "]",
                "",
                'ROOT_URLCONF = "core_project.urls"',
                "",
                "TEMPLATES = [",
                "    {",
                '        "BACKEND": "django.template.backends.django.DjangoTemplates",',
                '        "DIRS": [],',
                '        "APP_DIRS": True,',
                '        "OPTIONS": {',
                '            "context_processors": [',
                '                "django.template.context_processors.request",',
                '                "django.contrib.auth.context_processors.auth",',
                '                "django.contrib.messages.context_processors.messages",',
                "            ],",
                "        },",
                "    }",
                "]",
                "",
                'WSGI_APPLICATION = "core_project.wsgi.application"',
                "",
                'DATABASES = {"default": env.db()}',
                "",
                "AUTH_PASSWORD_VALIDATORS = [",
                '    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},',
                '    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},',
                '    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},',
                '    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},',
                "]",
                "",
                'LANGUAGE_CODE = "en-us"',
                'TIME_ZONE = env("TIME_ZONE", default="UTC")',
                "USE_I18N = True",
                "USE_TZ = True",
                "",
                "SIMPLE_JWT = {",
                '    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),',
                '    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),',
                '    "ROTATE_REFRESH_TOKENS": True,',
                '    "BLACKLIST_AFTER_ROTATION": True,',
                '    "AUTH_HEADER_TYPES": ("Bearer",),',
                "}",
                "",
                "CORS_ALLOW_ALL_ORIGINS = True",
                'STATIC_URL = "static/"',
                'MEDIA_URL = "/media/"',
                'MEDIA_ROOT = os.path.join(BASE_DIR, "media")',
                'FILE_STORAGE_TYPE = os.environ.get("FILE_STORAGE_TYPE", "LOCAL")',
                "",
                "MINIO_CONFIG = {",
                '    "ENDPOINT": os.environ.get("MINIO_ENDPOINT", "localhost:9000"),',
                '    "ACCESS_KEY": os.environ.get("MINIO_ACCESS_KEY", "minioadmin"),',
                '    "SECRET_KEY": os.environ.get("MINIO_SECRET_KEY", "minioadmin"),',
                '    "SECURE": os.environ.get("MINIO_SECURE", "false").lower() == "true",',
                '    "BUCKET": os.environ.get("MINIO_BUCKET", "erp-files"),',
                '    "EXTERNAL_URL": os.environ.get("MINIO_EXTERNAL_URL", "http://localhost:9000"),',
                "}",
                "",
                "S3_CONFIG = {",
                '    "ENDPOINT_URL": os.environ.get("S3_ENDPOINT_URL", ""),',
                '    "ACCESS_KEY": os.environ.get("AWS_ACCESS_KEY_ID", ""),',
                '    "SECRET_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY", ""),',
                '    "REGION": os.environ.get("AWS_REGION", "us-east-1"),',
                '    "BUCKET": os.environ.get("S3_BUCKET", "erp-files"),',
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_generated_backend_urls(*, bundle_root: Path, plan: GenerationPlan) -> None:
    imports = []
    for module in plan.modules:
        alias = f"{module.key}_urls".replace("-", "_")
        imports.append((alias, module.api_prefix, f"{module.django_app}.urls"))

    urls_path = bundle_root / "backend/core_project/urls.py"
    lines = [
        '"""Generated by ERP export."""',
        "",
        "from django.contrib import admin",
        "from django.urls import include, path",
        "",
    ]
    for alias, _, urlconf in imports:
        lines.append(f"import {urlconf} as {alias}")
    lines.extend(
        [
            "",
            "urlpatterns = [",
            '    path("admin/", admin.site.urls),',
            "]",
            "",
            "urlpatterns += [",
        ]
    )
    for alias, api_prefix, _ in imports:
        lines.append(f'    path("{api_prefix}", include({alias})),')
    lines.extend(["]", ""])
    urls_path.write_text("\n".join(lines), encoding="utf-8")


def _write_generated_frontend_registry(*, bundle_root: Path, plan: GenerationPlan) -> None:
    registry_path = bundle_root / "frontend/src/core/modules/registry.ts"
    imports = []
    module_refs = []
    for frontend_key in plan.retained_frontend_modules:
        ref_name = f"{frontend_key}Module".replace("-", "_")
        imports.append(f'import {{ module as {ref_name} }} from "../../modules/{frontend_key}/module";')
        module_refs.append(ref_name)

    frontend_contracts = {
        contract["frontend_module_key"]: {
            "disabled_prunable_features": contract.get("disabled_prunable_features", []),
            "config_only_features": contract.get("config_only_features", []),
            "prunable_route_paths": contract.get("prunable_route_paths", []),
            "prunable_permission_codes": contract.get("prunable_permission_codes", []),
        }
        for contract in plan.module_feature_contracts.values()
        if contract.get("frontend_module_key")
    }

    lines = [
        "// Generated by ERP export.",
        'import { buildFrontendRegistry } from "./registry-core";',
        'import type { FrontendModuleDefinition } from "./types";',
        *imports,
        "",
        f"const exportFeatureContracts = {json.dumps(frontend_contracts, ensure_ascii=False, indent=2)};",
        "",
        "const applyExportContract = (module: FrontendModuleDefinition): FrontendModuleDefinition => {",
        "  const contract = exportFeatureContracts[module.key as keyof typeof exportFeatureContracts];",
        "  const featurePages = module.exportMeta?.featurePages || [];",
        "  if (!contract || featurePages.length === 0) {",
        "    return module;",
        "  }",
        "  const disabledFeatures = new Set(contract.disabled_prunable_features || []);",
        "  const disabledRoutePaths = new Set(contract.prunable_route_paths || []);",
        "  const disabledPermissionCodes = new Set(contract.prunable_permission_codes || []);",
        "  for (const page of featurePages) {",
        '    const isPrunable = page.capability === "prunable" || page.prunable === true;',
        "    if (!isPrunable || !disabledFeatures.has(page.featureKey)) {",
        "      continue;",
        "    }",
        "    for (const routePath of page.routePaths) {",
        "      disabledRoutePaths.add(routePath);",
        "    }",
        "    for (const permissionCode of page.permissionCodes || []) {",
        "      disabledPermissionCodes.add(permissionCode);",
        "    }",
        "  }",
        "  return {",
        "    ...module,",
        "    menus: module.menus.filter((menu) => !disabledRoutePaths.has(menu.path)),",
        "    routes: module.routes.filter((route) => !disabledRoutePaths.has(route.path) && !(route.permissionCode && disabledPermissionCodes.has(route.permissionCode))),",
        "  };",
        "};",
        "",
        "export const frontendModules: FrontendModuleDefinition[] = [",
        *[f"  {ref_name}," for ref_name in module_refs],
        "].map(applyExportContract);",
        "",
        "const registry = buildFrontendRegistry(frontendModules);",
        "",
        "export const appRoutes = registry.appRoutes;",
        "export const hiddenRoutes = registry.hiddenRoutes;",
        "export const publicRoutes = registry.publicRoutes;",
        "export const publicRoutePaths = registry.publicRoutePaths;",
        "export const hiddenRoutePaths = registry.hiddenRoutePaths;",
        "",
        "export const getFrontendModule = (key: string) =>",
        "  frontendModules.find((module) => module.key === key);",
        "",
    ]
    registry_path.write_text("\n".join(lines), encoding="utf-8")


def _write_export_metadata(*, bundle_root: Path, job_key: str, blueprint_payload: dict, plan: GenerationPlan) -> None:
    (bundle_root / "erp_blueprint.json").write_text(
        json.dumps(blueprint_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (bundle_root / "module-lock.json").write_text(
        json.dumps(
            {
                "job_key": job_key,
                "runtime_mode": plan.runtime_mode,
                "modules": list(plan.module_keys),
                "export_manifest": plan.export_manifest,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (bundle_root / ".env.example").write_text(
        "\n".join(
            [
                "SECRET_KEY=replace-me",
                "DEBUG=False",
                "ALLOWED_HOSTS=localhost,127.0.0.1",
                "TIME_ZONE=UTC",
                "DATABASE_URL=sqlite:///db.sqlite3",
                "FILE_STORAGE_TYPE=LOCAL",
                "",
            ]
        ),
        encoding="utf-8",
    )
    seed_requirement_lines = [
        f"- {module_key}: required={details.get('required')} keys={', '.join(details.get('keys', [])) or 'none'}"
        for module_key, details in sorted(plan.seed_data_requirements.items())
    ] or ["- none"]
    support_dependency_lines = [
        f"- {module_key}: attachments={details.get('attachments_dependency')} task_logs={details.get('task_log_dependency')}"
        for module_key, details in sorted(plan.support_dependencies.items())
        if details.get("attachments_dependency") or details.get("task_log_dependency")
    ] or ["- none"]
    readme_lines = [
        "# Generated ERP Export Bundle",
        "",
        f"- job_key: `{job_key}`",
        f"- runtime_mode: `{plan.runtime_mode}`",
        f"- enabled_modules: `{', '.join(plan.enabled_modules)}`",
        f"- retained_backend_apps: `{', '.join(plan.retained_backend_apps)}`",
        f"- retained_frontend_modules: `{', '.join(plan.retained_frontend_modules)}`",
        f"- removed_modules: `{', '.join(plan.removed_modules)}`",
        "",
        "## Feature Contracts",
        "",
        f"- config_only_features: `{_join_feature_names(plan, 'config_only_features')}`",
        f"- pruned_route_paths: `{', '.join(plan.prunable_route_paths) or 'none'}`",
        f"- pruned_permission_codes: `{', '.join(plan.prunable_permission_codes) or 'none'}`",
        "",
        "## Seed Data Requirements",
        "",
        *seed_requirement_lines,
        "",
        "## Support Dependencies",
        "",
        *support_dependency_lines,
        "",
        "This bundle contains a pruned backend/frontend project, generated runtime settings and URL routing, the exported blueprint snapshot, and a module lock file.",
        "Feature-level pruning in stage three removes registration entries for pages, menus, and permission declarations.",
        "Shared implementation files may still remain in the package unless the feature has been split into isolated page/hook/service boundaries.",
    ]
    (bundle_root / "README.generated.md").write_text(
        "\n".join(readme_lines),
        encoding="utf-8",
    )


def _build_backend_module_pruning_block(*, prunable_route_paths: tuple[str, ...], prunable_permission_codes: tuple[str, ...]) -> str:
    route_paths_json = json.dumps(list(prunable_route_paths), ensure_ascii=False, indent=2)
    permission_codes_json = json.dumps(list(prunable_permission_codes), ensure_ascii=False, indent=2)
    return (
        "\n\n# Generated by ERP export: feature-level backend metadata pruning.\n"
        "_EXPORT_PRUNED_ROUTE_PATHS = set("
        f"{route_paths_json}"
        ")\n"
        "_EXPORT_PRUNED_PERMISSION_CODES = set("
        f"{permission_codes_json}"
        ")\n"
        'object.__setattr__(\n'
        "    MODULE,\n"
        '    "menus",\n'
        '    tuple(menu for menu in MODULE.menus if menu.get("path") not in _EXPORT_PRUNED_ROUTE_PATHS),\n'
        ")\n"
        'object.__setattr__(\n'
        "    MODULE,\n"
        '    "permissions",\n'
        '    tuple(permission for permission in MODULE.permissions if permission.get("code") not in _EXPORT_PRUNED_PERMISSION_CODES),\n'
        ")\n"
    )


def _build_frontend_module_pruning_block(*, prunable_route_paths: tuple[str, ...], prunable_permission_codes: tuple[str, ...]) -> str:
    route_paths_json = json.dumps(list(prunable_route_paths), ensure_ascii=False, indent=2)
    permission_codes_json = json.dumps(list(prunable_permission_codes), ensure_ascii=False, indent=2)
    return (
        "\n\n// Generated by ERP export: feature-level frontend entry pruning.\n"
        f"const __EXPORT_PRUNED_ROUTE_PATHS = new Set({route_paths_json});\n"
        f"const __EXPORT_PRUNED_PERMISSION_CODES = new Set({permission_codes_json});\n"
        "module.menus = module.menus.filter((menu) => !__EXPORT_PRUNED_ROUTE_PATHS.has(menu.path));\n"
        "module.routes = module.routes.filter(\n"
        "  (route) => !__EXPORT_PRUNED_ROUTE_PATHS.has(route.path)\n"
        "    && !(route.permissionCode && __EXPORT_PRUNED_PERMISSION_CODES.has(route.permissionCode)),\n"
        ");\n"
    )


def _join_feature_names(plan: GenerationPlan, field_name: str) -> str:
    values: list[str] = []
    for module_key, contract in sorted(plan.module_feature_contracts.items()):
        for feature_key in contract.get(field_name, []):
            values.append(f"{module_key}.{feature_key}")
    return ", ".join(values) or "none"
