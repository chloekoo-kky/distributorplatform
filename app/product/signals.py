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
    """
    if not instance.sku:
        return # Don't do anything if sku isn't set

    try:
        page_path = instance.get_absolute_url()
    except Exception:
        return # Fail silently if URL reversing fails

    # Use update_or_create to handle both new and existing products
    PageMetadata.objects.update_or_create(
        page_path=page_path,
        defaults={
            'page_name': f"Product: {instance.name}",
            'meta_title': instance.name, # A sensible default
            'meta_description': instance.description[:160] if instance.description else "", # Use product description
        }
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
