from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db import transaction
from django.utils import timezone
from django.db.models import Q
import logging
import time
from core_apps.common.viewsets import (
    BaseBusinessViewSet,
    ModuleAwareModelViewSet,
    ModuleAwareReadOnlyViewSet,
    build_erp_tenant_save_kwargs,
    validate_erp_related_tenant_scope,
)
from core_apps.erp_auth.compat import build_erp_user_and_dept_kwargs, build_erp_user_fk_kwargs
from core_apps.erp_auth.compat import as_erp_user
from core_apps.common.utils.data_scope import get_data_scope_filter
from core_apps.tenant.services import TenantService
from .models import Product, ProductCategory, Unit, ProductImage, ProductAttachment, ProductTag, Warehouse, Inventory, InventoryTransaction, Stocktake, StocktakeItem
from .serializers import (
    ProductSerializer, ProductCategorySerializer, ProductCategoryTreeSerializer,
    UnitSerializer, ProductImageSerializer, ProductAttachmentSerializer, ProductTagSerializer,
    WarehouseSerializer, InventorySerializer, InventoryTransactionSerializer, StocktakeSerializer, StocktakeItemSerializer
)
from .services import generate_product_code, generate_stocktake_no, generate_unit_code, generate_warehouse_code, check_duplicate_product, check_can_delete_product, InventoryService
from core_apps.policies.registry import get_policy
import csv
from django.http import HttpResponse

MODULE_KEY = "inventory"
STOCKTAKE_APPROVE_PERMISSION_CODE = "inventory:stocktake:approve"
STOCKTAKE_COMPLETE_PERMISSION_CODE = "inventory:stocktake:complete"
logger = logging.getLogger(__name__)


class ProductCategoryViewSet(ModuleAwareModelViewSet):
    module_key = MODULE_KEY
    queryset = ProductCategory.objects.all()
    serializer_class = ProductCategorySerializer
    permission_map = {
        'list': 'inventory:category:view',
        'retrieve': 'inventory:category:view',
        'create': 'inventory:category:create',
        'update': 'inventory:category:update',
        'partial_update': 'inventory:category:update',
        'destroy': 'inventory:category:delete',
    }

    def get_queryset(self):
        queryset = super().get_queryset().order_by('sort', 'id')
        if self.action == 'list' and self.request.query_params.get('tree'):
            return queryset.filter(parent__isnull=True).prefetch_related('children')
        return queryset
    
    def get_serializer_class(self):
        if self.action == 'list' and self.request.query_params.get('tree'):
            return ProductCategoryTreeSerializer
        return ProductCategorySerializer

    def destroy(self, request, *args, **kwargs):
        category = self.get_object()
        child_categories = category.children.all().order_by("id")
        if child_categories.exists():
            sample_names = "、".join(child_categories.values_list("name", flat=True)[:3])
            suffix = "等子分类" if child_categories.count() > 3 else ""
            return Response(
                {
                    "detail": (
                        f"无法删除分类「{category.name}」：存在下级分类"
                        f"（如：{sample_names}{suffix}）。请先处理下级分类后再删除。"
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        used_products = category.products.filter(is_deleted=False).order_by("id")
        if used_products.exists():
            sample_names = "、".join(used_products.values_list("name", flat=True)[:3])
            suffix = "等商品" if used_products.count() > 3 else ""
            return Response(
                {
                    "detail": (
                        f"无法删除分类「{category.name}」：已有商品使用该分类"
                        f"（如：{sample_names}{suffix}）。请先修改或删除相关商品后再删除分类。"
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return super().destroy(request, *args, **kwargs)

class UnitViewSet(ModuleAwareModelViewSet):
    module_key = MODULE_KEY
    queryset = Unit.objects.all()
    serializer_class = UnitSerializer
    permission_map = {
        'list': 'inventory:unit:view',
        'retrieve': 'inventory:unit:view',
        'create': 'inventory:unit:create',
        'update': 'inventory:unit:update',
        'partial_update': 'inventory:unit:update',
        'destroy': 'inventory:unit:delete',
    }

    def get_queryset(self):
        return super().get_queryset().order_by("id")

    def _log_unit_request(self, level: str, event: str, **extra):
        user = getattr(self.request, "user", None)
        tenant = getattr(user, "tenant", None)
        payload = {
            "event": event,
            "action": getattr(self, "action", None),
            "method": getattr(self.request, "method", None),
            "path": getattr(self.request, "path", None),
            "tenant_id": getattr(tenant, "id", None),
            "tenant_code": getattr(tenant, "code", None),
            "user_id": getattr(user, "id", None),
            "username": getattr(user, "username", None),
            **extra,
        }
        getattr(logger, level)("inventory.units %s", payload)

    def list(self, request, *args, **kwargs):
        started_at = time.monotonic()
        self._log_unit_request("info", "list.start")
        try:
            response = super().list(request, *args, **kwargs)
            count = len(response.data) if isinstance(response.data, list) else None
            self._log_unit_request(
                "info",
                "list.success",
                status_code=response.status_code,
                duration_ms=round((time.monotonic() - started_at) * 1000, 2),
                result_count=count,
            )
            return response
        except Exception:
            self._log_unit_request(
                "exception",
                "list.error",
                duration_ms=round((time.monotonic() - started_at) * 1000, 2),
            )
            raise

    def create(self, request, *args, **kwargs):
        started_at = time.monotonic()
        self._log_unit_request("info", "create.start", payload_keys=sorted(request.data.keys()))
        try:
            response = super().create(request, *args, **kwargs)
            self._log_unit_request(
                "info",
                "create.success",
                status_code=response.status_code,
                duration_ms=round((time.monotonic() - started_at) * 1000, 2),
                unit_id=response.data.get("id") if isinstance(response.data, dict) else None,
                unit_code=response.data.get("code") if isinstance(response.data, dict) else None,
            )
            return response
        except Exception:
            self._log_unit_request(
                "exception",
                "create.error",
                duration_ms=round((time.monotonic() - started_at) * 1000, 2),
                payload=request.data,
            )
            raise

    def update(self, request, *args, **kwargs):
        started_at = time.monotonic()
        self._log_unit_request("info", "update.start", unit_id=kwargs.get("pk"), payload_keys=sorted(request.data.keys()))
        try:
            response = super().update(request, *args, **kwargs)
            self._log_unit_request(
                "info",
                "update.success",
                unit_id=kwargs.get("pk"),
                status_code=response.status_code,
                duration_ms=round((time.monotonic() - started_at) * 1000, 2),
            )
            return response
        except Exception:
            self._log_unit_request(
                "exception",
                "update.error",
                unit_id=kwargs.get("pk"),
                duration_ms=round((time.monotonic() - started_at) * 1000, 2),
                payload=request.data,
            )
            raise

    def destroy(self, request, *args, **kwargs):
        started_at = time.monotonic()
        self._log_unit_request("info", "destroy.start", unit_id=kwargs.get("pk"))
        try:
            response = super().destroy(request, *args, **kwargs)
            self._log_unit_request(
                "info",
                "destroy.success",
                unit_id=kwargs.get("pk"),
                status_code=response.status_code,
                duration_ms=round((time.monotonic() - started_at) * 1000, 2),
            )
            return response
        except Exception:
            self._log_unit_request(
                "exception",
                "destroy.error",
                unit_id=kwargs.get("pk"),
                duration_ms=round((time.monotonic() - started_at) * 1000, 2),
            )
            raise

    def perform_create(self, serializer):
        validate_erp_related_tenant_scope(self.queryset.model, validated_data=serializer.validated_data, user=self.request.user)
        serializer.save(
            code=generate_unit_code(),
            **build_erp_tenant_save_kwargs(self.queryset.model, user=self.request.user),
        )

    def destroy(self, request, *args, **kwargs):
        unit = self.get_object()
        used_products = unit.products.filter(is_deleted=False).order_by('id')
        if used_products.exists():
            sample_names = "、".join(used_products.values_list('name', flat=True)[:3])
            suffix = "等商品" if used_products.count() > 3 else ""
            return Response(
                {
                    "detail": (
                        f"无法删除单位「{unit.name}」：已有商品使用该单位"
                        f"（如：{sample_names}{suffix}）。请先修改或删除相关商品后再删除单位。"
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

class ProductViewSet(BaseBusinessViewSet):
    module_key = MODULE_KEY
    queryset = Product.objects.filter(is_deleted=False)
    serializer_class = ProductSerializer
    user_field = 'created_by'
    
    permission_map = {
        'list': 'inventory:product:view',
        'retrieve': 'inventory:product:view',
        'create': 'inventory:product:create',
        'update': 'inventory:product:update',
        'destroy': 'inventory:product:delete',
        'export': 'inventory:product:export',
        'import_data': 'inventory:product:import',
    }

    filterset_fields = ['category', 'status', 'brand']
    search_fields = ['product_code', 'barcode', 'name', 'specification']

    def perform_create(self, serializer):
        # 1. Duplication check
        errors = check_duplicate_product(
            self.request.data.get('name'),
            self.request.data.get('barcode'),
            tenant=self.request.user.tenant
        )
        if errors:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"detail": errors})
        
        validate_erp_related_tenant_scope(self.queryset.model, validated_data=serializer.validated_data, user=self.request.user)
        # 2. Set code and owner
        serializer.save(
            product_code=generate_product_code(),
            **build_erp_tenant_save_kwargs(Product, user=self.request.user),
            **build_erp_user_and_dept_kwargs(Product, user=self.request.user),
        )

    def perform_update(self, serializer):
        errors = check_duplicate_product(
            self.request.data.get('name', serializer.instance.name),
            self.request.data.get('barcode', serializer.instance.barcode),
            exclude_id=serializer.instance.id,
            tenant=self.request.user.tenant,
        )
        if errors:
            raise ValidationError({"detail": errors})

        validate_erp_related_tenant_scope(self.queryset.model, validated_data=serializer.validated_data, user=self.request.user)
        serializer.save()

    def perform_destroy(self, instance):
        # Prevent deletion if product is in use
        reasons = check_can_delete_product(instance)
        if reasons:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"detail": f"无法删除商品：{', '.join(reasons)}"})
            
        # Soft delete
        instance.is_deleted = True
        instance.deleted_at = timezone.now()
        erp_user_kwargs = build_erp_user_fk_kwargs(Product, user=self.request.user, field_names=("deleted_by",))
        instance.deleted_by = erp_user_kwargs.get("deleted_by")
        instance.save()

    @action(detail=False, methods=['get'])
    def export(self, request):
        """Basic CSV Export as a starting point for Excel capability"""
        queryset = self.get_queryset()
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="products.csv"'
        
        # Write BOM for Excel UTF-8 support
        response.write(u'\ufeff'.encode('utf8'))
        
        writer = csv.writer(response)
        writer.writerow(['商品编码', '条码', '名称', '规格', '分类', '单位', '成本价', '销售价', '库存', '状态'])
        
        for p in queryset:
            writer.writerow([
                p.product_code, p.barcode, p.name, p.specification,
                p.category.name if p.category else '',
                p.unit.name if p.unit else '',
                p.cost_price, p.sale_price, p.current_stock, p.status
            ])
            
        return response

    @action(detail=False, methods=['post'])
    def import_data(self, request):
        # Placeholder for Excel import
        return Response({"detail": "导入功能正在开发中"}, status=status.HTTP_200_OK)

class ProductImageViewSet(ModuleAwareModelViewSet):
    module_key = MODULE_KEY
    queryset = ProductImage.objects.all()
    serializer_class = ProductImageSerializer

class ProductAttachmentViewSet(ModuleAwareModelViewSet):
    module_key = MODULE_KEY
    queryset = ProductAttachment.objects.all()
    serializer_class = ProductAttachmentSerializer

class ProductTagViewSet(ModuleAwareModelViewSet):
    module_key = MODULE_KEY
    queryset = ProductTag.objects.all()
    serializer_class = ProductTagSerializer

class WarehouseViewSet(ModuleAwareModelViewSet):
    module_key = MODULE_KEY
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer
    permission_map = {
        'list': 'inventory:warehouse:view',
        'retrieve': 'inventory:warehouse:view',
        'create': 'inventory:warehouse:create',
        'update': 'inventory:warehouse:update',
        'destroy': 'inventory:warehouse:delete',
    }

    def perform_create(self, serializer):
        validate_erp_related_tenant_scope(self.queryset.model, validated_data=serializer.validated_data, user=self.request.user)
        serializer.save(
            warehouse_code=generate_warehouse_code(),
            **build_erp_tenant_save_kwargs(self.queryset.model, user=self.request.user),
        )

    def perform_update(self, serializer):
        warehouse = serializer.instance
        next_status = serializer.validated_data.get("status", warehouse.status)
        if warehouse.status and next_status is False:
            runtime_config = TenantService.get_runtime_config(self.request.user.tenant)
            try:
                InventoryService.validate_warehouse_can_be_disabled(
                    warehouse=warehouse,
                    runtime_config=runtime_config,
                )
            except ValueError as exc:
                raise ValidationError({"detail": str(exc)}) from exc
        validate_erp_related_tenant_scope(self.queryset.model, validated_data=serializer.validated_data, user=self.request.user)
        serializer.save()

    def perform_destroy(self, instance):
        runtime_config = TenantService.get_runtime_config(self.request.user.tenant)
        try:
            InventoryService.validate_warehouse_can_be_deleted(
                warehouse=instance,
                runtime_config=runtime_config,
            )
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        instance.delete()

class InventoryViewSet(BaseBusinessViewSet):
    module_key = MODULE_KEY
    queryset = Inventory.objects.all()
    serializer_class = InventorySerializer
    filterset_fields = ['warehouse', 'product']
    dept_field = 'warehouse__manager__dept'
    user_field = 'warehouse__manager'
    permission_map = {
        'list': 'inventory:inventory:view',
        'retrieve': 'inventory:inventory:view',
        'adjust': 'inventory:inventory:adjust',
    }
    
    def get_queryset(self):
        queryset = super().get_queryset()
        alert_type = self.request.query_params.get('alert')
        
        if alert_type == 'LOW_STOCK':
            queryset = queryset.filter(current_qty__lt=models.F('product__min_stock'))
        elif alert_type == 'OUT_OF_STOCK':
            queryset = queryset.filter(current_qty=0)
        elif alert_type == 'OVER_STOCK':
            queryset = queryset.filter(current_qty__gt=models.F('product__max_stock'))
            
        return queryset
    
    @action(detail=False, methods=['post'])
    def adjust(self, request):
        """Manual inventory adjustment"""
        warehouse_id = request.data.get('warehouse')
        product_id = request.data.get('product')
        quantity = request.data.get('quantity')
        remark = request.data.get('remark')

        if not all([product_id, quantity, remark]):
            return Response({"detail": "缺少必要参数"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            product = self.get_scoped_related_object(Product.objects.filter(is_deleted=False), id=product_id)
            policy = get_policy("inventory", user=request.user)
            warehouse = policy.resolve_warehouse(warehouse_id)
            InventoryService.change_stock(
                warehouse=warehouse,
                product=product,
                quantity=float(quantity),
                transaction_type='MANUAL_ADJUST',
                operator=request.user,
                remark=remark
            )
            return Response({"status": "success"})
        except ObjectDoesNotExist:
            return Response({"detail": "关联数据不存在或不属于当前租户"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class InventoryTransactionViewSet(ModuleAwareReadOnlyViewSet):
    module_key = MODULE_KEY
    queryset = InventoryTransaction.objects.all()
    serializer_class = InventoryTransactionSerializer
    filterset_fields = ['warehouse', 'product', 'transaction_type']

class StocktakeViewSet(ModuleAwareModelViewSet):
    module_key = MODULE_KEY
    queryset = Stocktake.objects.filter(is_deleted=False).select_related(
        "warehouse",
        "created_by",
    ).prefetch_related("items__product")
    serializer_class = StocktakeSerializer
    dept_field = "created_by__dept"
    user_field = "created_by"
    permission_map = {
        'list': 'inventory:stocktake:view',
        'retrieve': 'inventory:stocktake:view',
        'create': 'inventory:stocktake:create',
        'update': 'inventory:stocktake:update',
        'destroy': 'inventory:stocktake:delete',
        'submit': 'inventory:stocktake:update',
        'approve': 'inventory:stocktake:approve',
        'complete': 'inventory:stocktake:complete',
        'add_items': 'inventory:stocktake:update',
        'update_items': 'inventory:stocktake:update',
    }

    def initial(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            policy = get_policy("inventory", user=request.user)
            if not policy.stocktake_enabled():
                raise ValidationError({"detail": "当前配置未启用库存盘点"})
        return super().initial(request, *args, **kwargs)

    def get_queryset(self):
        queryset = self.get_tenant_scoped_queryset()
        if self.get_data_permission_type(queryset) != "BUSINESS":
            return self.apply_data_permission_scope(queryset)
        user = self.request.user
        scope_q = get_data_scope_filter(user, dept_field=self.dept_field, user_field=self.user_field)
        if not scope_q.children:
            return queryset.distinct()

        visible_q = scope_q
        erp_user = as_erp_user(user)
        if getattr(self, "action", None) in ["list", "retrieve", "approve"] and user.roles.filter(
            permissions__code=STOCKTAKE_APPROVE_PERMISSION_CODE,
            permissions__status=True,
            status=True,
        ).exists():
            pending_q = Q(status="PENDING_APPROVAL")
            if erp_user is not None:
                pending_q &= ~Q(created_by=erp_user) & ~Q(submitted_by=erp_user)
            visible_q |= pending_q

        if getattr(self, "action", None) in ["list", "retrieve", "complete"] and user.roles.filter(
            permissions__code=STOCKTAKE_COMPLETE_PERMISSION_CODE,
            permissions__status=True,
            status=True,
        ).exists():
            visible_q |= Q(status="APPROVED")

        return queryset.filter(visible_q).distinct()

    def perform_create(self, serializer):
        policy = get_policy("inventory", user=self.request.user)
        try:
            warehouse = policy.resolve_warehouse(serializer.validated_data.get("warehouse"))
        except (ValueError, ObjectDoesNotExist) as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        stocktake = serializer.save(
            tenant=warehouse.tenant,
            warehouse=warehouse,
            stocktake_no=generate_stocktake_no(),
            status="DRAFT",
            **build_erp_user_fk_kwargs(Stocktake, user=self.request.user, field_names=("created_by",)),
        )
        InventoryService.ensure_stocktake_items(stocktake)

    def retrieve(self, request, *args, **kwargs):
        stocktake = self.get_object()
        InventoryService.ensure_stocktake_items(stocktake)
        stocktake = self.get_queryset().get(pk=stocktake.pk)
        serializer = self.get_serializer(stocktake)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        stocktake = self.get_object()
        try:
            InventoryService.ensure_stocktake_items(stocktake)
            summary = InventoryService.complete_stocktake(stocktake, request.user)
            return Response({"status": "success", "summary": summary})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        stocktake = self.get_object()
        try:
            InventoryService.submit_stocktake(stocktake, request.user)
            return Response({"status": "pending_approval"})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        stocktake = self.get_object()
        try:
            InventoryService.approve_stocktake(stocktake, request.user)
            return Response({"status": "approved"})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def add_items(self, request, pk=None):
        stocktake = self.get_object()
        items_data = request.data.get('items', [])
        try:
            for item in items_data:
                product = self.get_scoped_related_object(Product.objects.filter(is_deleted=False), id=item['product'])
                StocktakeItem.objects.create(
                    tenant=stocktake.tenant,
                    stocktake=stocktake,
                    product=product,
                    system_qty=item['system_qty'],
                    actual_qty=item['actual_qty'],
                    remark=item.get('remark')
                )
        except ObjectDoesNotExist:
            return Response({"detail": "关联数据不存在或不属于当前租户"}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"status": "success"})

    @action(detail=True, methods=['post'])
    def update_items(self, request, pk=None):
        stocktake = self.get_object()
        if stocktake.status not in ('DRAFT', 'IN_PROGRESS'):
            return Response({"detail": "只有草稿或盘点中的盘点单可以录入实盘数量"}, status=status.HTTP_400_BAD_REQUEST)

        items_data = request.data.get('items', [])
        if not isinstance(items_data, list) or not items_data:
            return Response({"detail": "请提供需要更新的盘点明细"}, status=status.HTTP_400_BAD_REQUEST)

        item_ids = [item.get('id') for item in items_data if item.get('id')]
        stocktake_items = {
            item.id: item
            for item in StocktakeItem.objects.filter(stocktake=stocktake, id__in=item_ids)
        }

        if len(stocktake_items) != len(item_ids):
            return Response({"detail": "存在无效的盘点明细记录"}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            for item_data in items_data:
                stocktake_item = stocktake_items[item_data['id']]
                if 'actual_qty' in item_data:
                    stocktake_item.actual_qty = item_data['actual_qty']
                if 'remark' in item_data:
                    stocktake_item.remark = item_data.get('remark')
                stocktake_item.save(update_fields=['actual_qty', 'remark'])

        stocktake = self.get_queryset().get(pk=stocktake.pk)
        serializer = self.get_serializer(stocktake)
        return Response(serializer.data)
