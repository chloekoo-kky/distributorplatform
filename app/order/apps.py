# distributorplatform/app/order/apps.py
from django.apps import AppConfig

class OrderConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'order'

    # --- START ADDITION ---
    def ready(self):
        import order.signals  # This imports and registers your signals
    # --- END ADDITION ---
