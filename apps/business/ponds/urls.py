from django.urls import path

from . import views
from .views import ponds

urlpatterns = ponds.urls() + [
    path("<int:pk>/", views.pond_detail_view, name="pond_detail"),
    path("<int:pk>/start-cycle/", views.cycle_start_view, name="cycle_start"),
    path("cycles/<int:pk>/", views.cycle_detail_view, name="cycle_detail"),
    path("cycles/<int:pk>/edit/", views.cycle_edit_view, name="cycle_edit"),
    path("cycles/<int:pk>/finish/", views.cycle_finish_view, name="cycle_finish"),
    path("cycles/<int:pk>/delete/", views.cycle_delete_view, name="cycle_delete"),
    path("cycles/<int:pk>/add/<slug:kind>/", views.entry_add_view, name="entry_add"),
    path("entries/<slug:kind>/<int:pk>/edit/", views.entry_edit_view, name="entry_edit"),
    path("entries/<slug:kind>/<int:pk>/delete/", views.entry_delete_view, name="entry_delete"),
]
