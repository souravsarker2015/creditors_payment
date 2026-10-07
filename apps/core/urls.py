from django.urls import path

from .my_data import my_data_view
from .offline import offline_pages_view, offline_settings_view
from .quick_create import quick_create_view

urlpatterns = [
    path("my-data.zip", my_data_view, name="my_data"),
    path("offline-pages/", offline_pages_view, name="offline_pages"),
    path("offline/", offline_settings_view, name="offline_settings"),
    path("quick-add/<slug:kind>/", quick_create_view, name="quick_create"),
]
