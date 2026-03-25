"""
Find occurrences of a media URL/path inside Text/HTML fields stored in the DB.

This helps when file extensions changed (e.g. jcain.jpg -> jcain.webp) but
TinyMCE/prose content still contains the old URL and keeps triggering 404s.

Example:
  python manage.py find_media_url_references --term 'blog_gallery/jcain.jpg'
  python manage.py find_media_url_references --term '/media/blog_gallery/jcain.jpg'
"""

import os

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import models


class Command(BaseCommand):
    help = "Search DB text/HTML fields for a media URL/path substring."

    def add_arguments(self, parser):
        parser.add_argument(
            "--term",
            required=True,
            help="Substring to search for (e.g. blog_gallery/jcain.jpg or /media/blog_gallery/jcain.jpg).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Max number of rows to print per model/field.",
        )

    def handle(self, *args, **options):
        term = options["term"]
        limit = options["limit"]

        # Basic escaping: keep it simple; icontains handles wildcards.
        term = (term or "").strip()
        if not term:
            self.stdout.write(self.style.WARNING("Empty --term provided; exiting."))
            return

        results = []

        # Search common text containers: TextField, CharField.
        text_field_types = (models.TextField, models.CharField)

        for model in apps.get_models():
            # Skip models without a table / manager
            try:
                qs = model._default_manager.all()
            except Exception:
                continue

            field_candidates = []
            for f in model._meta.get_fields():
                if isinstance(f, text_field_types):
                    field_candidates.append(f.name)

            if not field_candidates:
                continue

            for field_name in field_candidates:
                try:
                    matches_qs = (
                        qs.filter(**{f"{field_name}__icontains": term})
                        .only("pk", field_name)
                        .order_by("pk")
                    )
                except Exception:
                    continue

                count = 0
                for obj in matches_qs[:limit]:
                    count += 1
                    value = getattr(obj, field_name, "") or ""
                    # print a small excerpt around the term for fast human scan
                    idx = value.lower().find(term.lower())
                    excerpt = value[idx : idx + 120] if idx >= 0 else value[:120]
                    results.append(
                        {
                            "model": f"{model._meta.app_label}.{model.__name__}",
                            "pk": obj.pk,
                            "field": field_name,
                            "excerpt": excerpt.replace("\n", " "),
                        }
                    )

                if count:
                    self.stdout.write(
                        f"Found {count} match(es) in {model._meta.app_label}.{model.__name__}.{field_name}"
                    )

        if not results:
            self.stdout.write(self.style.SUCCESS("No DB text/HTML references found for that term."))
            return

        self.stdout.write("\n--- Sample results ---")
        for r in results[:200]:
            self.stdout.write(f"- {r['model']} pk={r['pk']} field={r['field']} excerpt={r['excerpt']}")

