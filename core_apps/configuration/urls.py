from django.urls import path

from .views import ConfigurationModuleCatalogView, ConfigurationValidationView


urlpatterns = [
    path("validate/", ConfigurationValidationView.as_view()),
    path("modules/", ConfigurationModuleCatalogView.as_view()),
]
