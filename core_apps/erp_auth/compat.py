from __future__ import annotations

from .models import ERPDepartment, ERPUser


def as_erp_user(user):
    return user if isinstance(user, ERPUser) else None


def get_erp_user_id(user):
    erp_user = as_erp_user(user)
    return erp_user.id if erp_user is not None else None


def build_erp_user_fk_kwargs(model, *, user=None, field_names: tuple[str, ...] = ()) -> dict:
    erp_user = as_erp_user(user)
    if erp_user is None:
        return {}

    kwargs = {}
    for field_name in field_names:
        try:
            field = model._meta.get_field(field_name)
        except Exception:
            continue
        remote_model = getattr(getattr(field, "remote_field", None), "model", None)
        if remote_model is ERPUser:
            kwargs[field_name] = erp_user
    return kwargs


def build_erp_user_and_dept_kwargs(model, *, user=None, user_field: str = "created_by", dept_field: str = "dept") -> dict:
    kwargs = build_erp_user_fk_kwargs(model, user=user, field_names=(user_field,))
    erp_user = as_erp_user(user)
    if erp_user is None:
        return kwargs
    try:
        dept_model_field = model._meta.get_field(dept_field)
    except Exception:
        return kwargs
    remote_model = getattr(getattr(dept_model_field, "remote_field", None), "model", None)
    if remote_model is ERPDepartment and hasattr(erp_user, "dept"):
        kwargs[dept_field] = erp_user.dept
    return kwargs
