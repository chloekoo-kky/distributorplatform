from django.contrib import admin
from django.db.models import Sum, F, Q
from django.utils.html import format_html
from django.urls import reverse
from import_export.admin import ImportExportModelAdmin
from .models import Order, OrderItem, Customer, CustomerAddress, SalesInvoiceIssuer


@admin.register(SalesInvoiceIssuer)
class SalesInvoiceIssuerAdmin(admin.ModelAdmin):
    list_display = ('label', 'legal_name', 'tax_id', 'is_default', 'updated_at')
    list_filter = ('is_default',)
    search_fields = ('label', 'legal_name', 'tax_id', 'registration_no')
    ordering = ('-is_default', 'label')
    readonly_fields = ('logo_preview',)

    fieldsets = (
        (None, {
            'fields': (
                'label', 'legal_name', 'is_default', 'logo', 'logo_preview',
                'address', 'phone', 'email', 'tax_id', 'registration_no', 'bank_details',
            ),
        }),
    )

    def logo_preview(self, obj):
        if not obj or not getattr(obj, 'logo', None) or not obj.logo.name:
            return '—'
        return format_html(
            '<img src="{}" alt="" style="max-height:64px;max-width:200px;object-fit:contain;" />',
            obj.logo.url,
        )

    logo_preview.short_description = 'Logo preview'


class CustomerAddressInline(admin.TabularInline):
    model = CustomerAddress
    extra = 0
    fields = ('label', 'address', 'is_default', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(Customer)
class CustomerAdmin(ImportExportModelAdmin):
    list_display = ('name', 'phone', 'email', 'created_at')
    search_fields = ('name', 'phone', 'email')
    list_per_page = 25
    inlines = [CustomerAddressInline]

    actions = ['backfill_orders_from_customers']

    def backfill_orders_from_customers(self, request, queryset):
        """
        For selected customers, link existing orders (without customer FK)
        based on matching phone and, when present, case-insensitive name.
        Also create CustomerAddress entries from order shipping addresses.
        """
        linked_orders = 0
        created_addresses = 0
        for customer in queryset:
            phone = (customer.phone or '').strip()
            name = (customer.name or '').strip()
            if not phone and not name:
                continue
            q = Q(customer__isnull=True)
            if phone:
                q &= Q(customer_phone__iexact=phone)
            if name:
                q &= Q(customer_name__iexact=name)
            orders = Order.objects.filter(q)
            for o in orders:
                o.customer = customer
                o.save(update_fields=['customer'])
                linked_orders += 1
                addr = (o.shipping_address or '').strip()
                if addr:
                    if not CustomerAddress.objects.filter(customer=customer, address=addr).exists():
                        is_default = not CustomerAddress.objects.filter(customer=customer).exists()
                        CustomerAddress.objects.create(
                            customer=customer,
                            label=None,
                            address=addr,
                            is_default=is_default,
                        )
                        created_addresses += 1

        self.message_user(
            request,
            f"Linked {linked_orders} order(s) and created {created_addresses} new address(es)."
        )
    backfill_orders_from_customers.short_description = "Backfill orders and addresses from selected customers"

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    # Make the product name clickable and calculate row totals
    readonly_fields = ('product_link', 'row_total', 'profit')
    fields = ('product_link', 'quantity', 'selling_price', 'landed_cost', 'row_total', 'profit')
    can_delete = False

    def product_link(self, obj):
        """Link to the actual product edit page."""
        if obj.product:
            url = reverse("admin:product_product_change", args=[obj.product.id])
            return format_html('<a href="{}" style="font-weight:bold;">{}</a><br><span style="color:#666; font-size:10px;">{}</span>', url, obj.product.name, obj.product.sku)
        return "-"
    product_link.short_description = "Product"

    def row_total(self, obj):
        """Calculates total for this line item."""
        if obj.selling_price and obj.quantity:
            return f"{(obj.selling_price * obj.quantity):.2f}"
        return "0.00"
    row_total.short_description = "Total"

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_id_display',
        'customer',
        'customer_name',
        'customer_phone',
        'agent_link',
        'customer_type_badge',
        'status_badge',
        'created_at',
        'get_total_value',
        'get_total_commission',
        'get_net_profit',
    )
    list_display_links = ('order_id_display',)
    list_editable = ('customer', 'customer_name', 'customer_phone')
    autocomplete_fields = ('customer',)
    list_filter = ('status', 'created_at', 'agent__user_groups')
    search_fields = (
        'id',
        'agent__username',
        'agent__email',
        'company_name',
        'customer_name',
        'customer_phone',
        'customer__name',
        'customer__phone',
        'customer__email',
    )
    date_hierarchy = 'created_at'
    list_per_page = 25

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('agent', 'customer')

    # --- Actions ---
    actions = ['mark_as_completed', 'mark_as_processing', 'mark_as_cancelled']

    # --- Layout (Fieldsets) ---
    fieldsets = (
        ('Order Information', {
            'fields': (
                ('agent', 'status'),
                ('created_at', 'updated_at'),
            )
        }),
        ('Customer', {
            'fields': (
                'customer',
                'company_name',
                ('customer_name', 'customer_phone'),
                'shipping_address',
            ),
        }),
        ('Financial Summary', {
            'fields': (
                'get_total_value',
                'get_total_profit',
                'get_total_commission',
                'get_net_profit'
            ),
            'classes': ('collapse', 'wide'),
            'description': 'Calculated metrics based on order items.'
        }),
    )

    readonly_fields = (
        'created_at', 'updated_at',
        'get_total_value', 'get_total_profit',
        'get_total_commission', 'get_net_profit'
    )

    inlines = [OrderItemInline]

    # --- Columns & Formatting ---

    def order_id_display(self, obj):
        return f"{str(obj.id)[:8]}..."
    order_id_display.short_description = "ID"
    order_id_display.admin_order_field = 'id'

    def agent_link(self, obj):
        """Distributor / agent User who owns the order."""
        url = reverse('admin:user_customuser_change', args=[obj.agent_id])
        return format_html('<a href="{}">{}</a>', url, obj.agent.username)

    agent_link.short_description = 'Agent'
    agent_link.admin_order_field = 'agent__username'

    def customer_type_badge(self, obj):
        commission = obj.total_commission
        if commission > 0:
            return format_html(
                '<span style="background-color:#dbeafe; color:#1e40af; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold;">AGENT</span>'
            )
        return format_html(
            '<span style="background-color:#dcfce7; color:#166534; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold;">DIRECT</span>'
        )
    customer_type_badge.short_description = 'Type'

    def status_badge(self, obj):
        colors = {
            'PENDING': '#fef9c3', # Yellow bg
            'COMPLETED': '#dcfce7', # Green bg
            'CANCELLED': '#fee2e2', # Red bg
        }
        text_colors = {
            'PENDING': '#854d0e',
            'COMPLETED': '#166534',
            'CANCELLED': '#991b1b',
        }
        bg = colors.get(obj.status, '#f3f4f6')
        text = text_colors.get(obj.status, '#1f2937')
        return format_html(
            '<span style="background-color:{}; color:{}; padding: 3px 8px; border-radius: 10px; font-size: 12px; font-weight: bold;">{}</span>',
            bg, text, obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    status_badge.admin_order_field = 'status'

    # --- Financial Calculations ---

    def get_total_value(self, obj):
        total = sum(item.selling_price * item.quantity for item in obj.items.all())
        return f"{total:.2f}"
    get_total_value.short_description = 'Total Value'

    def get_total_profit(self, obj):
        """Gross Profit."""
        return f"{obj.total_profit:.2f}"
    get_total_profit.short_description = 'Gross Profit'

    def get_total_commission(self, obj):
        return f"{obj.total_commission:.2f}"
    get_total_commission.short_description = 'Commission'

    def get_net_profit(self, obj):
        """Total Profit - Commission."""
        net = obj.total_profit - obj.total_commission
        return format_html('<b>{}</b>', f"{net:.2f}")
    get_net_profit.short_description = 'Net Profit'

    # --- Actions Methods ---

    @admin.action(description='Mark selected orders as Completed')
    def mark_as_completed(self, request, queryset):
        updated = queryset.update(status=Order.OrderStatus.COMPLETED)
        self.message_user(request, f"{updated} orders marked as Completed.")

    @admin.action(description='Mark selected orders as Pending')
    def mark_as_processing(self, request, queryset):
        updated = queryset.update(status=Order.OrderStatus.PENDING)
        self.message_user(request, f"{updated} orders marked as Pending.")

    @admin.action(description='Mark selected orders as Cancelled')
    def mark_as_cancelled(self, request, queryset):
        updated = queryset.update(status=Order.OrderStatus.CANCELLED)
        self.message_user(request, f"{updated} orders marked as Cancelled.")
