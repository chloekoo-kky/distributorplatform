from django.contrib import admin
from .models import Supplier, Quotation, InventoryBatch

class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_person', 'email', 'phone')
    search_fields = ('name',)

class QuotationAdmin(admin.ModelAdmin):
    list_display = ('product', 'supplier', 'quoted_price', 'date_quoted')
    list_filter = ('supplier', 'date_quoted')

class InventoryBatchAdmin(admin.ModelAdmin):
    list_display = ('batch_number', 'product', 'supplier', 'quantity', 'unit_cost', 'landed_cost_per_unit', 'received_date')
    list_filter = ('supplier', 'product', 'received_date')
    search_fields = ('batch_number', 'product__name')
    # Display our calculated properties, but make them read-only
    readonly_fields = ('total_cost', 'landed_cost_per_unit')

admin.site.register(Supplier, SupplierAdmin)
admin.site.register(Quotation, QuotationAdmin)
admin.site.register(InventoryBatch, InventoryBatchAdmin)
