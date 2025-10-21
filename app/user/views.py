# distributorplatform/app/user/views.py
import json
import logging
import time
from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST
from ratelimit.decorators import ratelimit
from ratelimit.exceptions import Ratelimited
from .forms import CustomUserCreationForm
from .models import UserGroup, CustomUser
from .utils import generate_verification_code, send_verification_code

# Get logger instance
logger = logging.getLogger(__name__)

# This key function is for rate limiting based on the submitted phone number
def get_phone_number_key(group, request):
    return f"{request.POST.get('phone_number_0')}-{request.POST.get('phone_number_1')}"


@require_POST
@ratelimit(key='ip', rate='10/h', block=True) # Limit by IP: 10 requests per hour
@ratelimit(key=get_phone_number_key, rate='3/h', block=True) # Limit by phone number: 3 requests per hour
def register(request):
    # --- Handle AJAX (JavaScript) submission ---
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            registration_data = request.POST.copy()
            phone_number = form.cleaned_data.get('phone_number')

            logger.info("[register] Form is valid. Attempting to send code.")
            code = generate_verification_code()
            if send_verification_code(phone_number, code):
                # Store data, code, and expiry in session
                request.session['registration_data'] = registration_data.dict()
                request.session['verification_code'] = code
                request.session['phone_number_to_verify'] = str(phone_number)
                request.session['verification_code_expiry'] = time.time() + 300 # 5 minute expiry

                logger.info("[register] Code sent successfully. Storing data in session.")
                return JsonResponse({'success': True, 'phone_number': str(phone_number)})
            else:
                logger.error("[register] Failed to send verification code.")
                return JsonResponse({
                    'success': False,
                    'error': 'We failed to send a verification code. Please check your phone number and try again.'
                }, status=400)
        else:
            logger.warning(f"[register] Form is invalid: {form.errors.as_json()}")
            return JsonResponse({'success': False, 'errors': json.loads(form.errors.as_json())}, status=400)

    return redirect('register')


def verify_phone(request):
    # --- Check for code expiry ---
    expiry_time = request.session.get('verification_code_expiry')
    if not expiry_time or time.time() > expiry_time:
        messages.error(request, "Verification code has expired. Please register again.")
        # Clean up expired session data
        for key in ['registration_data', 'verification_code', 'phone_number_to_verify', 'verification_code_expiry']:
            if key in request.session:
                del request.session[key]
        return redirect('register')

    # Get data from session
    registration_data = request.session.get('registration_data')
    stored_code = request.session.get('verification_code')

    if not (registration_data and stored_code):
        messages.error(request, "No registration data found or session expired. Please register first.")
        return redirect('register')

    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        try:
            data = json.loads(request.body)
            submitted_code = data.get('code')
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)

        if submitted_code == stored_code:
            form = CustomUserCreationForm(registration_data)
            if form.is_valid():
                user = form.save(commit=False)
                user.is_verified = True
                user.is_active = True
                user.save()

                try:
                    default_group = UserGroup.objects.get(is_default=True)
                    user.user_groups.add(default_group)
                except UserGroup.DoesNotExist:
                    pass

                # Clean up session
                for key in ['registration_data', 'verification_code', 'phone_number_to_verify', 'verification_code_expiry']:
                    if key in request.session:
                        del request.session[key]

                login(request, user)

                return JsonResponse({'success': True, 'redirect_url': reverse('product_list')})
            else:
                error_message = "A user with that username or email already exists. Please try logging in or use different details."
                return JsonResponse({'success': False, 'error': error_message}, status=400)
        else:
            return JsonResponse({'success': False, 'error': 'The 6-digit code is incorrect. Please try again.'}, status=400)

    if request.method == 'GET':
        messages.success(request, f"A verification code has been sent to your WhatsApp at {request.session.get('phone_number_to_verify')}.")

    return render(request, 'user/verify_phone.html')


# Custom handler for Ratelimited exception
def handler403(request, exception=None):
    if isinstance(exception, Ratelimited):
        # For AJAX requests, return a JSON response
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Too many requests. Please try again later.'}, status=403)
        # For regular requests, you could render a template
        # For now, we'll keep it simple
    return redirect('register')


def verify_phone(request):
    logger.info(f"[verify_phone] Received request method: {request.method}")
    # This view now only handles AJAX POST requests for verification
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        logger.info("[verify_phone] Processing AJAX POST request.")
        # Get data from session
        registration_data = request.session.get('registration_data')
        stored_code = request.session.get('verification_code')
        phone_number = request.session.get('phone_number_to_verify') # Get phone number for logging

        logger.info(f"[verify_phone] Retrieved from session - registration_data: {'Exists' if registration_data else 'Missing'}")
        logger.info(f"[verify_phone] Retrieved from session - stored_code: {'Exists' if stored_code else 'Missing'}")
        logger.info(f"[verify_phone] Retrieved from session - phone_number: {phone_number if phone_number else 'Missing'}")


        if not (registration_data and stored_code):
            logger.error("[verify_phone] Missing registration data or code in session.")
            return JsonResponse({'success': False, 'error': 'Session expired. Please register again.'}, status=400)

        try:
            data = json.loads(request.body)
            submitted_code = data.get('code')
            logger.info(f"[verify_phone] Received code from request: {submitted_code}")
        except json.JSONDecodeError:
            logger.error("[verify_phone] Failed to decode JSON body.")
            return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)

        if submitted_code == stored_code:
            logger.info("[verify_phone] Submitted code matches stored code. Attempting user creation.")
            # --- SUCCESS: Create the user now ---
            # Re-initialize the form with the stored POST data (which is now a dict)
            form = CustomUserCreationForm(registration_data)
            if form.is_valid():
                logger.info("[verify_phone] Form re-validation successful.")
                user = form.save(commit=False)
                user.is_verified = True
                user.is_active = True # User is now active
                user.save()
                logger.info(f"[verify_phone] User {user.username} created successfully.")

                # Assign user to the default group
                try:
                    default_group = UserGroup.objects.get(is_default=True)
                    user.user_groups.add(default_group)
                    logger.info(f"[verify_phone] Assigned user {user.username} to default group {default_group.name}.")
                except UserGroup.DoesNotExist:
                    logger.warning("[verify_phone] No default user group found to assign.")
                    pass

                # Clean up session
                logger.info("[verify_phone] Clearing session data.")
                for key in ['registration_data', 'verification_code', 'phone_number_to_verify']:
                    if key in request.session:
                        del request.session[key]

                # Log the user in
                login(request, user)
                logger.info(f"[verify_phone] User {user.username} logged in.")

                return JsonResponse({
                    'success': True,
                    'redirect_url': reverse('product_list')
                })
            else:
                # Log the specific form errors during re-validation
                logger.error(f"[verify_phone] Form re-validation failed: {form.errors.as_json()}")
                # Provide a more specific error if possible (e.g., uniqueness)
                error_message = "An error occurred during final validation. Please try registering again."
                if 'username' in form.errors or 'email' in form.errors:
                     error_message = "A user with that username or email already exists. Please try logging in or use different details."

                return JsonResponse({'success': False, 'error': error_message}, status=400)
        else:
            logger.warning("[verify_phone] Submitted code does not match stored code.")
            return JsonResponse({'success': False, 'error': 'The 6-digit code is incorrect. Please try again.'}, status=400)

    # Any non-AJAX or GET request redirects back to register
    logger.warning(f"[verify_phone] Received non-AJAX POST or GET request. Redirecting to register.")
    return redirect('register')
