# distributorplatform/app/order/urls.py
from django.urls import path
from . import views

app_name = 'order'

urlpatterns = [
    # The main page for creating a new order
    path('', views.place_order_view, name='place_order'),

    # The API endpoint that receives the cart submission
    path('api/submit/', views.api_submit_order, name='api_submit_order'),

    # The "Thank You" page after a successful order
    path('success/<int:order_id>/', views.order_success_view, name='order_success'),
]
