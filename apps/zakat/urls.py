from django.urls import path

from . import views

urlpatterns = [path("", views.zakat_view, name="zakat")]
