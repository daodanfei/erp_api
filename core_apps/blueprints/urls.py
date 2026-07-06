from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import BlueprintVersionViewSet, BlueprintViewSet

router = DefaultRouter()
router.register("items", BlueprintViewSet, basename="blueprint")
router.register("versions", BlueprintVersionViewSet, basename="blueprint-version")

urlpatterns = [
    path("", include(router.urls)),
]
