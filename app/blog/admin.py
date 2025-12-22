# distributorplatform/app/blog/admin.py
from django.contrib import admin
from .models import Post

@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    # Add 'order' and 'post_type' to the list display
    list_display = ('title', 'post_type', 'status', 'order', 'created_at')

    # Add 'order' to list_editable so you can change numbers directly in the list
    list_editable = ('order', 'status')

    list_filter = ('post_type', 'status', 'author')
    search_fields = ('title', 'content')
    filter_horizontal = ('user_groups', 'gallery_images',)
