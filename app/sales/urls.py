# distributorplatform/app/sales/urls.py
from django.urls import path
from . import views

app_name = 'sales'

urlpatterns = [
    path('invoice/from-quotation/<str:quotation_id>/', views.create_invoice_from_quotation, name='create_invoice_from_quotation'),
    # --- ADDED URL for editing invoices ---
    path('invoice/<str:invoice_id>/edit/', views.edit_invoice, name='edit_invoice'),
    # You might add an invoice detail URL later:
    # path('invoice/<str:invoice_id>/', views.invoice_detail, name='invoice_detail'),
]
