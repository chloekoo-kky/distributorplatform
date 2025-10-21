# distributorplatform/app/user/urls.py
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

# --- Add this line ---
handler403 = 'user.views.handler403'

urlpatterns = [
    path('register/', views.register, name='register'),
    path('verify/', views.verify_phone, name='verify_phone'),
    path('login/', auth_views.LoginView.as_view(template_name='user/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='product_list'), name='logout'),
]
