# distributorplatform/app/core/urls.py

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from . import views as core_views
from . import views

handler403 = 'user.views.handler403'

core_patterns = [
    path('manage/', core_views.manage_dashboard, name='manage_dashboard'),
    path('manage/api/save-banner/', views.api_save_banner, name='api_save_banner'),
    path('manage/api/save-banner/<int:banner_id>/', views.api_save_banner, name='api_update_banner'),
    path('manage/api/delete-banner/<int:banner_id>/', views.api_delete_banner, name='api_delete_banner'),
]

urlpatterns = [
    # Admin URL should be specific and is often placed first
    path('admin/', admin.site.urls),

    path('', include('product.urls', namespace='product')),
    path('order/', include('order.urls', namespace='order')),
    path('user/', include('user.urls', namespace='user')),
    path('inventory/', include('inventory.urls', namespace='inventory')),
    path('sales/', include('sales.urls', namespace='sales')),
    path('blog/', include('blog.urls', namespace='blog')),
    path('seo/', include('seo.urls', namespace='seo')),
    path('images/', include('images.urls', namespace='images')),
    path('tinymce/', include('tinymce.urls')),
    path('commission/', include('commission.urls', namespace='commission')),
]

urlpatterns += [
    path('', include((core_patterns, 'core'), namespace='core')),
]

# Add static and media file serving for development
if settings.DEBUG:
    # This serves static files (CSS, JS) for the admin and other apps
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    # This serves user-uploaded media files
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
