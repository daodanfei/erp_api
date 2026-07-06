from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import User, Role, Permission
from .serializers import UserSerializer, RoleSerializer, PermissionSerializer
from .services import generate_role_code

from core_apps.common.permissions import PlatformActionPermission, PlatformUserOnly

class PermissionViewSet(viewsets.ModelViewSet):
    queryset = Permission.objects.all().order_by('order')
    serializer_class = PermissionSerializer
    permission_classes = [permissions.IsAuthenticated, PlatformUserOnly, PlatformActionPermission]
    permission_map = {
        'list': 'system:perm',
        'retrieve': 'system:perm',
        'create': 'system:perm',
        'update': 'system:perm',
        'destroy': 'system:perm',
    }

class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    permission_classes = [permissions.IsAuthenticated, PlatformUserOnly, PlatformActionPermission]
    permission_map = {
        'list': 'system:role',
        'retrieve': 'system:role',
        'create': 'system:role',
        'update': 'system:role',
        'destroy': 'system:role',
    }

    def perform_create(self, serializer):
        serializer.save(code=generate_role_code(serializer.validated_data.get('name')))

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated, PlatformUserOnly, PlatformActionPermission]
    permission_map = {
        'list': 'system:user',
        'retrieve': 'system:user',
        'create': 'user:create',
        'update': 'user:update',
        'destroy': 'user:delete',
    }

    @action(detail=False, methods=['get'])
    def info(self, request):
        """
        Returns comprehensive user info including roles and permissions.
        """
        user = request.user
        serializer = self.get_serializer(user)
        
        # Get all permissions across all roles
        permissions = Permission.objects.filter(role__in=user.roles.all(), status=True).distinct()
        
        menu_perms = permissions.filter(type='MENU').order_by('order')
        button_perms = permissions.filter(type='BUTTON').values_list('code', flat=True)
        
        # Build menu tree
        menu_tree = self.build_menu_tree(menu_perms)
        
        return Response({
            'user': serializer.data,
            'menus': menu_tree,
            'permissions': button_perms
        })

    def build_menu_tree(self, queryset, parent=None):
        tree = []
        nodes = queryset.filter(parent=parent)
        for node in nodes:
            item = {
                'id': node.id,
                'name': node.name,
                'path': node.path,
                'component': node.component,
                'icon': node.icon,
                'code': node.code,
                'hide_in_menu': node.hide_in_menu,
                'children': self.build_menu_tree(queryset, node)
            }
            tree.append(item)
        return tree
