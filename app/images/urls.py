# distributorplatform/app/images/urls.py
from django.urls import path
from . import views

app_name = 'images'

urlpatterns = [
    # API-like views for the image gallery
    path('api/get-images/', views.ajax_get_images, name='ajax_get_images'),
    path('api/upload-image/', views.ajax_upload_image, name='ajax_upload_image'),
    path('api/delete-image/<int:image_id>/', views.ajax_delete_image, name='ajax_delete_image'),
    path('api/assign-to-products/', views.ajax_assign_to_products, name='ajax_assign_to_products'),
    path('api/assign-to-posts/', views.ajax_assign_to_posts, name='ajax_assign_to_posts'),
    path('api/bulk-assign/', views.ajax_bulk_assign, name='ajax_bulk_assign'),
    path('api/edit-image/<int:image_id>/', views.ajax_edit_image, name='ajax_edit_image'),
]
