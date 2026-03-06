# distributorplatform/app/product/signals.py
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Product
from seo.models import PageMetadata
from django.utils.text import slugify

@receiver(post_save, sender=Product)
def create_or_update_seo_for_product(sender, instance, created, **kwargs):
    """
    Automatically create or update a PageMetadata object
    when a Product is created or updated.
    Uses page_path as the lookup key so we never violate the unique constraint
    on page_path (e.g. when an old row already has that path but a different page_name).
    """
    if not instance.sku:
        return  # Don't do anything if sku isn't set

    try:
        page_path = instance.get_absolute_url()
    except Exception:
        return  # Fail silently if URL reversing fails

    page_name_by_sku = f"Product: {instance.sku}"
    meta_desc = (instance.description[:160] if instance.description else "") or ""

    # Look up by page_path (unique). If a row already exists for this path (e.g. from
    # a previous product or renamed SKU), we update it instead of inserting a duplicate.
    PageMetadata.objects.update_or_create(
        page_path=page_path,
        defaults={
            "page_name": page_name_by_sku,
            "meta_title": instance.name or page_name_by_sku,
            "meta_description": meta_desc,
        },
    )

@receiver(post_delete, sender=Product)
def delete_seo_for_product(sender, instance, **kwargs):
    """
    Automatically delete the PageMetadata object
    when a Product is deleted.
    """
    try:
        page_path = instance.get_absolute_url()
        if page_path:
            PageMetadata.objects.filter(page_path=page_path).delete()
    except Exception:
        # Fail silently
        pass
