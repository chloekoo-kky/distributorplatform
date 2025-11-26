# distributorplatform/app/core/models.py
from django.db import models

class SiteSetting(models.Model):
    site_name = models.CharField(max_length=100, default="Distributor Platform")

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
