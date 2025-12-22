# distributorplatform/app/user/views.py
import json
import logging
import time
import uuid
import requests

from django.shortcuts import render, redirect, get_object_or_404 # Add get_object_or_404
from django.contrib.auth import login
from django.db.models import Sum
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, Http404 # Add Http404
from django.urls import reverse
from django_ratelimit.decorators import ratelimit
from django_ratelimit.exceptions import Ratelimited
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.http import HttpResponse

from core.models import SiteSetting
from .forms import CustomUserCreationForm
from .models import UserGroup, CustomUser, SubscriptionPlan
from .utils import generate_verification_code, send_verification_code
from django.core.paginator import Paginator, EmptyPage # Add Paginator
from django.db.models import Q # Add Q
from inventory.views import staff_required # Add staff_required
from decimal import Decimal # Add Decimal



from .forms import CustomUserCreationForm
from .models import UserGroup, CustomUser, SubscriptionPayment
from .utils import generate_verification_code, send_verification_code
from order.models import Order
from commission.models import CommissionLedger


logger = logging.getLogger(__name__)

# Key function for rate limiting based on email
def get_email_key(group, request):
    return request.POST.get('email', '')


# --- CORRECTED DECORATORS ---
# The 'method='POST'' argument tells the decorator to ONLY run for POST requests.
# @ratelimit(key=get_email_key, rate='5/h', method='POST', block=True)
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
            # Changed from phone_number to email
            email = form.cleaned_data.get('email')

            logger.info(f"[register] Form is valid. Attempting to send code to {email}.")
            code = generate_verification_code()

            if send_verification_code(email, code):
                request.session['registration_data'] = registration_data.dict()
                request.session['verification_code'] = code
                # Store email in session instead of phone
                request.session['email_to_verify'] = email
                request.session['verification_code_expiry'] = time.time() + 300 # 5 min expiry
                logger.info("[register] Code sent successfully.")
                # Return email in response
                return JsonResponse({'success': True, 'email': email})
            else:
                logger.error("[register] Failed to send verification code.")
                return JsonResponse({'success': False, 'error': 'Failed to send verification email. Please check your address.'}, status=400)
        else:
            logger.warning(f"[register] Form invalid: {form.errors.as_json()}")
            return JsonResponse({'success': False, 'errors': json.loads(form.errors.as_json())}, status=400)

    # Fallback for non-AJAX POST
    return redirect('user:register')


def verify_email(request):
    # Renamed from verify_phone to verify_email
    logger.info(f"[verify_email] Received request method: {request.method}")
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        logger.info("[verify_email] Processing AJAX POST request.")

        expiry_time = request.session.get('verification_code_expiry')
        if not expiry_time or time.time() > expiry_time:
            logger.warning("[verify_email] Verification code has expired.")
            for key in ['registration_data', 'verification_code', 'email_to_verify', 'verification_code_expiry']:
                if key in request.session:
                    del request.session[key]
            return JsonResponse({'success': False, 'error': 'Verification code has expired. Please register again.'}, status=400)

        registration_data = request.session.get('registration_data')
        stored_code = request.session.get('verification_code')

        if not (registration_data and stored_code):
            logger.error("[verify_email] Missing registration data or code in session.")
            return JsonResponse({'success': False, 'error': 'Session expired. Please register again.'}, status=400)

        try:
            data = json.loads(request.body)
            submitted_code = data.get('code')
        except json.JSONDecodeError:
            logger.error("[verify_email] Failed to decode JSON body.")
            return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)

        if submitted_code == stored_code:
            logger.info("[verify_email] Code matches. Creating user.")
            form = CustomUserCreationForm(registration_data)
            if form.is_valid():
                user = form.save(commit=False)
                user.is_verified = True
                user.is_active = True
                user.save()
                logger.info(f"[verify_email] User {user.username} created.")

                try:
                    default_group = UserGroup.objects.get(is_default=True)
                    user.user_groups.add(default_group)
                except UserGroup.DoesNotExist:
                    pass

                # Clear session data
                for key in ['registration_data', 'verification_code', 'email_to_verify', 'verification_code_expiry']:
                    if key in request.session:
                        del request.session[key]

                login(request, user)
                logger.info(f"[verify_email] User {user.username} logged in.")
                return JsonResponse({'success': True, 'redirect_url': reverse('product:product_list')})
            else:
                error_message = "A user with that username or email already exists."
                return JsonResponse({'success': False, 'error': error_message}, status=400)
        else:
            return JsonResponse({'success': False, 'error': 'The 6-digit code is incorrect.'}, status=400)

    return redirect('user:register')


# This handler will now be correctly called for rate-limited POST requests
def handler403(request, exception=None):
    if isinstance(exception, Ratelimited):
        logger.warning(f"Rate limit exceeded: {exception}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': 'You have exceeded the request limit. Please wait a while and try again.'
            }, status=403)
        else:
            messages.error(request, 'Too many requests. Please try again later.')
            return redirect('product:product_list')

    logger.error(f"Permission denied (403) for request to {request.path}")
    messages.error(request, 'Permission denied.')
    return redirect('product:product_list')


@staff_required
def api_manage_user_groups(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            group_id = data.get('id')
            commission_str = data.get('commission_percentage')
            if commission_str is None: raise ValueError("Commission percentage required.")

            group = get_object_or_404(UserGroup, pk=group_id)
            group.commission_percentage = Decimal(commission_str)
            group.save(update_fields=['commission_percentage'])

            return JsonResponse({'success': True, 'group': {'id': group.id, 'name': group.name, 'commission_percentage': group.commission_percentage}})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    groups = UserGroup.objects.all().order_by('name')
    data = [{'id': g.id, 'name': g.name, 'commission_percentage': g.commission_percentage} for g in groups]
    return JsonResponse({'groups': data})

@staff_required
def api_manage_users(request):
    search = request.GET.get('search', '')
    page_number = request.GET.get('page', 1)

    queryset = CustomUser.objects.prefetch_related('user_groups').order_by('username')
    if search:
        queryset = queryset.filter(Q(username__icontains=search) | Q(email__icontains=search))

    paginator = Paginator(queryset, 25)
    try:
        page_obj = paginator.page(page_number)
    except EmptyPage:
        return JsonResponse({'users': [], 'pagination': {}})

    serialized_users = []
    for u in page_obj.object_list:
        # 1. Determine Subscription Plan
        # Find the plan associated with any of the user's current groups
        active_plan = SubscriptionPlan.objects.filter(target_group__in=u.user_groups.all()).first()
        plan_name = active_plan.name if active_plan else "-"

        # 2. Get Last Payment Info
        last_payment = SubscriptionPayment.objects.filter(user=u).order_by('-created_at').first()
        payment_amount = last_payment.amount if last_payment else None
        payment_status = last_payment.status if last_payment else "-"

        serialized_users.append({
            'id': u.id,
            'username': u.username,
            'email': u.email,
            'phone_number': str(u.phone_number),
            'is_staff': u.is_staff,
            'groups': list(u.user_groups.values_list('id', flat=True)),
            'group_names': ", ".join(list(u.user_groups.values_list('name', flat=True))),
            # --- NEW FIELDS ---
            'subscription_plan': plan_name,
            'payment_amount': str(payment_amount) if payment_amount is not None else "-",
            'payment_status': payment_status
        })

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
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=400)
    user = get_object_or_404(CustomUser, pk=user_id)
    try:
        data = json.loads(request.body)
        group_ids = data.get('group_ids', [])
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
    orders = Order.objects.filter(agent=user).prefetch_related('items__product').order_by('-created_at')

    # Calculate order totals for display
    for order in orders:
        total = sum(item.selling_price * item.quantity for item in order.items.all())
        order.calculated_total = total

    # --- NEW: Get Subscription Plans ---
    plans = SubscriptionPlan.objects.filter(is_active=True)

    # Determine current plan based on user's groups
    current_plan_id = None
    # We look for a plan whose target_group matches one of the user's groups
    for plan in plans:
        if user.user_groups.filter(id=plan.target_group.id).exists():
            current_plan_id = plan.id
            break

    context = {
        'is_agent': is_agent,
        'orders': orders,
        'plans': plans,               # Passed to template
        'current_plan_id': current_plan_id # Passed to template
    }

    # 3. Get Commission Data (Agent Only)
    if is_agent:
        commissions = CommissionLedger.objects.filter(agent=user).select_related('order_item__product').order_by('-created_at')

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

@login_required
@ratelimit(key='user', rate='10/h', method='POST')
def api_update_subscription(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=400)

    try:
        data = json.loads(request.body)
        plan_id = data.get('plan_id')

        selected_plan = get_object_or_404(SubscriptionPlan, pk=plan_id, is_active=True)
        config = SiteSetting.objects.first()
        user = request.user

        # --- UPDATE: Calculate Annual Price ---
        # Assuming plan.price is the monthly rate
        annual_price = selected_plan.price * 12

        # Handle FREE Plans
        if annual_price <= 0:
            _update_user_plan_logic(user, selected_plan)
            return JsonResponse({
                'success': True,
                'action': 'updated',
                'message': f"Successfully switched to {selected_plan.name}."
            })

        if not config or not config.payment_enabled:
            return JsonResponse({'success': False, 'error': 'Online payments are currently disabled.'}, status=503)

        ref_id = f"SUB-{uuid.uuid4().hex[:12].upper()}"

        # Create Payment Record with Annual Amount
        payment = SubscriptionPayment.objects.create(
            user=user,
            plan=selected_plan,
            amount=annual_price, # Store total paid (12 months)
            reference_id=ref_id,
            status='PENDING'
        )

        # 4. Payment Gateway Logic
        if config.payment_provider == 'TOYYIBPAY':
            # Pass the annual_price to the helper
            return _initiate_toyyibpay_payment(request, user, selected_plan, config, ref_id, annual_price)

        elif config.payment_provider == 'BILLPLZ':
            # Placeholder for Billplz logic
            return _initiate_billplz_payment(request, user, selected_plan, config, ref_id)

        elif config.payment_provider == 'STRIPE':
            # Placeholder for Stripe logic
            return JsonResponse({'success': False, 'error': 'Stripe provider not yet implemented.'}, status=501)

        else:
            return JsonResponse({'success': False, 'error': 'Invalid payment provider configuration.'}, status=500)

    except Exception as e:
        logger.error(f"Subscription Error: {str(e)}")
        return JsonResponse({'success': False, 'error': 'An unexpected error occurred. Please try again.'}, status=500)

# --- Helper Methods ---

def _update_user_plan_logic(user, plan):
    """
    Removes user from old subscription groups and adds to the new one.
    """
    # Find all groups that are linked to ANY subscription plan
    all_plan_groups = UserGroup.objects.filter(subscription_plans__isnull=False).distinct()

    # Remove user from these groups
    user.user_groups.remove(*all_plan_groups)

    # Add to the new target group
    user.user_groups.add(plan.target_group)

    # Optional: Log the change
    logger.info(f"User {user.username} upgraded to plan {plan.name} (Group: {plan.target_group.name})")

def _initiate_toyyibpay_payment(request, user, plan, config, ref_id):
    """
    Constructs the payload and calls ToyyibPay API.
    """
    # 1. Prepare Payload
    # Note: ToyyibPay expects amount in CENTS usually, strictly check their latest docs.
    # Standard CreateBill API usually takes Ringgit (RM) but some versions take cents.
    # Assuming standard 'billAmount' is in CENTS (e.g. RM1.00 = 100).
    bill_amount_cents = int(plan.price * 100)

    payload = {
        'userSecretKey': config.payment_api_key,
        'categoryCode': config.payment_category_code,
        'billName': f"Subscription: {plan.name}",
        'billDescription': f"Upgrade to {plan.name} Plan for {user.username}",
        'billPriceSetting': 1,
        'billPayorInfo': 1,
        'billAmount': bill_amount_cents,
        'billReturnUrl': request.build_absolute_uri(reverse('user:payment_callback')),
        'billCallbackUrl': request.build_absolute_uri(reverse('user:payment_webhook')),
        'billExternalReferenceNo': ref_id,
        'billTo': user.username,
        'billEmail': user.email,
        'billPhone': str(user.phone_number).replace('+', ''), # Remove + for some gateways
        'billSplitPayment': 0,
        'billPaymentChannel': '0', # 0 for FPX, 1 for Credit Card, 2 for Both
    }

    try:
        # 2. Send Request
        # Use the configured URL or fallback to production default
        gateway_url = config.payment_gateway_url or "https://toyyibpay.com/index.php/api/createBill"

        response = requests.post(gateway_url, data=payload, timeout=10)
        resp_data = response.json()

        # 3. Handle Response
        # ToyyibPay returns an array with 'BillCode' on success
        if isinstance(resp_data, list) and 'BillCode' in resp_data[0]:
            bill_code = resp_data[0]['BillCode']

            # Construct the payment URL for the user
            # Determine base URL (dev or prod) based on the API URL used
            base_url = "https://dev.toyyibpay.com" if "dev" in gateway_url else "https://toyyibpay.com"
            payment_url = f"{base_url}/{bill_code}"

            return JsonResponse({
                'success': True,
                'action': 'redirect',
                'payment_url': payment_url
            })
        else:
            logger.error(f"ToyyibPay Error: {resp_data}")
            return JsonResponse({'success': False, 'error': 'Payment gateway rejected the request.'}, status=502)

    except requests.exceptions.RequestException as e:
        logger.error(f"Gateway Connection Error: {e}")
        return JsonResponse({'success': False, 'error': 'Could not connect to payment gateway.'}, status=502)

def _initiate_billplz_payment(request, user, plan, config, ref_id, amount):
    """
    Constructs the payload and calls Billplz API.
    """
    # Billplz uses Basic Auth (User=API Key, Pass=Empty)
    # Amount is in CENTS (e.g., RM10.00 -> 1000)
    bill_amount_cents = int(amount * 100)

    payload = {
        'collection_id': config.payment_category_code,
        'email': user.email,
        'mobile': str(user.phone_number).replace('+', ''),
        'name': user.username,
        'amount': bill_amount_cents,
        'callback_url': request.build_absolute_uri(reverse('user:payment_webhook')),
        'description': f"Annual Subscription: {plan.name}",
        # Custom redirect (Billplz supports redirect_url param in v3)
        'redirect_url': request.build_absolute_uri(reverse('user:payment_callback')),
        # Pass reference ID to track this specific transaction
        'reference_1_label': 'Ref ID',
        'reference_1': ref_id
    }

    try:
        # Send Request
        response = requests.post(
            config.payment_gateway_url, # https://www.billplz-sandbox.com/api/v3/bills
            auth=(config.payment_api_key, ''), # Basic Auth
            data=payload,
            timeout=10
        )
        resp_data = response.json()

        # Billplz returns { "id": "...", "url": "https://billplz.com/bills/..." }
        if 'url' in resp_data:
            return JsonResponse({
                'success': True,
                'action': 'redirect',
                'payment_url': resp_data['url']
            })
        else:
            logger.error(f"Billplz Error: {resp_data}")
            return JsonResponse({'success': False, 'error': 'Payment gateway rejected the request.'}, status=502)

    except requests.exceptions.RequestException as e:
        logger.error(f"Gateway Connection Error: {e}")
        return JsonResponse({'success': False, 'error': 'Could not connect to payment gateway.'}, status=502)

def subscription_plans_view(request):
    """
    Public page to display all active subscription plans.
    """
    plans = SubscriptionPlan.objects.filter(is_active=True)
    current_plan_id = None

    # If logged in, identify their current plan
    if request.user.is_authenticated:
        for plan in plans:
            if request.user.user_groups.filter(id=plan.target_group.id).exists():
                current_plan_id = plan.id
                break

    context = {
        'plans': plans,
        'current_plan_id': current_plan_id
    }
    return render(request, 'user/subscription_plans.html', context)

@csrf_exempt
def payment_webhook(request):
    """
    Background server-to-server notification from the Gateway.
    """
    if request.method == 'POST':
        data = request.POST
        ref_id = data.get('refno')
        status = data.get('status') # '1' = Success, '3' = Fail (ToyyibPay)

        try:
            payment = SubscriptionPayment.objects.get(reference_id=ref_id)

            if status == '1' and payment.status != 'PAID':
                payment.status = 'PAID'
                payment.completed_at = timezone.now()
                payment.save()

                # ACTUAL UPGRADE
                _update_user_plan_logic(payment.user, payment.plan)
                logger.info(f"Webhook: Payment {ref_id} confirmed.")

            elif status == '3':
                payment.status = 'FAILED'
                payment.save()

            return HttpResponse("OK")
        except SubscriptionPayment.DoesNotExist:
            logger.warning(f"Webhook: Payment ref {ref_id} not found.")
            return HttpResponse("Not Found", status=404)

    return HttpResponse("Invalid Method", status=405)

def payment_callback(request):
    """
    User is redirected here after payment.
    """
    status_id = request.GET.get('status_id') # '1' = Success
    ref_id = request.GET.get('order_id') # ToyyibPay passes ref as order_id

    if status_id == '1':
        messages.success(request, "Payment successful! Your plan has been upgraded.")
    else:
        messages.error(request, "Payment failed or was cancelled.")

    return redirect('user:profile')

@login_required
def checkout_view(request, plan_id):
    """
    Displays a confirmation page before initiating payment/subscription switch.
    """
    plan = get_object_or_404(SubscriptionPlan, pk=plan_id, is_active=True)

    # Optional: Check if user is already on this plan
    # (Logic similar to profile_view or subscription_plans_view)

    context = {
        'plan': plan,
        'site_settings': SiteSetting.objects.first(),
    }
    return render(request, 'user/checkout.html', context)
