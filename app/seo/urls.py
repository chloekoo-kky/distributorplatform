# distributorplatform/app/seo/urls.py
from django.urls import path
from . import views

app_name = 'seo'

urlpatterns = [
    path('manage/create/', views.manage_seo_create, name='manage_seo_create'),
    path('manage/edit/<int:meta_id>/', views.manage_seo_edit, name='manage_seo_edit'),
]
