from django.urls import include, path

from .views import accounts, categories

urlpatterns = [
    path("categories/", include(categories.urls())),
    path("accounts/", include(accounts.urls())),
]
