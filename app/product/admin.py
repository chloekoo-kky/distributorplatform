# distributorplatform/app/product/admin.py
from django.contrib import admin
from django.db.models import Count
from .models import Product, Category, CategoryGroup, ProductContentSection
from import_export.admin import ImportExportMixin
from .resources import ProductResource, CategoryGroupResource, CategoryResource

class CategoryGroupAdmin(ImportExportMixin, admin.ModelAdmin):
    resource_class = CategoryGroupResource
    list_display = ('code', 'name', 'category_count')
    search_fields = ('code', 'name',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_category_count=Count('categories'))

    @admin.display(ordering='_category_count', description='Categories Count')
    def category_count(self, obj):
        return obj._category_count

class CategoryAdmin(ImportExportMixin, admin.ModelAdmin):
    resource_class = CategoryResource
    list_display = ('code', 'name', 'group', 'product_count')
    list_filter = ('group',)
    search_fields = ('code', 'name', 'group__name')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_product_count=Count('products'))

    @admin.display(ordering='_product_count', description='Product Count')
    def product_count(self, obj):
        return obj._product_count

# --- NEW: Inline for Sections ---
class ProductContentSectionInline(admin.TabularInline):
    model = ProductContentSection
    extra = 1

class ProductAdmin(ImportExportMixin, admin.ModelAdmin):
    resource_class = ProductResource
    list_display = ('sku', 'name', 'featured_image', 'display_categories', 'display_suppliers', 'base_cost', 'members_only')
    list_filter = ('members_only', 'categories', 'suppliers', 'created_at')
    search_fields = ('sku', 'name', 'description', 'suppliers__name')
    readonly_fields = ('base_cost',)
    filter_horizontal = ('categories', 'suppliers', 'gallery_images',)
    # Add inline
    inlines = [ProductContentSectionInline]

    def display_categories(self, obj):
        return ", ".join([category.name for category in obj.categories.all()])
    display_categories.short_description = 'Categories'

    def display_suppliers(self, obj):
        return ", ".join([supplier.code for supplier in obj.suppliers.all()])
    display_suppliers.short_description = 'Suppliers'

admin.site.register(Product, ProductAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(CategoryGroup, CategoryGroupAdmin)
