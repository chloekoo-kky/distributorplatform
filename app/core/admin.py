# distributorplatform/app/core/admin.py
from django.contrib import admin
from .models import SiteSetting

@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    # Prevent adding new rows if one already exists
    def has_add_permission(self, request):
        if SiteSetting.objects.exists():
            return False
        return True

    # Prevent deleting the settings
    def has_delete_permission(self, request, obj=None):
        return False
