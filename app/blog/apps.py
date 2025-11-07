# distributorplatform/app/blog/apps.py
from django.apps import AppConfig

class BlogConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'blog'

    # --- START MODIFICATION ---
    def ready(self):
        # This imports the signals so they are registered
        import blog.signals
    # --- END MODIFICATION ---
