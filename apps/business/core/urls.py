from django.urls import path

from . import views
from .crud import quick_add_view

urlpatterns = [
    path("", views.home_view, name="home"),
    path("setup/", views.setup_view, name="setup"),
    path("switch-business/", views.switch_business_view, name="switch_business"),
    path("default-dashboard/", views.default_dashboard_view, name="default_dashboard"),
    path("settings/profile/", views.profile_view, name="profile"),
    path("settings/units/", views.unit_list_view, name="units"),
    path("settings/units/add/", views.unit_form_view, name="unit_add"),
    path("settings/units/<int:pk>/edit/", views.unit_form_view, name="unit_edit"),
    path("settings/units/<int:pk>/delete/", views.unit_delete_view, name="unit_delete"),
    path("settings/units/<int:pk>/restore/", views.unit_restore_view, name="unit_restore"),
    path("settings/team/", views.team_view, name="team"),
    path("settings/team/<int:pk>/role/", views.member_role_view, name="member_role"),
    path("settings/team/<int:pk>/remove/", views.member_remove_view, name="member_remove"),
    path("settings/activity/", views.activity_view, name="activity"),
    path("quick-add/<slug:kind>/", quick_add_view, name="quick_add"),
    path("settings/", views.setup_hub_view, name="setup_hub"),
    path("admin/access/", views.access_admin_view, name="access_admin"),
    path("admin/access/<int:user_id>/", views.access_update_view, name="access_update"),
]
