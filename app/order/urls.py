from django.urls import path
from . import views

app_name = 'order'

urlpatterns = [
    path('place-order/', views.place_order_view, name='place_order'),
    path('api/submit-order/', views.api_submit_order, name='api_submit_order'),

    path('manual-order/', views.create_manual_order_view, name='create_manual_order'),
    path('api/manual-order/products/', views.api_manual_order_products, name='api_manual_order_products'),
    path('api/manual-order/submit/', views.api_submit_manual_order, name='api_submit_manual_order'),
    path('api/manual-order/<str:order_id>/detail/', views.api_manual_order_detail, name='api_manual_order_detail'),
    path('api/manual-order/<str:order_id>/update/', views.api_update_manual_order, name='api_update_manual_order'),

    path('api/customers/search/', views.api_customer_search, name='api_customer_search'),

    path('order-success/<str:order_id>/', views.order_success_view, name='order_success'),

    path('manage/', views.manage_orders_dashboard, name='manage_orders'),
    path('customers/', views.manage_customers_dashboard, name='manage_customers'),
    path('api/customers/', views.api_customers_list, name='api_customers_list'),
    path('api/customers/create/', views.api_customer_create, name='api_customer_create'),
    path('api/customers/<int:customer_id>/', views.api_customer_detail, name='api_customer_detail'),
    path('api/customers/<int:customer_id>/orders/', views.api_customer_orders, name='api_customer_orders'),
    path('api/customers/<int:customer_id>/update/', views.api_customer_update, name='api_customer_update'),
    path('api/customers/<int:customer_id>/delete/', views.api_customer_delete, name='api_customer_delete'),
    path('export/customers-from-orders/', views.export_customers_from_orders, name='export_customers_from_orders'),
    path('api/manage-orders/', views.api_manage_orders, name='api_manage_orders'),
    path('api/export-selected-orders/', views.export_selected_orders, name='export_selected_orders'),
    path('api/bulk-update-status/', views.api_bulk_update_order_status, name='api_bulk_update_status'),
    path('export/orders-range/', views.export_orders_range, name='export_orders_range'),

    path('api/order/<str:order_id>/items/', views.api_get_order_items, name='api_get_order_items'),
    path('api/order/<str:order_id>/edit-details/', views.api_manage_order_edit_details, name='api_manage_order_edit_details'),
    path('api/order/<str:order_id>/update-status/', views.api_update_order_status, name='api_update_order_status'),

    path('api/invoice-issuers/', views.api_invoice_issuers_list, name='api_invoice_issuers_list'),
    path('api/invoice-issuers/create/', views.api_invoice_issuer_create, name='api_invoice_issuer_create'),
    path('api/invoice-issuers/<int:issuer_id>/', views.api_invoice_issuer_detail, name='api_invoice_issuer_detail'),
    path('api/invoice-issuers/<int:issuer_id>/update/', views.api_invoice_issuer_update, name='api_invoice_issuer_update'),
    path('api/invoice-issuers/<int:issuer_id>/delete/', views.api_invoice_issuer_delete, name='api_invoice_issuer_delete'),
    path('sales-invoice/<str:order_id>/', views.sales_invoice_print, name='sales_invoice_print'),

    path('api/prepare-checkout/', views.api_prepare_checkout, name='api_prepare_checkout'),
    path('checkout/', views.checkout_confirmation_view, name='checkout_confirmation'),
    path('api/confirm-checkout/', views.api_confirm_checkout, name='api_confirm_checkout'),

    # --- ADDED: Payment URLs ---
    path('payment/<str:order_id>/', views.payment_view, name='payment'),
    path('payment/callback/', views.payment_callback_view, name='payment_callback'),
    path('payment/webhook/', views.payment_webhook_view, name='payment_webhook'),

    path('export/', views.export_order_statement, name='export_order_statement'),
]
