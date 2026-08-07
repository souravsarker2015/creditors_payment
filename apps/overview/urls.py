from django.urls import path
from . import views

urlpatterns = [
    path("", views.networth_view, name="networth"),
]
