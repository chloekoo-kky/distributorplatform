# distributorplatform/app/user/models.py
import uuid
from django.db import models
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from phonenumber_field.modelfields import PhoneNumberField


class UserGroup(models.Model):
    name = models.CharField(max_length=100, unique=True, help_text="e.g., 'Agent Tiers', 'Customer Types'")
    product_categories = models.ManyToManyField('product.Category', blank=True, related_name="user_groups")
    is_default = models.BooleanField(default=False, help_text="Set this as the default group for new users.")

    # --- START ADDITION ---
    commission_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        help_text="The percentage of the *profit* this group earns as commission (e.g., 50.00 for 50%)."
    )
    # --- END ADDITION ---
    
    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.is_default:
            # Unset other default groups
            UserGroup.objects.filter(is_default=True).update(is_default=False)
        super(UserGroup, self).save(*args, **kwargs)

class CustomUser(AbstractUser):
    # Enforce a unique email address for each user
    email = models.EmailField(unique=True, blank=False)
    bio = models.TextField(max_length=500, blank=True)
    phone_number = PhoneNumberField(blank=False, null=False)
    user_groups = models.ManyToManyField(UserGroup, blank=True, related_name="users")

    # We only need to know if they are verified or not
    is_verified = models.BooleanField(default=False)

    groups = models.ManyToManyField('auth.Group', related_name='customuser_set', blank=True)
    user_permissions = models.ManyToManyField('auth.Permission', related_name='customuser_set', blank=True)

    def __str__(self):
        return self.username
