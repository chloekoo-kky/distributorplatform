# distributorplatform/app/blog/signals.py
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Post
from seo.models import PageMetadata

@receiver(post_save, sender=Post)
def create_or_update_seo_for_post(sender, instance, created, **kwargs):
    """
    Automatically create or update a PageMetadata object
    when a Post is created or updated.
    """
    if not instance.slug:
        return # Don't do anything if slug isn't set

    page_path = instance.get_absolute_url()

    # Use update_or_create to handle both new and existing posts
    # This ensures if you change a post's title, the SEO tab reflects it.
    PageMetadata.objects.update_or_create(
        page_path=page_path,
        defaults={
            'page_name': f"Blog: {instance.title}",
            'meta_title': instance.title, # A sensible default
            'meta_description': "", # Prompt user to fill this in
        }
    )

@receiver(post_delete, sender=Post)
def delete_seo_for_post(sender, instance, **kwargs):
    """
    Automatically delete the PageMetadata object
    when a Post is deleted.
    """
    try:
        page_path = instance.get_absolute_url()
        if page_path:
            PageMetadata.objects.filter(page_path=page_path).delete()
    except Exception:
        # Fail silently if post had no slug or something went wrong
        pass
