from django.urls import path

from . import views

urlpatterns = [
    path("", views.goal_list_view, name="goal_list"),
    path("new/", views.goal_create_view, name="goal_create"),
    path("<int:pk>/", views.goal_detail_view, name="goal_detail"),
    path("<int:pk>/edit/", views.goal_edit_view, name="goal_edit"),
    path("<int:pk>/add/", views.entry_create_view, name="goal_entry_create"),
    path("<int:pk>/toggle-active/", views.goal_toggle_active_view, name="goal_toggle_active"),
    path("<int:pk>/delete/", views.goal_delete_view, name="goal_delete"),
    path("entries/<int:pk>/edit/", views.entry_edit_view, name="goal_entry_edit"),
    path("entries/<int:pk>/delete/", views.entry_delete_view, name="goal_entry_delete"),
]
