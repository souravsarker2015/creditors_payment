from django.urls import path

from . import views
from .views import equipment

urlpatterns = equipment.urls() + [
    path("<int:pk>/", views.equipment_detail_view, name="equipment_detail"),
    path("<int:pk>/condition/", views.condition_view, name="equipment_condition"),
    path("<int:equipment_pk>/service/", views.service_form_view, name="equipment_service"),
    path("services/<int:pk>/edit/", views.service_form_view, name="equipment_service_edit"),
    path("services/<int:pk>/delete/", views.service_delete_view, name="equipment_service_delete"),
]
