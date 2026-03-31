from django.urls import path
from . import views

urlpatterns = [
    path('', views.contributor_dashboard, name='contributor_dashboard'),
    path('list/', views.contributor_list, name='contributor_list'),
    path('add/', views.contributor_create, name='contributor_create'),
    path('<int:pk>/edit/', views.contributor_update, name='contributor_update'),
    path('<int:pk>/delete/', views.contributor_delete, name='contributor_delete'),
    path('<int:pk>/', views.contributor_detail, name='contributor_detail'),
    path('contribution/<int:pk>/edit/', views.contribution_update, name='contribution_edit'),
    path('contribution/<int:pk>/delete/', views.contribution_delete, name='contribution_delete'),
]
