from django.urls import include, path

from . import money_views as m
from .views import accounts, categories, family_members

urlpatterns = [
    path("categories/", include(categories.urls())),
    path("accounts/", include(accounts.urls())),
    path("accounts/<int:pk>/book/", m.account_detail_view, name="account_detail"),
    path("transfer/", m.transfer_form_view, name="transfer_add"),
    path("transfer/<int:pk>/edit/", m.transfer_form_view, name="transfer_edit"),
    path("transfer/<int:pk>/delete/", m.transfer_delete_view, name="transfer_delete"),
    path("money/", m.transaction_list_view, name="transactions"),
    path("money/add/", m.transaction_form_view, name="transaction_add"),
    path("money/deleted/", m.transaction_deleted_view, name="transactions_deleted"),
    path("money/<int:pk>/edit/", m.transaction_form_view, name="transaction_edit"),
    path("money/<int:pk>/delete/", m.transaction_delete_view, name="transaction_delete"),
    path("money/<int:pk>/restore/", m.transaction_restore_view, name="transaction_restore"),
    path("family/", m.family_income_view, name="family_income"),
    path("family/add/", m.family_income_form_view, name="family_income_add"),
    path("family/<int:pk>/edit/", m.family_income_form_view, name="family_income_edit"),
    path("family/people/", include(family_members.urls())),
    path("statement/", m.statement_view, name="statement"),
    path("budget/", m.budget_view, name="budget"),
    path("budget/edit/", m.budget_edit_view, name="budget_edit"),
    path("budget/copy/", m.budget_copy_view, name="budget_copy"),
    path("recurring/", m.recurring_list_view, name="recurring"),
    path("recurring/add/", m.recurring_form_view, name="recurring_add"),
    path("recurring/<int:pk>/edit/", m.recurring_form_view, name="recurring_edit"),
    path("recurring/<int:pk>/skip/", m.recurring_skip_view, name="recurring_skip"),
    path("recurring/<int:pk>/delete/", m.recurring_delete_view, name="recurring_delete"),
]
