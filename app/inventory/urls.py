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
    path('quotation-item/<int:pk>/delete/', views.delete_quotation_item, name='delete_quotation_item'),
    path('export-quotations/', views.export_quotations_csv, name='export_quotations_csv'),
]
