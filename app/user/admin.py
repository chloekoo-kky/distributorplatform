# distributorplatform/app/user/admin.py
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from .models import (
    CustomUser, UserGroup,
)


class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ['username', 'email', 'phone_number', 'date_joined', 'display_user_groups']
    # Add user_groups to the admin view
    fieldsets = UserAdmin.fieldsets + (
        ('User Groups', {'fields': ('user_groups',)}),
    )
    filter_horizontal = ('user_groups',)

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


admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(UserGroup, UserGroupAdmin)
