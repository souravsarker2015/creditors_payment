from django.urls import path

from .quick_create import quick_create_view

urlpatterns = [
    path("quick-add/<slug:kind>/", quick_create_view, name="quick_create"),
]
