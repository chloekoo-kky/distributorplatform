# distributorplatform/app/images/admin.py
from django.contrib import admin
from .models import MediaImage, ImageCategory

@admin.register(ImageCategory)
class ImageCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}

@admin.register(MediaImage)
class MediaImageAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'category', 'image', 'uploaded_at')
    list_filter = ('category',)
    search_fields = ('title',)
