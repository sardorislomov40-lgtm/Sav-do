from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("stock/", views.stock_list, name="stock_list"),
    path("movements/", views.movement_list, name="movement_list"),
    # Kirim
    path("receipts/", views.receipt_list, name="receipt_list"),
    path("receipts/new/", views.receipt_create, name="receipt_create"),
    path("receipts/<int:pk>/", views.receipt_detail, name="receipt_detail"),
    path("receipts/<int:pk>/scan/", views.receipt_scan, name="receipt_scan"),
    path("receipts/<int:pk>/add/", views.receipt_add_product, name="receipt_add_product"),
    path("receipts/<int:pk>/lines/<int:line_id>/update/", views.receipt_line_update, name="receipt_line_update"),
    path("receipts/<int:pk>/lines/<int:line_id>/delete/", views.receipt_line_delete, name="receipt_line_delete"),
    path("receipts/<int:pk>/post/", views.receipt_post, name="receipt_post"),
    path("receipts/<int:pk>/remove/", views.receipt_remove, name="receipt_remove"),
    path("receipts/<int:pk>/labels/", views.receipt_labels, name="receipt_labels"),
    # Inventarizatsiya
    path("counts/", views.count_list, name="count_list"),
    path("counts/new/", views.count_create, name="count_create"),
    path("counts/<int:pk>/", views.count_detail, name="count_detail"),
    path("counts/<int:pk>/scan/", views.count_scan, name="count_scan"),
    path("counts/<int:pk>/add/", views.count_add_product, name="count_add_product"),
    path("counts/<int:pk>/lines/<int:line_id>/update/", views.count_line_update, name="count_line_update"),
    path("counts/<int:pk>/lines/<int:line_id>/delete/", views.count_line_delete, name="count_line_delete"),
    path("counts/<int:pk>/post/", views.count_post, name="count_post"),
    path("counts/<int:pk>/remove/", views.count_remove, name="count_remove"),
]
