# distributorplatform/app/images/models.py
from django.db import models
from django.utils.text import slugify

class ImageCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['name']
        verbose_name = "Image Category"
        verbose_name_plural = "Image Categories"
        db_table = 'blog_imagecategory' # <-- IMPORTANT: Use old table name

class MediaImage(models.Model):
    title = models.CharField(max_length=200, help_text="e.g., 'Red Scarf Product Shot'")
    image = models.ImageField(upload_to='blog_gallery/')
    alt_text = models.CharField(max_length=255, blank=True, help_text="Accessibility text for screen readers.")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    category = models.ForeignKey(
        ImageCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="images"
    )

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['-uploaded_at']
        db_table = 'blog_mediaimage' # <-- IMPORTANT: Use old table name
