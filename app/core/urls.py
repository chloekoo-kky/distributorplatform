# distributorplatform/app/core/urls.py

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Admin URL should be specific and is often placed first
    path('admin/', admin.site.urls),

    # Your application URLs
    path('accounts/', include('user.urls')),
    path('', include('product.urls')),  # Root URL pattern
]

# Add static and media file serving for development
if settings.DEBUG:
    # This serves static files (CSS, JS) for the admin and other apps
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    # This serves user-uploaded media files
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
