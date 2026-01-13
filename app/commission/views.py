# distributorplatform/app/commission/views.py
import json
import csv
import datetime
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.db import transaction
from django.db.models import Q, Sum, Count
from django.views.decorators.http import require_POST, require_GET
from django.utils.dateparse import parse_date
from django.utils import timezone

from inventory.views import staff_required
from .models import CommissionLedger

@staff_required
def api_get_commissions(request):
    """
    Fetch commissions with optional filtering and return dashboard stats.
    """
    status_filter = request.GET.get('status', '') # Default to empty for 'All' or specific filter
    if status_filter == 'null': status_filter = '' # Handle potential JS null string

    search_query = request.GET.get('search', '').strip()

    # --- 1. Dashboard Statistics (Current Month Context) ---
    # These are calculated independently of the table filters to provide a consistent monthly overview.
    now = timezone.now()
    current_year = now.year
    current_month = now.month

    # A. Total Payout: Sum of amounts for commissions PAID in the current month
    payout_stats = CommissionLedger.objects.filter(
        status=CommissionLedger.CommissionStatus.PAID,
        paid_at__year=current_year,
        paid_at__month=current_month
    ).aggregate(total_payout=Sum('amount'))

    month_payout = payout_stats['total_payout'] or 0.0

    # B. Sales Activity: Orders and Items that GENERATED commissions in the current month (Created Date)
    activity_qs = CommissionLedger.objects.filter(
        created_at__year=current_year,
        created_at__month=current_month
    )

    # Count total commission records (1 record = 1 order item)
    month_items = activity_qs.count()

    # Count unique orders associated with these commissions
    month_orders = activity_qs.values('order_item__order').distinct().count()

    stats = {
        'month_payout': float(month_payout),
        'month_orders': month_orders,
        'month_items': month_items
    }

    # --- 2. Table Data Query ---
    commissions_qs = CommissionLedger.objects.select_related(
        'agent', 'order_item__order', 'order_item__product'
    ).order_by('-created_at')

    # Apply Table Filters
    if status_filter:
        commissions_qs = commissions_qs.filter(status=status_filter)

    if search_query:
        commissions_qs = commissions_qs.filter(
            Q(agent__username__icontains=search_query) |
            Q(order_item__order__id__icontains=search_query) |
            Q(order_item__product__name__icontains=search_query)
        )

    # Serialize List
    data = []
    for c in commissions_qs:
        data.append({
            'id': c.id,
            'created_at': c.created_at.strftime('%Y-%m-%d'),
            'agent_name': c.agent.username,
            'order_id': c.order_item.order.id,
            'product_name': c.order_item.product.name,
            'amount': float(c.amount),
            'status': c.get_status_display(),
            'paid_at': c.paid_at.strftime('%Y-%m-%d') if c.paid_at else '-'
        })

    return JsonResponse({
        'commissions': data,
        'stats': stats
    })

@staff_required
@require_POST
@transaction.atomic
def api_pay_commissions(request):
    """
    Bulk pay selected commissions.
    Expects JSON: { "ids": [1, 2], "payment_date": "2023-10-27" }
    """
    try:
        data = json.loads(request.body)
        commission_ids = data.get('ids', [])
        payment_date_str = data.get('payment_date')

        if not commission_ids:
            return JsonResponse({'success': False, 'error': 'No commissions selected.'}, status=400)

        if not payment_date_str:
            return JsonResponse({'success': False, 'error': 'Payment date is required.'}, status=400)

        payment_date = parse_date(payment_date_str)
        if not payment_date:
            return JsonResponse({'success': False, 'error': 'Invalid date format.'}, status=400)

        # Update only PENDING items to avoid re-paying
        updated_count = CommissionLedger.objects.filter(
            id__in=commission_ids,
            status=CommissionLedger.CommissionStatus.PENDING
        ).update(
            status=CommissionLedger.CommissionStatus.PAID,
            paid_at=payment_date
        )

        return JsonResponse({
            'success': True,
            'message': f'Successfully marked {updated_count} commissions as paid.'
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@staff_required
@require_GET
def export_commission_statement(request):
    """
    Export commissions to CSV based on Month/Year/Status.
    """
    try:
        month = int(request.GET.get('month', timezone.now().month))
        year = int(request.GET.get('year', timezone.now().year))
        status = request.GET.get('status', '') # Empty = All

        # Filter by Creation Date (Earnings) or Paid Date?
        # Usually Statements are based on earnings created in that month,
        # OR payments made in that month. Let's default to 'Created Date' for the statement context.
        qs = CommissionLedger.objects.filter(
            created_at__year=year,
            created_at__month=month
        ).select_related('agent', 'order_item__order', 'order_item__product').order_by('created_at')

        if status:
            qs = qs.filter(status=status)

        # Create CSV Response
        response = HttpResponse(content_type='text/csv')
        filename = f"commission_statement_{year}_{month:02d}.csv"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow(['Date Earned', 'Agent Username', 'Agent Email', 'Order ID', 'Product', 'Quantity', 'Amount (RM)', 'Status', 'Paid Date'])

        for c in qs:
            writer.writerow([
                c.created_at.strftime('%Y-%m-%d %H:%M'),
                c.agent.username,
                c.agent.email,
                c.order_item.order.id,
                c.order_item.product.name,
                c.order_item.quantity,
                f"{c.amount:.2f}",
                c.get_status_display(),
                c.paid_at.strftime('%Y-%m-%d') if c.paid_at else '-'
            ])

        return response

    except Exception as e:
        return HttpResponse(f"Error exporting CSV: {str(e)}", status=500)
