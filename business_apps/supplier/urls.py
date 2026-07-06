from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SupplierViewSet, SupplierContactViewSet, SupplierFollowRecordViewSet, 
    SupplierEvaluationViewSet, SupplierTagViewSet, SupplierAttachmentViewSet
)

router = DefaultRouter()
router.register('suppliers', SupplierViewSet)
router.register('contacts', SupplierContactViewSet)
router.register('follow-records', SupplierFollowRecordViewSet)
router.register('evaluations', SupplierEvaluationViewSet)
router.register('tags', SupplierTagViewSet)
router.register('attachments', SupplierAttachmentViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
