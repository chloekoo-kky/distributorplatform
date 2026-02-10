# distributorplatform/app/product/urls.py
from django.urls import path
from . import views

app_name = 'product'

urlpatterns = [
    path('', views.home, name='home'),
    path('products/', views.product_list, name='product_list'),
    path('product/<str:sku>/', views.product_detail, name='product_detail'),

    # API
    path('api/product-details/<str:sku>/', views.api_get_product_details, name='api_get_product_details'),
    path('api/manage-pricing/<int:product_id>/', views.api_manage_pricing, name='api_manage_pricing'),
    path('api/manage-products/', views.api_manage_products, name='api_manage_products'),

    # --- NEW: Category Management API ---
    path('api/manage-categories/', views.api_manage_categories, name='api_manage_categories'),
    path('manage/category/create/', views.manage_category_create, name='manage_category_create'),
    path('manage/category/edit/<int:category_id>/', views.manage_category_edit, name='manage_category_edit'),
            # ------------------------------------

    path('upload-products/', views.upload_products, name='upload_products'),
    path('export-products/', views.export_products_csv, name='export_products_csv'),
    path('export-products-pdf/', views.export_products_pdf, name='export_products_pdf'),
    path('manage/edit/<int:product_id>/', views.manage_product_edit, name='manage_product_edit'),
]
