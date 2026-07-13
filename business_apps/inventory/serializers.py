from rest_framework import serializers

from core_apps.common.authz import has_erp_role_permission
from core_apps.erp_auth.compat import get_erp_user_id
from core_apps.policies.registry import get_policy

from .features import FIELD_INVENTORY_TRANSACTION_WAREHOUSE, FIELD_STOCKTAKE_WAREHOUSE
from .models import Product, ProductCategory, Unit, ProductImage, ProductAttachment, ProductTag, Warehouse, Inventory, InventoryTransaction, Stocktake, StocktakeItem


class WarehouseFieldRuleSerializerMixin:
    warehouse_field_rule_key = ""

    def _get_warehouse_field_rule(self):
        if not self.warehouse_field_rule_key:
            return {"visible": True, "required": False, "readonly": False}
        request = self.context.get("request")
        if request is None or not getattr(request.user, "is_authenticated", False):
            return {"visible": True, "required": False, "readonly": False}
        policy = get_policy("inventory", user=request.user)
        return policy.get_field_rule(self.warehouse_field_rule_key)

    def get_fields(self):
        fields = super().get_fields()
        rule = self._get_warehouse_field_rule()
        if not rule.get("visible", True):
            fields.pop("warehouse", None)
            fields.pop("warehouse_name", None)
        return fields

class ProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = '__all__'

    def validate_parent(self, value):
        if value is None:
            return value
        request = self.context.get("request")
        if request is None or not getattr(request.user, "is_authenticated", False):
            return value
        tenant = getattr(request.user, "tenant", None)
        if tenant is None:
            return value
        if value.tenant_id is not None and value.tenant_id != tenant.id:
            raise serializers.ValidationError("上级分类不属于当前租户")
        instance = getattr(self, "instance", None)
        if instance is not None and value.id == instance.id:
            raise serializers.ValidationError("上级分类不能选择自己")
        if value.status is False:
            raise serializers.ValidationError("禁用分类不能作为上级分类")
        current = value
        while current is not None:
            if instance is not None and current.id == instance.id:
                raise serializers.ValidationError("不能形成分类循环关系")
            current = current.parent
        return value

class ProductCategoryTreeSerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()
    parent_name = serializers.CharField(source='parent.name', read_only=True)

    class Meta:
        model = ProductCategory
        fields = ['id', 'name', 'parent', 'parent_name', 'sort', 'status', 'remark', 'children']

    def get_children(self, obj):
        children = obj.children.all().order_by('sort', 'id')
        request = self.context.get("request")
        if request is not None and getattr(request.user, "is_authenticated", False):
            tenant = getattr(request.user, "tenant", None)
            if tenant is not None:
                children = children.filter(tenant=tenant)
        return ProductCategoryTreeSerializer(children, many=True).data

class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = '__all__'
        read_only_fields = ('code',)

class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = '__all__'

class ProductAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductAttachment
        fields = '__all__'

class ProductTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductTag
        fields = '__all__'

class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    unit_name = serializers.CharField(source='unit.name', read_only=True)
    unit_code = serializers.CharField(source='unit.code', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    tags = ProductTagSerializer(many=True, read_only=True)
    tag_ids = serializers.PrimaryKeyRelatedField(many=True, queryset=ProductTag.objects.all(), source='tags', write_only=True, required=False)
    images = ProductImageSerializer(many=True, read_only=True)
    
    class Meta:
        model = Product
        fields = '__all__'
        read_only_fields = (
            'product_code', 'current_stock', 'created_by', 'dept', 
            'is_deleted', 'deleted_at', 'deleted_by'
        )

    def validate_category(self, value):
        if value is None:
            return value
        if value.status is False:
            raise serializers.ValidationError("禁用商品分类不能用于商品")
        return value

    def validate_unit(self, value):
        if value is None:
            return value
        if value.status is False:
            raise serializers.ValidationError("禁用计量单位不能用于商品")
        return value

class WarehouseSerializer(serializers.ModelSerializer):
    manager_name = serializers.CharField(source='manager.username', read_only=True)
    class Meta:
        model = Warehouse
        fields = '__all__'
        read_only_fields = ('warehouse_code',)


class ActiveWarehouseValidationMixin:
    def validate_warehouse(self, value):
        if value is None:
            return value
        if value.status is False:
            raise serializers.ValidationError("禁用仓库不能用于业务")
        return value

class InventorySerializer(WarehouseFieldRuleSerializerMixin, serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source='warehouse.warehouse_name', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.product_code', read_only=True)
    available_qty = serializers.ReadOnlyField()
    sellable_qty = serializers.SerializerMethodField()
    warehouse_field_rule = serializers.SerializerMethodField()
    warehouse_field_rule_key = FIELD_INVENTORY_TRANSACTION_WAREHOUSE
    
    class Meta:
        model = Inventory
        fields = '__all__'

    def get_warehouse_field_rule(self, obj):
        return self._get_warehouse_field_rule()

    def get_sellable_qty(self, obj):
        from business_apps.sales.services import SalesOrderService

        committed_qty = SalesOrderService.get_open_sales_commitment_quantity(
            warehouse=obj.warehouse,
            product=obj.product,
        )
        sellable_qty = obj.current_qty - committed_qty
        return max(sellable_qty, 0)

class InventoryTransactionSerializer(WarehouseFieldRuleSerializerMixin, serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source='warehouse.warehouse_name', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    warehouse_field_rule = serializers.SerializerMethodField()
    warehouse_field_rule_key = FIELD_INVENTORY_TRANSACTION_WAREHOUSE
    
    class Meta:
        model = InventoryTransaction
        fields = '__all__'

    def get_warehouse_field_rule(self, obj):
        return self._get_warehouse_field_rule()

class StocktakeItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.product_code', read_only=True)
    difference_qty = serializers.ReadOnlyField()
    
    class Meta:
        model = StocktakeItem
        fields = '__all__'

class StocktakeSerializer(WarehouseFieldRuleSerializerMixin, ActiveWarehouseValidationMixin, serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source='warehouse.warehouse_name', read_only=True)
    creator_name = serializers.CharField(source='created_by.username', read_only=True)
    submitted_by_name = serializers.CharField(source='submitted_by.username', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.username', read_only=True)
    items = StocktakeItemSerializer(many=True, read_only=True)
    warehouse_field_rule = serializers.SerializerMethodField()
    can_approve = serializers.SerializerMethodField()
    warehouse_field_rule_key = FIELD_STOCKTAKE_WAREHOUSE
    
    class Meta:
        model = Stocktake
        fields = '__all__'
        read_only_fields = (
            'stocktake_no',
            'status',
            'created_by',
            'submitted_by',
            'submitted_at',
            'approved_by',
            'approved_at',
            'created_at',
            'completed_at',
            'is_deleted',
            'tenant',
        )
        extra_kwargs = {
            'warehouse': {'required': False, 'allow_null': True},
        }

    def get_warehouse_field_rule(self, obj):
        return self._get_warehouse_field_rule()

    def get_can_approve(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        if obj.status != "PENDING_APPROVAL":
            return False
        erp_user_id = get_erp_user_id(user)
        if erp_user_id is not None and (
            obj.created_by_id == erp_user_id or obj.submitted_by_id == erp_user_id
        ):
            return False
        return has_erp_role_permission(user, STOCKTAKE_APPROVE_PERMISSION_CODE)
STOCKTAKE_APPROVE_PERMISSION_CODE = "inventory:stocktake:approve"
