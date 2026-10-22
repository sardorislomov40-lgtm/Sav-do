from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("", views.product_list, name="product_list"),
    path("new/", views.product_form_view, name="product_create"),
    path("<int:pk>/", views.product_detail, name="product_detail"),
    path("<int:pk>/edit/", views.product_form_view, name="product_edit"),
    path("<int:pk>/barcode/", views.product_generate_barcode, name="product_generate_barcode"),
    path("labels/", views.labels_pdf, name="labels_pdf"),
    path("search/", views.product_search, name="product_search"),
    path("categories/", views.category_list, name="category_list"),
    path("categories/<int:pk>/delete/", views.category_delete, name="category_delete"),
]
