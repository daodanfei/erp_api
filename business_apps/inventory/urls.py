from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ProductViewSet, ProductCategoryViewSet, UnitViewSet,
    ProductImageViewSet, ProductAttachmentViewSet, ProductTagViewSet,
    WarehouseViewSet, InventoryViewSet, InventoryTransactionViewSet, StocktakeViewSet
)

router = DefaultRouter()
router.register('products', ProductViewSet)
router.register('categories', ProductCategoryViewSet)
router.register('units', UnitViewSet)
router.register('images', ProductImageViewSet)
router.register('attachments', ProductAttachmentViewSet)
router.register('tags', ProductTagViewSet)
router.register('warehouses', WarehouseViewSet)
router.register('inventories', InventoryViewSet)
router.register('transactions', InventoryTransactionViewSet)
router.register('stocktakes', StocktakeViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
