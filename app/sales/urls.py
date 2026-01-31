# distributorplatform/app/sales/urls.py
from django.urls import path
from . import views

app_name = 'sales'

urlpatterns = [
    path('api/manage-invoices/', views.api_manage_invoices, name='api_manage_invoices'),
    path('invoice/from-quotation/<str:quotation_id>/', views.create_invoice_from_quotation, name='create_invoice_from_quotation'),
    path('invoice/<str:invoice_id>/edit/', views.edit_invoice, name='edit_invoice'),
]
