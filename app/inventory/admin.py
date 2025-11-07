# distributorplatform/app/inventory/admin.py
import csv
import datetime
from django.http import HttpResponse
from django.contrib import admin
from django.db.models import Count, Sum, F

from import_export.admin import ImportExportMixin
from .resources import SupplierResource

from .models import Supplier, Quotation, InventoryBatch, QuotationItem


class SupplierAdmin(ImportExportMixin, admin.ModelAdmin):
    resource_class = SupplierResource
    list_display = ('code', 'name', 'contact_person', 'email', 'phone')
    search_fields = ('code', 'name', 'contact_person', 'email')

class QuotationItemInline(admin.TabularInline):
    model = QuotationItem
    extra = 1
    fields = ('product', 'quantity', 'quoted_price', 'total_item_price_display')
    readonly_fields = ('total_item_price_display',)

    def total_item_price_display(self, obj):
        return obj.total_item_price
    total_item_price_display.short_description = 'Total Price'


def export_quotations_as_csv(modeladmin, request, queryset):
    """
    Admin action to export selected Quotation objects (including items) as a CSV file.
    Each row represents one QuotationItem.
    """
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename=quotations-{datetime.date.today()}.csv'
    writer = csv.writer(response)

    # Write header row
    writer.writerow([
        'Quotation ID',
        'Supplier',
        'Date Quoted',
        'Product',
        'Quantity',
        'Quoted Price (Unit)',
        'Total Item Price',
        'Quotation Notes'
    ])

    quotations = queryset.select_related('supplier').prefetch_related('items__product')

    for quotation in quotations:
        for item in quotation.items.all():
            writer.writerow([
                quotation.quotation_id,
                quotation.supplier.name,
                quotation.date_quoted,
                item.product.name,
                item.quantity,
                item.quoted_price,
                item.total_item_price,
                quotation.notes,
            ])

    return response

export_quotations_as_csv.short_description = "Export Selected Quotations (with Items) as CSV"


class QuotationAdmin(admin.ModelAdmin):
    list_display = ('quotation_id', 'supplier', 'date_quoted', 'get_item_count', 'get_total_value', 'transportation_cost')
    list_filter = ('supplier', 'date_quoted')
    search_fields = ('quotation_id', 'supplier__name')
    readonly_fields = ('item_count_display', 'total_value_display', 'total_landed_cost') # Add new property
    inlines = [QuotationItemInline]

    fieldsets = (
        (None, {
            'fields': ('quotation_id', 'supplier', 'date_quoted', 'transportation_cost', 'notes')
        }),
        ('Summary (Calculated)', {
            'fields': ('item_count_display', 'total_value_display', 'total_landed_cost'),
        }),
    )
    # --- END CHANGES ---

    actions = [export_quotations_as_csv]

    def get_item_count(self, obj):
        return obj.item_count
    get_item_count.short_description = 'Item Count'

    def get_total_value(self, obj):
        value = obj.total_value
        return f"${value:,.2f}" if value is not None else "$0.00"
    get_total_value.short_description = 'Total Value (Items)' # Renamed for clarity

    def item_count_display(self, obj):
         return obj.item_count
    item_count_display.short_description = 'Number of Items'

    def total_value_display(self, obj):
        value = obj.total_value
        return f"${value:,.2f}" if value is not None else "$0.Following.00"
    total_value_display.short_description = 'Total Quotation Value (Items)' # Renamed

    # --- NEW DISPLAY METHOD ---
    def total_landed_cost(self, obj):
        value = obj.total_landed_cost
        return f"${value:,.2f}" if value is not None else "$0.00"
    total_landed_cost.short_description = 'Total Landed Cost (Items + Transport)'
    # --- END NEW ---


@admin.register(QuotationItem)
class QuotationItemAdmin(admin.ModelAdmin):
    list_display = ('product', 'quotation', 'quantity', 'quoted_price')
    list_filter = ('quotation__supplier',)
    search_fields = ('product__name', 'quotation__quotation_id')


def export_batches_as_csv(modeladmin, request, queryset):
    """
    Admin action to export selected InventoryBatch objects as a CSV file.
    """
    meta = modeladmin.model._meta

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename={meta.verbose_name_plural}-{datetime.date.today()}.csv'
    writer = csv.writer(response)

    # Write header row (Removed cost fields, added quotation)
    writer.writerow([
        'Batch Number', 'Product Name', 'Supplier Name', 'Quantity Received',
        'Received Date', 'Original Quotation ID'
    ])

    # Write data rows
    for obj in queryset:
        supplier_name = obj.supplier.name if obj.supplier else ''
        quotation_id = obj.quotation.quotation_id if obj.quotation else ''
        writer.writerow([
            obj.batch_number,
            obj.product.name,
            supplier_name,
            obj.quantity,
            obj.received_date,
            quotation_id, # Added quotation
        ])

    return response
export_batches_as_csv.short_description = "Export Selected Batches as CSV"


class InventoryBatchAdmin(admin.ModelAdmin):
    list_display = ('batch_number', 'product', 'supplier', 'quantity', 'quotation', 'received_date', 'expiry_date')
    list_filter = ('supplier', 'product', 'received_date', 'expiry_date')
    search_fields = ('batch_number', 'product__name', 'quotation__quotation_id')

    actions = [export_batches_as_csv]

admin.site.register(Supplier, SupplierAdmin)
admin.site.register(Quotation, QuotationAdmin)
admin.site.register(InventoryBatch, InventoryBatchAdmin)
