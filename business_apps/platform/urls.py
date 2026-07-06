from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    FileViewSet, DictTypeViewSet, DictItemViewSet,
    DictItemsByCodeView, CodeRuleViewSet,
)

router = DefaultRouter()
router.register('files', FileViewSet, basename='file')
router.register('dict/types', DictTypeViewSet, basename='dict-type')
router.register('dict/items', DictItemViewSet, basename='dict-item')
router.register('code-rules', CodeRuleViewSet, basename='code-rule')

urlpatterns = [
    path('', include(router.urls)),
    path('dict/items/<str:dict_code>', DictItemsByCodeView.as_view(), name='dict-items-by-code'),
]
