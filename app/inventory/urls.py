# distributorplatform/app/inventory/urls.py
from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('api/manage-inventory/', views.api_manage_inventory, name='api_manage_inventory'),
    path('api/manage-quotations/', views.api_manage_quotations, name='api_manage_quotations'),
    path('api/product-batches/<int:product_id>/', views.api_get_product_batches, name='api_get_product_batches'),
    path('api/quotation-items/<str:quotation_id>/', views.api_get_quotation_items, name='api_get_quotation_items'),
    
    path('upload-quotation/', views.upload_quotation, name='upload_quotation'),
    path('upload-batches/', views.upload_batches, name='upload_batches'),
    path('export-batches/', views.export_batches_csv, name='export_batches_csv'),

    # --- START ADDED ---
    path('receive-stock/', views.receive_stock, name='receive_stock'),
    # --- END ADDED ---

    path('create-quotation/', views.create_quotation, name='create_quotation'),
    path('quotation/<str:quotation_id>/', views.quotation_detail, name='quotation_detail'),
    path('quotation/<str:quotation_id>/assign-product/', views.assign_product_to_supplier, name='assign_product_to_supplier'),
    path('quotation/<str:quotation_id>/import-items/preview/', views.import_quotation_items_preview, name='import_quotation_items_preview'),
    path('quotation/<str:quotation_id>/import-items/confirm/', views.import_quotation_items_confirm, name='import_quotation_items_confirm'),
    path('api/products-for-mapping/', views.api_products_for_mapping, name='api_products_for_mapping'),
    path('quotation-item/<int:pk>/delete/', views.delete_quotation_item, name='delete_quotation_item'),
    path('export-quotations-xlsx/', views.export_quotations_xlsx, name='export_quotations_xlsx'),
]
