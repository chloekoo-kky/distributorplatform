# distributorplatform/app/user/admin.py
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from .models import (
    CustomUser, UserGroup, SubscriptionPlan
)


class CustomUserAdmin(UserAdmin):
    model = CustomUser
    # Updated list_display to include names and assigned agent
    list_display = ['username', 'email', 'first_name', 'last_name', 'phone_number', 'assigned_agent', 'date_joined', 'display_user_groups']

    # Enable search for autocomplete
    search_fields = ('username', 'email', 'first_name', 'last_name', 'phone_number')

    # Add custom fields to the admin edit page
    # Added 'assigned_agent' to the tuple
    fieldsets = UserAdmin.fieldsets + (
        ('Additional Information', {'fields': ('phone_number', 'shipping_address', 'user_groups', 'assigned_agent')}),
    )

    filter_horizontal = ('user_groups',)

    # Enables a search box for selecting the agent instead of a long dropdown
    autocomplete_fields = ['assigned_agent']

    def display_user_groups(self, obj):
        """Creates a string of all user groups for the list display."""
        return ", ".join([group.name for group in obj.user_groups.all()])
    display_user_groups.short_description = 'User Groups'

class UserGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'display_product_categories', 'is_default')
    filter_horizontal = ('product_categories',)

    def display_product_categories(self, obj):
        """Creates a string of all product categories for the list display."""
        return ", ".join([category.name for category in obj.product_categories.all()])
    display_product_categories.short_description = 'Product Categories'

class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'target_group', 'is_active', 'is_popular', 'order')
    list_editable = ('is_active', 'is_popular', 'order')
    search_fields = ('name', 'target_group__name')

admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(UserGroup, UserGroupAdmin)
admin.site.register(SubscriptionPlan, SubscriptionPlanAdmin)
