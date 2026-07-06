import re

from django.utils.text import slugify


def _next_fallback_role_code():
    from .models import Role

    max_suffix = 0
    for code in Role.objects.filter(code__startswith="role_").values_list("code", flat=True):
        match = re.fullmatch(r"role_(\d{4})", code)
        if match:
            max_suffix = max(max_suffix, int(match.group(1)))
    return f"role_{max_suffix + 1:04d}"


def generate_role_code(role_name: str) -> str:
    from .models import Role

    base_code = slugify((role_name or "").strip()).replace("-", "_")
    if not base_code:
        return _next_fallback_role_code()

    candidate = base_code
    index = 2
    while Role.objects.filter(code=candidate).exists():
        candidate = f"{base_code}_{index}"
        index += 1
    return candidate
