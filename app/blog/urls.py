# distributorplatform/app/blog/urls.py
from django.urls import path
from . import views

app_name = 'blog'

urlpatterns = [
    # Public URLs
    path('', views.post_list, name='post_list'),
    path('<slug:slug>/', views.post_detail, name='post_detail'),

    # Management URLs
    path('manage/create/', views.manage_post_create, name='manage_post_create'),
    path('manage/edit/<int:post_id>/', views.manage_post_edit, name='manage_post_edit'),
    path('manage/delete/<int:post_id>/', views.manage_post_delete, name='manage_post_delete'),

    # --- ADDED API URL ---
    path('api/manage-posts/', views.api_manage_posts, name='api_manage_posts'),
]
