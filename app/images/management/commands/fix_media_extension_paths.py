"""
Fix DB file paths when the physical file exists under a different image extension.

Example: database has blog_gallery/jcain.jpg but disk has blog_gallery/jcain.webp
after a historical WEBP migration — updates the model to the path that exists.

Usage:
  python manage.py fix_media_extension_paths
  python manage.py fix_media_extension_paths --apply
"""

import os

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db.models import FileField

ALTERNATE_EXTENSIONS = (
    '.webp', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif',
)


class Command(BaseCommand):
    help = (
        'For FileField/ImageField values that are missing on storage, try the same '
        'basename with other image extensions and update the DB if a match exists.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Write fixes to the database (without this flag, only print what would change).',
        )

    def handle(self, *args, **options):
        apply_fixes = options['apply']
        found_count = 0
        fixed_count = 0

        for model in apps.get_models():
            file_fields = [f for f in model._meta.get_fields() if isinstance(f, FileField)]
            if not file_fields:
                continue

            for field in file_fields:
                field_name = field.name
                try:
                    qs = (
                        model._default_manager
                        .exclude(**{f'{field_name}__exact': ''})
                        .exclude(**{f'{field_name}__isnull': True})
                    )
                except Exception:
                    continue

                for obj in qs.iterator(chunk_size=500):
                    file_obj = getattr(obj, field_name, None)
                    if not file_obj or not file_obj.name:
                        continue
                    storage = file_obj.storage
                    name = file_obj.name
                    if storage.exists(name):
                        continue

                    base, ext = os.path.splitext(name)
                    ext_lower = ext.lower()
                    candidate = None
                    for alt in ALTERNATE_EXTENSIONS:
                        if alt == ext_lower:
                            continue
                        trial = base + alt
                        try:
                            if storage.exists(trial):
                                candidate = trial
                                break
                        except Exception:
                            continue

                    if not candidate:
                        continue

                    found_count += 1
                    model_label = f'{model._meta.app_label}.{model.__name__}'
                    self.stdout.write(
                        f'[{model_label}] pk={obj.pk} {field_name}: '
                        f'{name!r} -> {candidate!r}'
                    )

                    if apply_fixes:
                        file_obj.name = candidate
                        obj.save(update_fields=[field_name])
                        fixed_count += 1

        if not apply_fixes and found_count:
            self.stdout.write(
                self.style.WARNING(
                    f'Dry-run only. {found_count} path(s) could be fixed. '
                    'Re-run with --apply to update the database.'
                )
            )
        elif apply_fixes:
            self.stdout.write(
                self.style.SUCCESS(f'Updated {fixed_count} row(s).')
            )
        else:
            self.stdout.write(self.style.SUCCESS('No mismatched paths found.'))
