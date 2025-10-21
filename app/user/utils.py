# distributorplatform/app/user/utils.py
import random
import logging
from django.conf import settings
from twilio.rest import Client

# Get an instance of a logger
logger = logging.getLogger(__name__)

def generate_verification_code():
    """Generates a random 6-digit code."""
    return str(random.randint(100000, 999999))

def send_verification_code(phone_number, code):
    """
    Sends the verification code to the user's phone number via WhatsApp.

    This uses the 'body' parameter which works with the Twilio Sandbox
    default templates (e.g., "Your verification code is: [CODE]")
    """
    logger.info(f"[utils.py] Attempting to send verification code to {phone_number}")

    if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_WHATSAPP_NUMBER):
        logger.warning("[utils.py] Twilio settings (SID, TOKEN, or NUMBER) are not configured. Skipping WhatsApp message.")
        return False

    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

        whatsapp_to = f"whatsapp:{phone_number.as_e164}"
        whatsapp_from = settings.TWILIO_WHATSAPP_NUMBER
        if not whatsapp_from.startswith('whatsapp:'):
            whatsapp_from = f'whatsapp:{whatsapp_from}'

        message_body = f"Your verification code is: {code}"

        # --- DETAILED LOGGING ---
        logger.info(f"[utils.py] Sending Twilio message with the following details:")
        logger.info(f"[utils.py]   -> TO: {whatsapp_to}")
        logger.info(f"[utils.py]   -> FROM: {whatsapp_from}")
        logger.info(f"[utils.py]   -> BODY: {message_body}")
        # --- END LOGGING ---

        message = client.messages.create(
            body=message_body,
            from_=whatsapp_from,
            to=whatsapp_to
        )

        logger.info(f"[utils.py] Successfully sent message. Twilio Message SID: {message.sid}")
        return True

    except Exception as e:
        logger.error(f"[utils.py] Error sending WhatsApp message: {e}")
        return False
