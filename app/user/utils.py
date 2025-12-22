# distributorplatform/app/user/utils.py
import random
import logging
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)

def generate_verification_code():
    """Generates a random 6-digit code."""
    return str(random.randint(100000, 999999))

def send_verification_code(email, code):
    """
    Sends the verification code to the user's email address.
    """
    logger.info(f"[utils.py] Attempting to send verification code to {email}")

    subject = f"Your Verification Code - {getattr(settings, 'SITE_NAME', 'Distributor Platform')}"
    message = f"Your verification code is: {code}\n\nThis code will expire in 5 minutes."
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com')

    try:
        send_mail(
            subject,
            message,
            from_email,
            [email],
            fail_silently=False,
        )
        logger.info(f"[utils.py] Verification email sent successfully to {email}")
        return True

    except Exception as e:
        logger.exception(f"[utils.py] Failed to send verification email to {email}: {e}")
        return False
