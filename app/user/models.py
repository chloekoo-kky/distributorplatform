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

class SubscriptionPlan(models.Model):
    name = models.CharField(max_length=100, help_text="Use '|' to split languages (e.g., 'Gold Plan | 金牌套餐')")
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    description = models.TextField(blank=True, help_text="Use '|' to split languages.")

    target_group = models.ForeignKey(
        UserGroup,
        on_delete=models.PROTECT,
        related_name='subscription_plans'
    )

    # Store features as a list of strings, e.g., ["Priority Support | 优先支持", "Free Shipping | 免运费"]
    features = models.JSONField(default=list, blank=True)

    is_active = models.BooleanField(default=True)
    is_popular = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'price']

    def __str__(self):
        return self.name

    # --- NEW: Helper Methods for 2-Line Display ---
    def _get_lines(self, text):
        """Helper to split text by pipe '|' symbol."""
        if text and '|' in text:
            return [line.strip() for line in text.split('|')]
        return [text] if text else []

    @property
    def name_lines(self):
        return self._get_lines(self.name)

    @property
    def description_lines(self):
        return self._get_lines(self.description)

    @property
    def features_lines_list(self):
        """
        Returns a list of lists.
        Example: [['Feature 1', '功能 1'], ['Feature 2', '功能 2']]
        """
        if not self.features:
            return []
        return [self._get_lines(feature) for feature in self.features]

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


class SubscriptionPayment(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('FAILED', 'Failed'),
    )

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference_id = models.CharField(max_length=100, unique=True, help_text="Gateway Transaction ID")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.plan.name} - {self.status}"
