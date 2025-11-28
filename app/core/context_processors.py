# distributorplatform/app/core/context_processors.py
from .models import SiteSetting, ProductFeature
from blog.models import Post

def site_settings_context(request):
    """
    Returns the singleton SiteSetting object, global footer links, and main menu links.
    """
    try:
        # Get the first object, or create one if it doesn't exist
        settings_obj = SiteSetting.objects.first()
        if not settings_obj:
            settings_obj = SiteSetting.objects.create(site_name="Distributor Platform")
    except Exception:
        settings_obj = None

    # Fetch Footer Links
    try:
        footer_quick_links = Post.objects.filter(
            post_type=Post.PostType.FOOTER_LINK,
            status=Post.PostStatus.PUBLISHED
        ).order_by('title')
    except Exception:
        footer_quick_links = []

    # --- NEW: Fetch Main Menu Links ---
    try:
        main_menu_links = Post.objects.filter(
            post_type=Post.PostType.MAIN_MENU,
            status=Post.PostStatus.PUBLISHED
        ).order_by('created_at')
    except Exception:
        main_menu_links = []

    try:
        global_product_features = ProductFeature.objects.all().order_by('order')
    except Exception:
        global_product_features = []

    return {
        'site_settings': settings_obj,
        'footer_quick_links': footer_quick_links,
        'main_menu_links': main_menu_links,
        'global_product_features': global_product_features,
    }
