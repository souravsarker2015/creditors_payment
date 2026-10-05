from django.urls import path

from . import views
from .views import staff

urlpatterns = staff.urls() + [
    path("<int:pk>/khata/", views.worker_detail_view, name="staff_worker"),
    path("<int:worker_pk>/earn/", views.earning_form_view, name="staff_earn"),
    path("<int:worker_pk>/pay/", views.payment_form_view, name="staff_pay"),
    path("earnings/<int:pk>/edit/", views.earning_form_view, name="staff_earning_edit"),
    path("payments/<int:pk>/edit/", views.payment_form_view, name="staff_payment_edit"),
    path("<slug:kind>/<int:pk>/remove/", views.entry_delete_view, name="staff_entry_delete"),
    path("work/", views.work_sheet_view, name="staff_work"),
    path("salaries/", views.salary_sheet_view, name="staff_salaries"),
]
