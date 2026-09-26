from django.urls import path

from . import views
from .models import LoanTxnKind

urlpatterns = [
    path("", views.loan_list_view, name="loans"),
    path("add/", views.loan_form_view, name="loan_add"),
    path("preview/", views.loan_preview_view, name="loan_preview"),
    path("<int:pk>/", views.loan_detail_view, name="loan_detail"),
    path("<int:pk>/edit/", views.loan_form_view, name="loan_edit"),
    path("<int:pk>/pay/", views.txn_create_view, {"kind": LoanTxnKind.PAYMENT}, name="loan_pay"),
    path("<int:pk>/borrow-more/", views.txn_create_view, {"kind": LoanTxnKind.TOP_UP}, name="loan_topup"),
    path("<int:pk>/pay-past-dues/", views.pay_past_dues_view, name="loan_pay_past"),
    path("<int:pk>/rate/", views.rate_change_view, name="loan_rate"),
    path("<int:pk>/close/", views.loan_close_view, name="loan_close"),
    path("<int:pk>/delete/", views.loan_delete_view, name="loan_delete"),
    path("<int:pk>/restore/", views.loan_restore_view, name="loan_restore"),
    path("<int:pk>/schedule.csv", views.loan_schedule_csv_view, name="loan_csv"),
    path("entries/<int:pk>/edit/", views.txn_edit_view, name="loan_txn_edit"),
    path("entries/<int:pk>/delete/", views.txn_delete_view, name="loan_txn_delete"),
    path("rates/<int:pk>/delete/", views.rate_change_delete_view, name="loan_rate_delete"),
    path("lenders/", views.lender_list_view, name="lenders"),
    path("lenders/add/", views.lender_form_view, name="lender_add"),
    path("lenders/quick-add/", views.lender_quick_add_view, name="lender_quick_add"),
    path("lenders/<int:pk>/edit/", views.lender_form_view, name="lender_edit"),
    path("lenders/<int:pk>/delete/", views.lender_delete_view, name="lender_delete"),
    path("lenders/<int:pk>/restore/", views.lender_restore_view, name="lender_restore"),
]
