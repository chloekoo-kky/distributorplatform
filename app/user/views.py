# distributorplatform/app/user/views.py
import json
import logging
import time
from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse
from django_ratelimit.decorators import ratelimit
from django_ratelimit.exceptions import Ratelimited
from .forms import CustomUserCreationForm
from .models import UserGroup, CustomUser
from .utils import generate_verification_code, send_verification_code

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
