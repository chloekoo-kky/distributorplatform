# distributorplatform/app/seo/models.py
from django.db import models

class PageMetadata(models.Model):
    page_name = models.CharField(max_length=100, unique=True, help_text="A unique name for this page, e.g., 'Home Page', 'Product List Page'.")
    page_path = models.CharField(max_length=255, unique=True, help_text="The exact path, e.g., '/', '/products/', '/blog/'.")
    meta_title = models.CharField(max_length=255, help_text="The title tag for the page (60 chars).")
    meta_description = models.CharField(max_length=160, help_text="The meta description for the page (160 chars).")

    class Meta:
        ordering = ['page_path']

    def __str__(self):
        return f"{self.page_name} ({self.page_path})"
