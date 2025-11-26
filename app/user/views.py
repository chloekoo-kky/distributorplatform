# distributorplatform/app/user/views.py
import json
import logging
import time
from django.shortcuts import render, redirect, get_object_or_404 # Add get_object_or_404
from django.contrib.auth import login
from django.db.models import Sum
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, Http404 # Add Http404
from django.urls import reverse
from django_ratelimit.decorators import ratelimit
from django_ratelimit.exceptions import Ratelimited
from .forms import CustomUserCreationForm
from .models import UserGroup, CustomUser
from .utils import generate_verification_code, send_verification_code
from django.core.paginator import Paginator, EmptyPage # Add Paginator
from django.db.models import Q # Add Q
from inventory.views import staff_required # Add staff_required
from decimal import Decimal # Add Decimal



from .forms import CustomUserCreationForm
from .models import UserGroup, CustomUser
from .utils import generate_verification_code, send_verification_code
from order.models import Order
from commission.models import CommissionLedger


logger = logging.getLogger(__name__)

# This key function is now only called for POST requests, so it's safe
def get_phone_number_key(group, request):
    return f"{request.POST.get('phone_number_0', '')}-{request.POST.get('phone_number_1', '')}"


# --- CORRECTED DECORATORS ---
# The 'method='POST'' argument tells the decorator to ONLY run for POST requests.
# GET requests will completely bypass the rate limiter.
@ratelimit(key='ip', rate='10/h', method='POST', block=True)
@ratelimit(key=get_phone_number_key, rate='3/h', method='POST', block=True)
def register(request):
    # Handle GET request to show the form
    if request.method == 'GET':
        form = CustomUserCreationForm()
        return render(request, 'user/register.html', {'form': form})

    # Handle POST (AJAX) submission
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            registration_data = request.POST.copy()
            phone_number = form.cleaned_data.get('phone_number')

            logger.info("[register] Form is valid. Attempting to send code.")
            code = generate_verification_code()
            if send_verification_code(phone_number, code):
                request.session['registration_data'] = registration_data.dict()
                request.session['verification_code'] = code
                request.session['phone_number_to_verify'] = str(phone_number)
                request.session['verification_code_expiry'] = time.time() + 300 # 5 min expiry
                logger.info("[register] Code sent successfully.")
                return JsonResponse({'success': True, 'phone_number': str(phone_number)})
            else:
                logger.error("[register] Failed to send verification code.")
                return JsonResponse({'success': False, 'error': 'Failed to send verification code.'}, status=400)
        else:
            logger.warning(f"[register] Form invalid: {form.errors.as_json()}")
            return JsonResponse({'success': False, 'errors': json.loads(form.errors.as_json())}, status=400)

    # Fallback for non-AJAX POST
    # --- FIXED REDIRECT ---
    return redirect('user:register')


def verify_phone(request):
    # ... (This function remains correct from the previous step) ...
    logger.info(f"[verify_phone] Received request method: {request.method}")
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        logger.info("[verify_phone] Processing AJAX POST request.")

        expiry_time = request.session.get('verification_code_expiry')
        if not expiry_time or time.time() > expiry_time:
            logger.warning("[verify_phone] Verification code has expired.")
            for key in ['registration_data', 'verification_code', 'phone_number_to_verify', 'verification_code_expiry']:
                if key in request.session:
                    del request.session[key]
            return JsonResponse({'success': False, 'error': 'Verification code has expired. Please register again.'}, status=400)

        registration_data = request.session.get('registration_data')
        stored_code = request.session.get('verification_code')

        if not (registration_data and stored_code):
            logger.error("[verify_phone] Missing registration data or code in session.")
            return JsonResponse({'success': False, 'error': 'Session expired. Please register again.'}, status=400)

        try:
            data = json.loads(request.body)
            submitted_code = data.get('code')
        except json.JSONDecodeError:
            logger.error("[verify_phone] Failed to decode JSON body.")
            return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)

        if submitted_code == stored_code:
            logger.info("[verify_phone] Code matches. Creating user.")
            form = CustomUserCreationForm(registration_data)
            if form.is_valid():
                user = form.save(commit=False)
                user.is_verified = True
                user.is_active = True
                user.save()
                logger.info(f"[verify_phone] User {user.username} created.")

                try:
                    default_group = UserGroup.objects.get(is_default=True)
                    user.user_groups.add(default_group)
                except UserGroup.DoesNotExist:
                    pass

                for key in ['registration_data', 'verification_code', 'phone_number_to_verify', 'verification_code_expiry']:
                    if key in request.session:
                        del request.session[key]

                login(request, user)
                logger.info(f"[verify_phone] User {user.username} logged in.")
                # --- FIXED REVERSE ---
                return JsonResponse({'success': True, 'redirect_url': reverse('product:product_list')})
            else:
                error_message = "A user with that username or email already exists."
                return JsonResponse({'success': False, 'error': error_message}, status=400)
        else:
            return JsonResponse({'success': False, 'error': 'The 6-digit code is incorrect.'}, status=400)

    # --- FIXED REDIRECT ---
    return redirect('user:register')


# This handler will now be correctly called for rate-limited POST requests
def handler403(request, exception=None):
    if isinstance(exception, Ratelimited):
        logger.warning(f"Rate limit exceeded: {exception}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': 'You have exceeded the verification request limit. Please wait a while and try again.'
            }, status=403)
        else:
            # Fallback for non-AJAX rate limits
            messages.error(request, 'Too many requests. Please try again later.')
            # --- FIXED REDIRECT ---
            return redirect('product:product_list')

    # Handle general 403 Permission Denied errors
    logger.error(f"Permission denied (403) for request to {request.path}")
    messages.error(request, 'Permission denied.')
    # --- FIXED REDIRECT ---
    return redirect('product:product_list')


@staff_required
def api_manage_user_groups(request):
    """
    GET: Returns a list of all UserGroups.
    POST: Updates the commission_percentage for a UserGroup.
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            group_id = data.get('id')
            commission_str = data.get('commission_percentage')

            if commission_str is None:
                 raise ValueError("Commission percentage is required.")

            group = get_object_or_404(UserGroup, pk=group_id)
            group.commission_percentage = Decimal(commission_str)
            group.save(update_fields=['commission_percentage'])

            return JsonResponse({'success': True, 'group': {
                'id': group.id,
                'name': group.name,
                'commission_percentage': group.commission_percentage
            }})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    # Handle GET
    groups = UserGroup.objects.all().order_by('name')
    data = [{
        'id': g.id,
        'name': g.name,
        'commission_percentage': g.commission_percentage
    } for g in groups]
    return JsonResponse({'groups': data})

@staff_required
def api_manage_users(request):
    """
    GET: Returns a paginated list of all users.
    """
    search = request.GET.get('search', '')
    page_number = request.GET.get('page', 1)

    queryset = CustomUser.objects.prefetch_related('user_groups').order_by('username')
    if search:
        queryset = queryset.filter(Q(username__icontains=search) | Q(email__icontains=search))

    paginator = Paginator(queryset, 25) # 25 users per page
    try:
        page_obj = paginator.page(page_number)
    except EmptyPage:
        return JsonResponse({'users': [], 'pagination': {}})

    serialized_users = [{
        'id': u.id,
        'username': u.username,
        'email': u.email,
        'phone_number': str(u.phone_number),
        'is_staff': u.is_staff,
        'groups': list(u.user_groups.values_list('id', flat=True)),
        'group_names': ", ".join(list(u.user_groups.values_list('name', flat=True)))
    } for u in page_obj.object_list]

    return JsonResponse({
        'users': serialized_users,
        'pagination': {
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
        }
    })

@staff_required
def api_update_user_groups(request, user_id):
    """
    POST: Updates the list of groups a specific user belongs to.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=400)

    user = get_object_or_404(CustomUser, pk=user_id)
    try:
        data = json.loads(request.body)
        group_ids = data.get('group_ids', [])

        # .set() is the most efficient way to handle this
        user.user_groups.set(group_ids)

        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
def profile_view(request):
    user = request.user

    # 1. Check if user is an Agent (has a group with > 0% commission)
    is_agent = user.user_groups.filter(commission_percentage__gt=0).exists()

    # 2. Get Order History (For everyone)
    # Optimize query by pre-fetching items and products
    orders = Order.objects.filter(agent=user).prefetch_related('items__product').order_by('-created_at')

    # Calculate order totals on the fly for display (or add a property to Order model)
    for order in orders:
        # Calculate total per order for the template
        total = sum(item.selling_price * item.quantity for item in order.items.all())
        order.calculated_total = total

    context = {
        'is_agent': is_agent,
        'orders': orders,
    }

    # 3. Get Commission Data (Agent Only)
    if is_agent:
        commissions = CommissionLedger.objects.filter(agent=user).select_related('order_item__product').order_by('-created_at')

        # Aggregates
        total_earnings = commissions.exclude(status='CANCELLED').aggregate(sum=Sum('amount'))['sum'] or 0
        pending_payout = commissions.filter(status='PENDING').aggregate(sum=Sum('amount'))['sum'] or 0
        paid_payout = commissions.filter(status='PAID').aggregate(sum=Sum('amount'))['sum'] or 0

        context.update({
            'commissions': commissions,
            'total_earnings': total_earnings,
            'pending_payout': pending_payout,
            'paid_payout': paid_payout,
        })

    return render(request, 'user/profile.html', context)
