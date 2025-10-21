from django.contrib import admin
from .models import Product, Category, CategoryGroup

# Keep your existing admin classes
class CategoryGroupAdmin(admin.ModelAdmin):
    list_display = ('name',)

class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'group')
    list_filter = ('group',)

# 2. Create a new admin view for the Product model
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'base_cost', 'created_at')
    # Display the calculated base cost, but make it read-only
    readonly_fields = ('base_cost',)

admin.site.register(Product, ProductAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(CategoryGroup, CategoryGroupAdmin)
