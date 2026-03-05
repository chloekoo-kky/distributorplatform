# distributorplatform/app/images/admin.py
from django.contrib import admin, messages
from django.urls import path
from django.apps import apps
from django.conf import settings
from django.db.models import FileField
from django.shortcuts import render, redirect

import os

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

    change_list_template = "admin/images/mediaimage/change_list.html"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'orphan-images/',
                self.admin_site.admin_view(self.orphan_images_view),
                name='images_mediaimage_orphans',
            ),
        ]
        return custom_urls + urls

    def orphan_images_view(self, request):
        """
        Admin view to find and optionally delete orphan files under MEDIA_ROOT.
        An orphan file is a file present on disk but not referenced by any
        FileField / ImageField across all installed models.
        """
        context = self.admin_site.each_context(request)

        # --- Step A: Collect all referenced (valid) file paths from DB ---
        valid_files = set()

        for model in apps.get_models():
            # We only care about concrete models with database tables
            try:
                fields = [
                    f for f in model._meta.get_fields()
                    if isinstance(getattr(f, 'remote_field', None), type(None)) and isinstance(getattr(f, 'attname', ''), str)
                ]
            except Exception:
                fields = model._meta.get_fields()

            file_fields = [f for f in fields if isinstance(getattr(f, 'field', f), FileField) or isinstance(f, FileField)]
            if not file_fields:
                continue

            for field in file_fields:
                field_name = getattr(field, 'name', None) or getattr(field, 'attname', None)
                if not field_name:
                    continue
                try:
                    # Only pull non-empty values
                    qs = model._default_manager.exclude(**{f"{field_name}__exact": ''}).exclude(**{f"{field_name}__isnull": True})
                    for value in qs.values_list(field_name, flat=True):
                        if not value:
                            continue
                        rel_path = os.path.normpath(str(value))
                        valid_files.add(rel_path)
                except Exception:
                    # Be defensive: if any model/field query fails, skip it
                    continue

        # --- Step B: Walk MEDIA_ROOT and collect all physical files ---
        physical_files = set()
        media_root = getattr(settings, 'MEDIA_ROOT', None)
        if media_root and os.path.isdir(media_root):
            for root, dirs, files in os.walk(media_root):
                # Skip hidden directories
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                for fname in files:
                    if fname.startswith('.'):
                        continue
                    full_path = os.path.join(root, fname)
                    rel_path = os.path.relpath(full_path, media_root)
                    rel_path = os.path.normpath(rel_path)
                    physical_files.add(rel_path)

        # --- Step C: Determine orphans (files on disk but not referenced) ---
        orphan_files = sorted(physical_files - valid_files)

        # --- Step D: Handle deletion POST ---
        if request.method == 'POST':
            to_delete = request.POST.getlist('orphan_files')
            deleted_count = 0
            failed = 0

            for rel_path in to_delete:
                safe_rel = os.path.normpath(rel_path).lstrip(os.sep)
                full_path = os.path.join(media_root, safe_rel)

                # Safety: ensure file is still under MEDIA_ROOT
                if not full_path.startswith(os.path.abspath(media_root)):
                    failed += 1
                    continue

                if os.path.isfile(full_path):
                    try:
                        os.remove(full_path)
                        deleted_count += 1
                    except OSError:
                        failed += 1

            if deleted_count:
                messages.success(request, f"Deleted {deleted_count} orphan file(s).")
            if failed:
                messages.warning(request, f"Failed to delete {failed} file(s). Check server logs or permissions.")

            return redirect('admin:images_mediaimage_orphans')

        context.update({
            'title': "Orphan Images Cleaner",
            'orphan_files': orphan_files,
            'media_url': getattr(settings, 'MEDIA_URL', '/media/'),
        })
        return render(request, 'admin/images/mediaimage/orphan_images.html', context)
