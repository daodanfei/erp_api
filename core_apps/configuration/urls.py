from django.urls import path

from .views import ConfigurationModuleCatalogView, ConfigurationNavigationCatalogView, ConfigurationPermissionDependencyView, ConfigurationValidationView


urlpatterns = [
    path("validate/", ConfigurationValidationView.as_view()),
    path("modules/", ConfigurationModuleCatalogView.as_view()),
    path("navigation/", ConfigurationNavigationCatalogView.as_view()),
    path("permission-dependencies/", ConfigurationPermissionDependencyView.as_view()),
]
