from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("reports/", views.report_index_view, name="reports"),
    path("worth/", views.worth_view, name="worth"),
    path("reports/<slug:kind>/", views.report_view, name="report"),
]
