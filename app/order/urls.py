from django.urls import path
from . import views

app_name = 'order'

urlpatterns = [
    path('place-order/', views.place_order_view, name='place_order'),
    path('api/submit-order/', views.api_submit_order, name='api_submit_order'),

    # --- CHANGED: <int:order_id> -> <uuid:order_id> ---
    path('order-success/<uuid:order_id>/', views.order_success_view, name='order_success'),

    path('manage/', views.manage_orders_dashboard, name='manage_orders'),
    path('api/manage-orders/', views.api_manage_orders, name='api_manage_orders'),

    # --- CHANGED: <int:order_id> -> <uuid:order_id> ---
    path('api/order/<uuid:order_id>/items/', views.api_get_order_items, name='api_get_order_items'),
    path('api/order/<uuid:order_id>/update-status/', views.api_update_order_status, name='api_update_order_status'),

    path('api/prepare-checkout/', views.api_prepare_checkout, name='api_prepare_checkout'),
    path('checkout/', views.checkout_confirmation_view, name='checkout_confirmation'),
    path('api/confirm-checkout/', views.api_confirm_checkout, name='api_confirm_checkout'),
]
