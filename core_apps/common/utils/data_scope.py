from django.db.models import Q
from core_apps.authentication.models import User as PlatformUser
from core_apps.common.authz import has_erp_full_data_scope, has_platform_full_data_scope
from core_apps.erp_auth.models import ERPUser
from core_apps.erp_auth.data_permissions import get_department_descendant_ids

def get_data_scope_filter(user, dept_field='dept', user_field='created_by'):
    """
    Returns a Q object based on user's roles data scopes.
    Supports ALL, SELF, DEPARTMENT.
    """
    roles_manager = getattr(user, "roles", None)
    if roles_manager is None:
        return Q()

    roles = roles_manager.filter(status=True)
    if not roles.exists():
        return Q(pk__isnull=True) if not hasattr(user, "dept") else Q(**{user_field: user})

    # If user has multiple roles, we take the most permissive one
    scopes = [role.data_scope for role in roles]
    
    if isinstance(user, ERPUser) and has_erp_full_data_scope(user):
        return Q()
    if isinstance(user, PlatformUser) and has_platform_full_data_scope(user):
        return Q()
    if 'ALL' in scopes:
        return Q()
    
    q_filter = Q()
    if 'DEPARTMENT' in scopes:
        user_dept = getattr(user, "dept", None)
        if user_dept:
            q_filter |= Q(**{f"{dept_field}__in": get_department_descendant_ids(user_dept)})
        else:
            # A user without a department can only retain self visibility.
            q_filter |= Q(**{user_field: user})
            
    if 'SELF' in scopes:
        q_filter |= Q(**{user_field: user})
        
    return q_filter or Q(pk__isnull=True)
