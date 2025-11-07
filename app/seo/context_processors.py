# distributorplatform/app/seo/context_processors.py
from .models import PageMetadata
# --- START MODIFICATION ---
# No longer need to import Post or Http404
# --- END MODIFICATION ---

def seo_tags(request):
    """
    Context processor to load SEO tags for the current page.
    """
    try:
        # --- START MODIFICATION ---
        # This one query now works for static pages AND blog posts!
        metadata = PageMetadata.objects.get(page_path=request.path)
        return {
            'meta_title': metadata.meta_title,
            'meta_description': metadata.meta_description,
        }
        # --- END MODIFICATION ---
    except PageMetadata.DoesNotExist:
        # Fallback to default
        return {
            'meta_title': 'Distributor Platform',
            'meta_description': 'Welcome to our platform for distribution and inventory management.',
        }
    except Exception:
        # Fail safe
        return {
            'meta_title': 'Distributor Platform',
            'meta_description': 'Welcome to our platform.',
        }
