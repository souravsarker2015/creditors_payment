from django.urls import path

from .my_data import (my_data_cancel_view, my_data_copy_view, my_data_page_view, my_data_restore_view,
                      my_data_upload_view, my_data_view)
from .delete_check import delete_check_view
from .launcher import launcher_view
from .offline import offline_pages_view, offline_settings_view
from .quick_create import quick_create_view

urlpatterns = [
    path("my-data.zip", my_data_view, name="my_data"),
    path("my-data/", my_data_page_view, name="my_data_page"),
    path("my-data/check/", my_data_upload_view, name="my_data_upload"),
    path("my-data/restore/", my_data_restore_view, name="my_data_restore"),
    path("my-data/cancel/", my_data_cancel_view, name="my_data_cancel"),
    path("my-data/copies/<str:name>/", my_data_copy_view, name="my_data_copy"),
    path("delete-check/", delete_check_view, name="delete_check"),
    path("offline-pages/", offline_pages_view, name="offline_pages"),
    path("offline/", offline_settings_view, name="offline_settings"),
    path("shortcuts/", launcher_view, name="launcher"),
    path("quick-add/<slug:kind>/", quick_create_view, name="quick_create"),
]
