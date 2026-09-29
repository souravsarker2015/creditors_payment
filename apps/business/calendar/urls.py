from django.urls import path

from . import views

urlpatterns = [
    path("", views.calendar_view, name="calendar"),
    path("add/", views.event_form_view, name="calendar_add"),
    path("<int:pk>/edit/", views.event_form_view, name="calendar_edit"),
    path("<int:pk>/done/", views.event_done_view, name="calendar_done"),
    path("<int:pk>/delete/", views.event_delete_view, name="calendar_delete"),
    path("farm-calendar.ics", views.calendar_ics_view, name="calendar_ics"),
]
