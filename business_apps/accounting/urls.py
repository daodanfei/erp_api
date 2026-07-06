from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AccountSubjectViewSet,
    AccountingPeriodViewSet,
    VoucherViewSet,
    BusinessPostingLogViewSet,
)


router = DefaultRouter()
router.register("subjects", AccountSubjectViewSet)
router.register("periods", AccountingPeriodViewSet)
router.register("vouchers", VoucherViewSet)
router.register("posting-logs", BusinessPostingLogViewSet)

urlpatterns = [
    path("", include(router.urls)),
]

