from django.urls import path

from . import views

urlpatterns = [
    path("", views.trash_list_view, name="trash_list"),
    path("<int:pk>/restore/", views.restore_view, name="trash_restore"),
    path("<int:pk>/forget/", views.forget_view, name="trash_forget"),
    path("empty/", views.empty_view, name="trash_empty"),
]
