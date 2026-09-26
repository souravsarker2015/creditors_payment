from django.urls import include, path

from . import views

urlpatterns = [
    path("", views.stock_view, name="feed_stock"),
    path("products/", include(views.feed_products.urls())),
    path("purchases/", include(views.feed_purchases.urls())),
    path("usage/", views.usage_list_view, name="feed_usage"),
    path("usage/add/", views.bulk_usage_view, name="feed_usage_bulk"),
]
