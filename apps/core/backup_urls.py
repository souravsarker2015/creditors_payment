from django.urls import path

from . import backup_views as v

urlpatterns = [
    path("", v.backup_home_view, name="backup_home"),
    path("download/", v.backup_download_view, name="backup_download"),
    path("save/", v.backup_save_view, name="backup_save"),
    path("upload/", v.backup_upload_view, name="backup_upload"),
    path("check/", v.backup_preview_view, name="backup_preview"),
    path("restore/", v.backup_restore_view, name="backup_restore"),
    path("cancel/", v.backup_cancel_view, name="backup_cancel"),
    path("server/<str:name>/", v.backup_file_view, name="backup_file"),
    path("server/<str:name>/use/", v.backup_use_server_copy_view, name="backup_use"),
    path("server/<str:name>/delete/", v.backup_delete_view, name="backup_delete"),
]
