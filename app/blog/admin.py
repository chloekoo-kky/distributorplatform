# distributorplatform/app/blog/admin.py
from django.contrib import admin
from .models import Post


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'author', 'created_at')
    search_fields = ('title', 'content')
    list_filter = ('status', 'author')
    # --- START MODIFICATION ---
    filter_horizontal = ('user_groups', 'gallery_images',) # <-- Added gallery_images
    # --- END MODIFICATION ---
