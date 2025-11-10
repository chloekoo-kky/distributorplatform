# distributorplatform/app/user/urls.py
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'user'

urlpatterns = [
    path('register/', views.register, name='register'),
    path('verify/', views.verify_phone, name='verify_phone'),
    path('login/', auth_views.LoginView.as_view(template_name='user/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='product:product_list'), name='logout'),

    # --- START ADDITIONS ---
    path('api/manage-users/', views.api_manage_users, name='api_manage_users'),
    path('api/manage-groups/', views.api_manage_user_groups, name='api_manage_user_groups'),
    path('api/update-user-groups/<int:user_id>/', views.api_update_user_groups, name='api_update_user_groups'),
    # --- END ADDITIONS ---
]
