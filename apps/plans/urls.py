from django.urls import path

from . import views

urlpatterns = [
    path("<slug:kind>/<int:pk>/", views.plan_form_view, name="plan_form"),
    path("<slug:kind>/<int:pk>/remove/", views.plan_delete_view, name="plan_delete"),
]
