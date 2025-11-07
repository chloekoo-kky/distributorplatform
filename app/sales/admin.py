# distributorplatform/app/sales/admin.py
from django.contrib import admin
from .models import Invoice, InvoiceItem

class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0
    fields = ('product', 'description', 'quantity', 'unit_price', 'total_price')
    readonly_fields = ('total_price',)

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    # --- UPDATED list_display ---
    list_display = ('invoice_id', 'supplier', 'quotation', 'date_issued', 'payment_date', 'status', 'total_amount')
    list_filter = ('status', 'date_issued', 'supplier')
    search_fields = ('invoice_id', 'supplier__name', 'quotation__quotation_id')
    readonly_fields = ('invoice_id', 'subtotal', 'total_amount', 'created_at', 'updated_at')
    inlines = [InvoiceItemInline]
    fieldsets = (
        (None, {
            'fields': ('invoice_id', 'supplier', 'quotation', 'status')
        }),
        ('Dates', {
            # --- UPDATED fieldsets ---
            'fields': ('date_issued', 'payment_date')
        }),
        ('Amounts', {
            'fields': ('transportation_cost', 'subtotal', 'total_amount')
        }),
        ('Other Info', {
            'fields': ('notes', 'created_at', 'updated_at')
        }),
    )

@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    list_display = ('invoice', 'product', 'description', 'quantity', 'unit_price', 'total_price')
    list_filter = ('invoice__supplier',)
    search_fields = ('invoice__invoice_id', 'product__name', 'description')
    readonly_fields = ('total_price',)
