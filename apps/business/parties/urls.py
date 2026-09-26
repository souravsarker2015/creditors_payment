from django.urls import include, path

from .views import buyers, suppliers

urlpatterns = [
    path("suppliers/", include(suppliers.urls())),
    path("buyers/", include(buyers.urls())),
]
