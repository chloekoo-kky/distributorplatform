# distributorplatform/app/inventory/urls.py
from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('api/manage-inventory/', views.api_manage_inventory, name='api_manage_inventory'),
    path('api/manage-quotations/', views.api_manage_quotations, name='api_manage_quotations'),
    path('api/manage-procurement/', views.api_manage_procurement, name='api_manage_procurement'),
    path('api/product-batches/<int:product_id>/', views.api_get_product_batches, name='api_get_product_batches'),
    path('api/invoice-item-batches/<int:invoice_item_id>/', views.api_get_invoice_item_batches, name='api_get_invoice_item_batches'),
    path('api/invoice-item-batches/<int:invoice_item_id>/save/', views.api_save_invoice_item_batches, name='api_save_invoice_item_batches'),
    path('api/batch/<int:batch_id>/update/', views.api_update_batch, name='api_update_batch'),
    path('api/quotation-items/<str:quotation_id>/', views.api_get_quotation_items, name='api_get_quotation_items'),
    
    path('upload-quotation/', views.upload_quotation, name='upload_quotation'),
    path('upload-invoice/', views.upload_invoice, name='upload_invoice'),
    path('upload-invoice/preview/', views.upload_invoice_preview, name='upload_invoice_preview'),
    path('upload-invoice/confirm/', views.upload_invoice_confirm, name='upload_invoice_confirm'),
    path('upload-batches/', views.upload_batches, name='upload_batches'),
    path('export-batches/', views.export_batches_csv, name='export_batches_csv'),

    # --- START ADDED ---
    path('receive-stock/', views.receive_stock, name='receive_stock'),
    path('bulk-receive-stock/', views.bulk_receive_stock, name='bulk_receive_stock'),
    # --- END ADDED ---

    path('create-quotation/', views.create_quotation, name='create_quotation'),
    path('quotation/<str:quotation_id>/', views.quotation_detail, name='quotation_detail'),
    path('quotation/<str:quotation_id>/delete/', views.delete_quotation, name='delete_quotation'),
    path('quotation/<str:quotation_id>/assign-product/', views.assign_product_to_supplier, name='assign_product_to_supplier'),
    path('quotation/<str:quotation_id>/import-items/preview/', views.import_quotation_items_preview, name='import_quotation_items_preview'),
    path('quotation/<str:quotation_id>/import-items/confirm/', views.import_quotation_items_confirm, name='import_quotation_items_confirm'),
    path('api/products-for-mapping/', views.api_products_for_mapping, name='api_products_for_mapping'),
    path('quotation-item/<int:pk>/delete/', views.delete_quotation_item, name='delete_quotation_item'),
    path('export-quotations-xlsx/', views.export_quotations_xlsx, name='export_quotations_xlsx'),
    path('export-supplier-price-matrix-xlsx/', views.export_supplier_price_matrix_xlsx, name='export_supplier_price_matrix_xlsx'),
    path('api/delete-supplier-price-matrix-rows/', views.api_delete_supplier_price_matrix_rows, name='api_delete_supplier_price_matrix_rows'),
    path('api/manage-supplier-prices/', views.api_manage_supplier_prices, name='api_manage_supplier_prices'),
    path('api/supplier-price-matrix/<int:entry_id>/', views.api_supplier_price_matrix_entry_detail, name='api_supplier_price_matrix_entry_detail'),
    path('api/supplier-price-matrix/quotation/<int:item_id>/', views.api_quotation_matrix_row_detail, name='api_quotation_matrix_row_detail'),
    path('upload-supplier-price-matrix/preview/', views.upload_supplier_price_matrix_preview, name='upload_supplier_price_matrix_preview'),
    path('upload-supplier-price-matrix/confirm/', views.upload_supplier_price_matrix_confirm, name='upload_supplier_price_matrix_confirm'),
    path('api/create-supplier/', views.api_create_supplier, name='api_create_supplier'),
    path('api/suppliers-matrix-settings/', views.api_list_suppliers_matrix_settings, name='api_list_suppliers_matrix_settings'),
    path('api/suppliers/<int:supplier_id>/delete/', views.api_delete_supplier, name='api_delete_supplier'),
]
