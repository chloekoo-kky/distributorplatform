# distributorplatform/app/blog/models.py
from django.db import models
from django.conf import settings
from django.utils.text import slugify
from django.urls import reverse
from user.models import UserGroup
from tinymce.models import HTMLField


class Post(models.Model):
    class PostStatus(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        PUBLISHED = 'PUBLISHED', 'Published'

    # --- NEW: Content Type Choices ---
    class PostType(models.TextChoices):
        NEWS = 'NEWS', 'Latest News'
        ANNOUNCEMENT = 'ANNOUNCEMENT', 'Announcement'
        FAQ = 'FAQ', 'FAQ / Help'
        FOOTER_LINK = 'FOOTER_LINK', 'Footer Quick Link'
        MAIN_MENU = 'MAIN_MENU', 'Main Menu Link'

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, blank=True, help_text="A unique URL-friendly path. Leave blank to auto-generate from title.")
    content = HTMLField(blank=True, null=True)

    # --- NEW: Post Type Field ---
    post_type = models.CharField(
        max_length=20,
        choices=PostType.choices,
        default=PostType.NEWS,
        help_text="Define where this content belongs (e.g., Sidebar News, Announcement banner, etc.)"
    )

    # This field should already be a ForeignKey
    featured_image = models.ForeignKey(
        'images.MediaImage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='featured_in_posts'
    )

    related_products_title = models.CharField(
        max_length=255,
        default="Related Products",
        blank=True,
        help_text="Title to display above the related products section (e.g., 'Recommended for You')."
    )

    related_products_title = models.CharField(
        max_length=255,
        default="Related Products",
        blank=True,
        help_text="Title to display above the related products section (e.g., 'Recommended for You')."
    )

    related_products = models.ManyToManyField(
        'product.Product',
        blank=True,
        related_name='related_posts',
        help_text="Select products to display as related items on this post."
    )

    gallery_images = models.ManyToManyField(
        'images.MediaImage',
        blank=True,
        related_name="post_galleries"
    )

    status = models.CharField(max_length=10, choices=PostStatus.choices, default=PostStatus.DRAFT)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='blog_posts'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    user_groups = models.ManyToManyField(
        'user.UserGroup',
        blank=True,
        related_name="blog_posts",
        help_text="Select groups to restrict this post to. Leave blank for a public post."
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('blog:post_detail', kwargs={'slug': self.slug})

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
            original_slug = self.slug
            counter = 1
            while Post.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
                self.slug = f'{original_slug}-{counter}'
                counter += 1

        super().save(*args, **kwargs)

    @property
    def is_public(self):
        return self.user_groups.count() == 0
