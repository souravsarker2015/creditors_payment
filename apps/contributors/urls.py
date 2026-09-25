from django.urls import path
from . import views

urlpatterns = [
    path('', views.contributor_dashboard, name='contributor_dashboard'),
    path('list/', views.contributor_list, name='contributor_list'),
    path('add/', views.contributor_create, name='contributor_create'),
    path('import/', views.contributor_import_view, name='contributor_import'),
    path('import/template/', views.contributor_import_template_view, name='contributor_import_template'),
    path("<int:pk>/toggle-active/", views.contributor_toggle_active_view, name="contributor_toggle_active"),
    path('<int:pk>/edit/', views.contributor_update, name='contributor_update'),
    path('<int:pk>/delete/', views.contributor_delete, name='contributor_delete'),
    path('<int:pk>/', views.contributor_detail, name='contributor_detail'),
    path('<int:pk>/statement/', views.contributor_statement_view, name='contributor_statement'),
    path('contribution/<int:pk>/edit/', views.contribution_update, name='contribution_edit'),
    path('contribution/<int:pk>/delete/', views.contribution_delete, name='contribution_delete'),
]
