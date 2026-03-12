from django.contrib import admin
from .models import CommissionLedger


@admin.register(CommissionLedger)
class CommissionLedgerAdmin(admin.ModelAdmin):
    list_display = ('id', 'agent', 'order_item', 'amount', 'status', 'created_at', 'paid_at')
    list_filter = ('status', 'created_at')
    search_fields = ('agent__username', 'agent__email')
    readonly_fields = ('order_item', 'created_at')
    raw_id_fields = ('agent',)
    date_hierarchy = 'created_at'
    list_editable = ('status',)
    ordering = ('-created_at',)
