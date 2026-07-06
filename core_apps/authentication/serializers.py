from rest_framework import serializers
from .models import User, Role, Permission
from core_apps.organization.models import Department

class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = '__all__'

class RoleSerializer(serializers.ModelSerializer):
    permissions = PermissionSerializer(many=True, read_only=True)
    permission_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Permission.objects.all(), source='permissions', write_only=True, required=False
    )

    class Meta:
        model = Role
        fields = '__all__'
        read_only_fields = ('code',)

class UserSerializer(serializers.ModelSerializer):
    dept_name = serializers.CharField(source='dept.name', read_only=True)
    role_names = serializers.SerializerMethodField()
    role_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Role.objects.all(), source='roles', write_only=True
    )
    password = serializers.CharField(write_only=True, required=False, allow_blank=False)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 
            'dept', 'dept_name', 'roles', 'role_names', 'role_ids', 
            'phone', 'status', 'is_superuser', 'password'
        ]
        read_only_fields = ('is_superuser',)

    def get_role_names(self, obj):
        return [role.name for role in obj.roles.all()]

    def validate(self, attrs):
        if self.instance is None and not attrs.get('password'):
            raise serializers.ValidationError({'password': '创建用户时必须设置密码'})
        return attrs

    def create(self, validated_data):
        roles = validated_data.pop('roles', [])
        password = validated_data.pop('password')
        user = User.objects.create(**validated_data)
        user.set_password(password)
        user.save()
        user.roles.set(roles)
        return user

    def update(self, instance, validated_data):
        roles = validated_data.pop('roles', None)
        password = validated_data.pop('password', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()

        if roles is not None:
            instance.roles.set(roles)

        return instance
