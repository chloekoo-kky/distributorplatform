# distributorplatform/app/core/models.py
from django.db import models

class SiteSetting(models.Model):
    site_name = models.CharField(max_length=100, default="Distributor Platform")
    site_logo = models.ImageField(
        upload_to='site_branding/',
        blank=True,
        null=True,
        help_text="Upload a logo to display next to the site name in the navigation bar."
    )
    nav_background_color = models.CharField(
        max_length=7,
        default="#FFFFFF",
        help_text="Select the background color for the top navigation bar."
    )
    # Contact Info
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=50, blank=True)
    contact_address = models.TextField(blank=True, help_text="Physical address displayed in footer.")

    # Footer Content
    footer_about_text = models.TextField(
        blank=True,
        help_text="A short paragraph about your company displayed in the footer."
    )

    # Social Media
    facebook_url = models.URLField(blank=True, verbose_name="Facebook URL")
    instagram_url = models.URLField(blank=True, verbose_name="Instagram URL")
    twitter_url = models.URLField(blank=True, verbose_name="Twitter/X URL")
    linkedin_url = models.URLField(blank=True, verbose_name="LinkedIn URL")

    def save(self, *args, **kwargs):
        # Ensure only one instance exists (Singleton pattern)
        if not self.pk and SiteSetting.objects.exists():
            # If you try to create a new one, it updates the existing one instead
            existing = SiteSetting.objects.first()
            return existing
        return super(SiteSetting, self).save(*args, **kwargs)

    def __str__(self):
        return "Site Configuration"

    class Meta:
        verbose_name = "Site Configuration"
        verbose_name_plural = "Site Configuration"

class ProductFeature(models.Model):
    title = models.CharField(max_length=50, help_text="Top line (e.g., 'Free Shipping')")
    subtitle = models.CharField(max_length=50, blank=True, help_text="Bottom line (e.g., 'Orders over $100')")
    order = models.PositiveIntegerField(default=0, help_text="Order of display (1-4 recommended)")

    class Meta:
        ordering = ['order']
        verbose_name = "Global Product Feature"

    def __str__(self):
        return self.title
