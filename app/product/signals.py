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
    Uses page_name "Product: {sku}" so the same product is always updated
    (avoids duplicate page_name when SKU/path changes).
    """
    if not instance.sku:
        return  # Don't do anything if sku isn't set

    try:
        page_path = instance.get_absolute_url()
    except Exception:
        return  # Fail silently if URL reversing fails

    page_name_by_sku = f"Product: {instance.sku}"
    meta_desc = (instance.description[:160] if instance.description else "") or ""

    # Look up by stable page_name (Product: sku) so when SKU or path changes we update
    # the same row instead of creating a duplicate (page_name is unique).
    PageMetadata.objects.update_or_create(
        page_name=page_name_by_sku,
        defaults={
            "page_path": page_path,
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
