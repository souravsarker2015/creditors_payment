from django.urls import path

from . import views
from .views import papers

urlpatterns = papers.urls() + [
    path("<int:pk>/file/", views.paper_file_view, name="paper_file"),
]
