from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CustomerViewSet, ContactViewSet, FollowRecordViewSet, CustomerTagViewSet, CustomerAttachmentViewSet

router = DefaultRouter()
router.register('customers', CustomerViewSet)
router.register('contacts', ContactViewSet)
router.register('follow-records', FollowRecordViewSet)
router.register('tags', CustomerTagViewSet)
router.register('attachments', CustomerAttachmentViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
