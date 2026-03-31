from django.contrib import admin
from django.db.models import Count, Min

from import_export.admin import ImportExportMixin

from .models import Product, Category, CategoryGroup, ProductContentSection, CategoryContentSection, ProductPriceTier
from .resources import ProductResource, CategoryGroupResource, CategoryResource

class CategoryGroupAdmin(ImportExportMixin, admin.ModelAdmin):
    resource_class = CategoryGroupResource
    list_display = ('code', 'name', 'category_count')
    search_fields = ('code', 'name',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            _category_count=Count('categories')
        )

    @admin.display(ordering='_category_count', description='Categories Count')
    def category_count(self, obj):
        return obj._category_count

class CategoryContentSectionInline(admin.TabularInline):
    model = CategoryContentSection
    extra = 1

class CategoryAdmin(ImportExportMixin, admin.ModelAdmin):
    resource_class = CategoryResource
    list_display = ('name', 'display_order', 'code', 'group', 'product_count')
    list_display_links = ('name',)
    list_editable = ('display_order',)
    list_filter = ('group',)
    search_fields = ('code', 'name', 'group__name')
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


class ProductPriceTierInline(admin.TabularInline):
    model = ProductPriceTier
    extra = 1
    ordering = ['-min_quantity']


class ProductAdmin(ImportExportMixin, admin.ModelAdmin):
    resource_class = ProductResource
    # Excel on Windows treats CSV as ANSI unless UTF-8 BOM is present; needed for symbols like ®.
    to_encoding = 'utf-8-sig'
    list_display = ('sku', 'name', 'display_order', 'featured_image', 'display_categories', 'display_suppliers', 'formatted_base_cost', 'members_only')
    # Add this line to make both SKU and Name clickable
    list_display_links = ('sku', 'name')
    list_filter = ('members_only', 'categories', 'suppliers', 'created_at')
    search_fields = ('sku', 'name', 'description', 'suppliers__name')
    readonly_fields = ('formatted_base_cost',)
    filter_horizontal = ('categories', 'suppliers', 'gallery_images',)
    inlines = [ProductContentSectionInline, ProductPriceTierInline]

    list_editable = ('display_order',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related('categories').annotate(_categories_sort=Min('categories__name'))

    @admin.display(ordering='_categories_sort', description='Categories')
    def display_categories(self, obj):
        return ", ".join([category.name for category in obj.categories.all()])

    @admin.display(description='Base cost')
    def formatted_base_cost(self, obj):
        cost = obj.base_cost
        if cost is None:
            return '—'
        return f'{cost:.2f}'

    def display_suppliers(self, obj):
        """
        Creates a string of supplier names for the list display.
        Fix: Falls back to supplier.name if supplier.code is None.
        """
        return ", ".join([supplier.code or supplier.name for supplier in obj.suppliers.all()])
    display_suppliers.short_description = 'Suppliers'
# Register all models
admin.site.register(Product, ProductAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(CategoryGroup, CategoryGroupAdmin)
