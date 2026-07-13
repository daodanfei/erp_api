from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal

from django.db import models
from rest_framework.response import Response


OPERATION_TARGET_PARAM = "_operation_target"
OPERATION_CHANGED_FIELDS_PARAM = "_changed_fields"
OPERATION_CHANGES_PARAM = "_changes"
MAX_OPERATION_LOG_CHANGES = 20
MAX_OPERATION_LOG_VALUE_LENGTH = 100


def is_sensitive_operation_log_field(field_name) -> bool:
    normalized = str(field_name).lower().replace("-", "_")
    return any(token in normalized for token in ("password", "token", "secret"))


def _truncate_value(value: str) -> str:
    compact = " ".join(value.split())
    if len(compact) <= MAX_OPERATION_LOG_VALUE_LENGTH:
        return compact
    return compact[: MAX_OPERATION_LOG_VALUE_LENGTH - 1] + "…"


def format_operation_log_value(value, *, model_field=None) -> str:
    if model_field is not None and getattr(model_field, "choices", None):
        choice_label = dict(model_field.flatchoices).get(value)
        if choice_label is not None:
            return _truncate_value(str(choice_label))
    if value is None or value == "":
        return "空"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, models.Model):
        return _truncate_value(str(value))
    if isinstance(value, Mapping):
        return f"{len(value)}项内容"
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        values = list(value)
        shown = [format_operation_log_value(item) for item in values[:5]]
        suffix = f"等{len(values)}项" if len(values) > 5 else ""
        return _truncate_value("、".join(shown) + suffix)
    return _truncate_value(str(value))


def _operation_log_change(field_name, old_value, new_value, *, model_field=None) -> dict[str, str]:
    return {
        "field": str(field_name),
        "old": format_operation_log_value(old_value, model_field=model_field),
        "new": format_operation_log_value(new_value, model_field=model_field),
    }


def collect_serializer_operation_log_changes(serializer) -> list[dict[str, str]]:
    """Collect only real serializer changes; no full model snapshot is retained."""
    instance = getattr(serializer, "instance", None)
    if instance is None:
        return []
    changes = []
    for field_name, new_value in serializer.validated_data.items():
        if is_sensitive_operation_log_field(field_name):
            continue
        try:
            model_field = instance._meta.get_field(field_name)
        except Exception:
            if field_name.endswith("_ids") and isinstance(new_value, Iterable):
                base_name = field_name[:-4]
                related_manager = getattr(instance, f"{base_name}s", None) or getattr(instance, base_name, None)
                if related_manager is not None and hasattr(related_manager, "all"):
                    old_objects = list(related_manager.all())
                    old_ids = {item.pk for item in old_objects}
                    new_ids = {getattr(item, "pk", item) for item in new_value}
                    if old_ids != new_ids:
                        new_objects = list(related_manager.model._default_manager.filter(pk__in=new_ids))
                        changes.append(_operation_log_change(field_name, old_objects, new_objects))
                    continue
            old_value = getattr(instance, field_name, None)
            if old_value != new_value:
                changes.append(_operation_log_change(field_name, old_value, new_value))
            continue

        if getattr(model_field, "many_to_many", False):
            old_objects = list(getattr(instance, field_name).all())
            old_ids = {item.pk for item in old_objects}
            new_objects = list(new_value)
            new_ids = {getattr(item, "pk", item) for item in new_objects}
            if old_ids != new_ids:
                changes.append(_operation_log_change(field_name, old_objects, new_objects, model_field=model_field))
        elif getattr(model_field, "is_relation", False):
            old_id = getattr(instance, model_field.attname)
            new_id = getattr(new_value, "pk", new_value)
            if old_id != new_id:
                # Only load the old related label when that relation really changed.
                old_object = getattr(instance, field_name, None) if old_id is not None else None
                changes.append(_operation_log_change(field_name, old_object, new_value, model_field=model_field))
        else:
            old_value = getattr(instance, field_name)
            if old_value != new_value:
                changes.append(_operation_log_change(field_name, old_value, new_value, model_field=model_field))
        if len(changes) >= MAX_OPERATION_LOG_CHANGES:
            break
    return changes


def set_operation_log_changes(request, changes: list[dict[str, str]]) -> None:
    compact_changes = changes[:MAX_OPERATION_LOG_CHANGES]
    request.operation_log_changes = compact_changes
    django_request = getattr(request, "_request", None)
    if django_request is not None:
        django_request.operation_log_changes = compact_changes


def build_operation_log_change(field_name, old_value, new_value, *, model_field=None) -> dict[str, str]:
    """Public helper for service-driven updates that do not use a writable serializer."""
    return _operation_log_change(field_name, old_value, new_value, model_field=model_field)


def build_operation_log_new_value(field_name, new_value) -> dict[str, str]:
    return {
        "field": str(field_name),
        "old": "",
        "new": format_operation_log_value(new_value),
    }


class OperationLogChangeTracker:
    """Lightweight before/after tracker for service-driven model updates."""

    def __init__(self, instance, submitted_data):
        self._captured = []
        if not isinstance(submitted_data, Mapping):
            return
        for field_name in submitted_data:
            if is_sensitive_operation_log_field(field_name):
                continue
            try:
                model_field = instance._meta.get_field(field_name)
            except Exception:
                continue
            if getattr(model_field, "many_to_many", False):
                continue
            if getattr(model_field, "is_relation", False):
                old_comparison = getattr(instance, model_field.attname)
                submitted_value = submitted_data.get(field_name)
                submitted_id = getattr(submitted_value, "pk", submitted_value)
                old_value = old_comparison
                if str(old_comparison or "") != str(submitted_id or ""):
                    old_value = getattr(instance, field_name, None) if old_comparison is not None else None
            else:
                old_comparison = getattr(instance, field_name)
                old_value = old_comparison
            self._captured.append((field_name, model_field, old_comparison, old_value))

    def finish(self, request, updated_instance, *, extra_changes=None):
        changes = []
        for field_name, model_field, old_comparison, old_value in self._captured:
            if getattr(model_field, "is_relation", False):
                new_comparison = getattr(updated_instance, model_field.attname)
                new_value = getattr(updated_instance, field_name, None) if new_comparison is not None else None
            else:
                new_comparison = getattr(updated_instance, field_name)
                new_value = new_comparison
            if old_comparison != new_comparison:
                changes.append(build_operation_log_change(
                    field_name,
                    old_value,
                    new_value,
                    model_field=model_field,
                ))
        changes.extend(extra_changes or [])
        set_operation_log_changes(request, changes)
        return changes


def summarize_operation_log_items(items) -> str:
    items = list(items or [])
    if not items:
        return "0条商品明细"
    summaries = []
    for item in items[:3]:
        product = item.get("product") if isinstance(item, Mapping) else None
        quantity = item.get("quantity") if isinstance(item, Mapping) else None
        product_name = getattr(product, "name", None) or str(product or "商品")
        summaries.append(f"{product_name}×{quantity}")
    suffix = f"等{len(items)}条" if len(items) > 3 else f"，共{len(items)}条"
    return "、".join(summaries) + suffix


class OperationLogModelViewSetMixin:
    """Unified update path for ERP model CRUD operation-log differences."""

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        set_operation_log_changes(request, collect_serializer_operation_log_changes(serializer))
        self.perform_update(serializer)

        if getattr(instance, "_prefetched_objects_cache", None):
            instance._prefetched_objects_cache = {}

        return Response(serializer.data)
