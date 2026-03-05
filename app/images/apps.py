from django.apps import AppConfig


class ImagesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'images'

    def ready(self):
        # Implicitly connect signal handlers decorated with @receiver.
        import images.signals  # noqa
