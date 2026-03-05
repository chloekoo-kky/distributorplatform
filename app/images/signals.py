import os

from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver

from .models import MediaImage


@receiver(post_delete, sender=MediaImage)
def auto_delete_file_on_delete(sender, instance, **kwargs):
    """
    Deletes file from filesystem when corresponding `MediaImage` object is deleted.
    """
    file_field = getattr(instance, "image", None)
    if not file_field:
        return

    file_path = file_field.path if hasattr(file_field, "path") else None
    if file_path and os.path.isfile(file_path):
        try:
            os.remove(file_path)
        except OSError:
            # Fail silently if the file was already removed or is not accessible.
            pass


@receiver(pre_save, sender=MediaImage)
def auto_delete_file_on_change(sender, instance, **kwargs):
    """
    Deletes old file from filesystem when corresponding `MediaImage` object is
    updated with a new file.
    """
    if not instance.pk:
        # New object; nothing to delete yet.
        return

    try:
        old_file = MediaImage.objects.get(pk=instance.pk).image
    except MediaImage.DoesNotExist:
        return

    new_file = getattr(instance, "image", None)

    # If the file has changed, delete the old one from disk.
    if old_file and old_file != new_file:
        old_path = old_file.path if hasattr(old_file, "path") else None
        if old_path and os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError:
                # Fail silently if file cannot be removed.
                pass

