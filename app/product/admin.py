# distributorplatform/app/product/admin.py
from django.contrib import admin
from django.db.models import Count  # --- IMPORT COUNT ---
from .models import Product, Category, CategoryGroup, ProductContentSection, CategoryContentSection

# --- Import the library and our new resource ---
from import_export.admin import ImportExportMixin
from .resources import ProductResource, CategoryGroupResource, CategoryResource


# --- UPDATED ADMIN ---
class CategoryGroupAdmin(ImportExportMixin, admin.ModelAdmin):
    resource_class = CategoryGroupResource
    # --- UPDATED list_display, replaced 'id' with 'code' ---
    list_display = ('code', 'name', 'category_count')
    search_fields = ('code', 'name',) # Added code to search

    def get_queryset(self, request):
        """
        Annotate the queryset with the number of categories
        in each group for sorting and display.
        """
        qs = super().get_queryset(request)
        return qs.annotate(
            _category_count=Count('categories')
        )

    @admin.display(ordering='_category_count', description='Categories Count')
    def category_count(self, obj):
        """
        Returns the annotated count.
        """
        return obj._category_count
# --- END UPDATES ---

class CategoryContentSectionInline(admin.TabularInline):
    model = CategoryContentSection
    extra = 1

class CategoryAdmin(ImportExportMixin, admin.ModelAdmin):
    resource_class = CategoryResource
    list_display = ('code', 'name', 'group', 'product_count')
    list_filter = ('group',)
    search_fields = ('code', 'name', 'group__name')
    # --- Add Inline ---
    inlines = [CategoryContentSectionInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_product_count=Count('products'))

    @admin.display(ordering='_product_count', description='Product Count')
    def product_count(self, obj):
        return obj._product_count


class ProductContentSectionInline(admin.TabularInline):
    model = ProductContentSection
    extra = 1

# 2. Create a new admin view for the Product model
class ProductAdmin(ImportExportMixin, admin.ModelAdmin):
    resource_class = ProductResource
    # --- UPDATED list_display ---
    list_display = ('sku', 'name', 'featured_image', 'display_categories', 'display_suppliers', 'base_cost', 'members_only')
    # --- UPDATED list_filter ---
    list_filter = ('members_only', 'categories', 'suppliers', 'created_at')
    # --- UPDATED search_fields ---
    search_fields = ('sku', 'name', 'description', 'suppliers__name')
    readonly_fields = ('base_cost',)
    # --- ADDED filter_horizontal ---
    filter_horizontal = ('categories', 'suppliers', 'gallery_images',) # <-- Added gallery_images
    inlines = [ProductContentSectionInline]

    def display_categories(self, obj):
        return ", ".join([category.name for category in obj.categories.all()])
    display_categories.short_description = 'Categories'

    # --- NEW display_suppliers method ---
    def display_suppliers(self, obj):
        """Creates a string of supplier names for the list display."""
        return ", ".join([supplier.code for supplier in obj.suppliers.all()])
    display_suppliers.short_description = 'Suppliers'

# Register all models
admin.site.register(Product, ProductAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(CategoryGroup, CategoryGroupAdmin)
