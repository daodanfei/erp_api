from rest_framework import serializers
from .models import Department

class DepartmentSerializer(serializers.ModelSerializer):
    def validate_parent(self, value):
        instance = getattr(self, "instance", None)
        if not value:
            return value

        if instance and value.pk == instance.pk:
            raise serializers.ValidationError("上级部门不能是当前部门本身")

        current = value
        while current:
            if instance and current.pk == instance.pk:
                raise serializers.ValidationError("上级部门不能形成循环层级")
            current = current.parent

        return value

    class Meta:
        model = Department
        fields = '__all__'

class DepartmentTreeSerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = ['id', 'name', 'parent', 'order', 'leader', 'phone', 'email', 'status', 'children']

    def get_children(self, obj):
        visited_ids = set(self.context.get("visited_ids", set()))
        if obj.id in visited_ids:
            return []

        next_visited_ids = visited_ids | {obj.id}
        children = obj.children.exclude(id__in=next_visited_ids).order_by("order", "id")
        return DepartmentTreeSerializer(
            children,
            many=True,
            context={**self.context, "visited_ids": next_visited_ids},
        ).data
