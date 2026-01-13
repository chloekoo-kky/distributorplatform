# distributorplatform/app/core/admin.py
from django.contrib import admin
from django import forms
from .models import SiteSetting, ThemeSetting, ProductFeature, Banner, PaymentSetting, PaymentOption

# --- 1. Form for Color Settings ---
class ThemeSettingForm(forms.ModelForm):
    class Meta:
        model = ThemeSetting
        fields = [
            'site_name_color',
            'site_name_subtitle_color',
            'category_header_background_color',
            'category_header_border_color',
            'category_header_title_color',
            'category_header_subtitle_color',
            'section_header_background_color',
            'section_header_border_color',
            'section_header_title_color',
        ]
        widgets = {
            'site_name_color': forms.TextInput(attrs={'type': 'color'}),
            'site_name_subtitle_color': forms.TextInput(attrs={'type': 'color'}),
            'category_header_background_color': forms.TextInput(attrs={'type': 'color'}),
            'category_header_border_color': forms.TextInput(attrs={'type': 'color'}),
            'category_header_title_color': forms.TextInput(attrs={'type': 'color'}),
            'category_header_subtitle_color': forms.TextInput(attrs={'type': 'color'}),
            'section_header_background_color': forms.TextInput(attrs={'type': 'color'}),
            'section_header_border_color': forms.TextInput(attrs={'type': 'color'}),
            'section_header_title_color': forms.TextInput(attrs={'type': 'color'}),
        }

@admin.register(ThemeSetting)
class ThemeSettingAdmin(admin.ModelAdmin):
    form = ThemeSettingForm

    # Restrict permissions to act like a Singleton (same as SiteSetting)
    def has_add_permission(self, request):
        return not SiteSetting.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

# --- 2. Form for General Site Settings ---
class SiteSettingForm(forms.ModelForm):
    class Meta:
        model = SiteSetting
        fields = '__all__'
        # We don't need color widgets here since we are hiding the fields

class PaymentSettingForm(forms.ModelForm):
    class Meta:
        model = PaymentSetting
        fields = [
            'payment_enabled',
            'payment_provider',
            'payment_category_code', # Merchant ID
            'payment_api_key',       # Secret Key
            'payment_gateway_url',
        ]
        widgets = {
            # Render the API key as a password field for basic visual security
            'payment_api_key': forms.PasswordInput(render_value=True),
            'payment_gateway_url': forms.TextInput(attrs={'style': 'width: 400px;'}),
        }
        help_texts = {
            'payment_gateway_url': "Default for SenangPay: <strong>https://app.senangpay.my/payment/</strong>",
            'payment_category_code': "Your <strong>Merchant ID</strong> (e.g., 1234567890).",
            'payment_api_key': "Your <strong>Secret Key</strong> from the SenangPay Dashboard.",
        }

@admin.register(PaymentSetting)
class PaymentSettingAdmin(admin.ModelAdmin):
    form = PaymentSettingForm

    # Show Provider, Enabled Status, and Merchant ID in the list column
    list_display = ('get_provider_label', 'payment_enabled', 'payment_category_code', 'get_masked_key')

    def get_provider_label(self, obj):
        """Displays the human-readable provider name or 'Not Set'."""
        if not obj.payment_provider:
            return "Not Set"
        return obj.get_payment_provider_display()
    get_provider_label.short_description = "Payment Provider"

    def get_masked_key(self, obj):
        if obj.payment_api_key:
            return "********"
        return "-"
    get_masked_key.short_description = "Secret Key"

    # Restrict permissions to act like a Singleton
    def has_add_permission(self, request):
        return not SiteSetting.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    form = SiteSettingForm

    # EXCLUDE the color fields from this view so they only appear in "Theme Settings"
    exclude = (
        'site_name_color',
        'site_name_subtitle_color',
        'category_header_background_color',
        'category_header_border_color',
        'category_header_title_color',
        'category_header_subtitle_color',
        'section_header_background_color',
        'section_header_border_color',
        'section_header_title_color',
        'payment_enabled', 'payment_provider',
        'payment_gateway_url', 'payment_api_key', 'payment_category_code'
    )

    def has_add_permission(self, request):
        return not SiteSetting.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProductFeature)
class ProductFeatureAdmin(admin.ModelAdmin):
    list_display = ('title', 'subtitle', 'order')
    list_editable = ('order',)

@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ('title', 'location', 'is_active', 'order')
    list_filter = ('location', 'is_active')
    search_fields = ('title', 'subtitle')

@admin.register(PaymentOption)
class PaymentOptionAdmin(admin.ModelAdmin):
    list_display = ('name', 'option_type', 'is_active')
    list_filter = ('option_type', 'is_active')
    search_fields = ('name',)
