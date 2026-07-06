from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CreateSaasGenerationView, ExportCodeGenerationView, GenerationJobViewSet, SystemInstanceViewSet

router = DefaultRouter()
router.register("jobs", GenerationJobViewSet, basename="generation-job")
router.register("instances", SystemInstanceViewSet, basename="generation-instance")

urlpatterns = [
    path("create-saas/", CreateSaasGenerationView.as_view()),
    path("export-code/", ExportCodeGenerationView.as_view()),
    path("", include(router.urls)),
]
