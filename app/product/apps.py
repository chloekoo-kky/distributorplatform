from django.apps import AppConfig


class ProductConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'product'

    # --- START ADDITION ---
    def ready(self):
        # This imports the signals so they are registered
        import product.signals
    # --- END ADDITION ---
