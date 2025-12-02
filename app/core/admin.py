# distributorplatform/app/core/admin.py
from django.contrib import admin
from django import forms  # <-- Import forms
from .models import SiteSetting, ProductFeature

# Define a custom form to use the HTML5 color input widget
class SiteSettingForm(forms.ModelForm):
    class Meta:
        model = SiteSetting
        fields = '__all__'
        widgets = {
            'nav_background_color': forms.TextInput(attrs={'type': 'color'}),
        }

@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    form = SiteSettingForm  # <-- Assign the custom form

    def has_add_permission(self, request):
        return not SiteSetting.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(ProductFeature)
class ProductFeatureAdmin(admin.ModelAdmin):
    list_display = ('title', 'subtitle', 'order')
    list_editable = ('order',)
