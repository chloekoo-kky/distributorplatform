# distributorplatform/app/commission/urls.py
from django.urls import path
from . import views

app_name = 'commission'

urlpatterns = [
    path('api/list/', views.api_get_commissions, name='api_get_commissions'),
    path('api/pay/', views.api_pay_commissions, name='api_pay_commissions'),
    path('export/', views.export_commission_statement, name='export_commission_statement'),
]
