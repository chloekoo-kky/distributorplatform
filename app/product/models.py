# distributorplatform/app/product/models.py
from django.db import models
from django.urls import reverse

class CategoryGroup(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        help_text="A unique code for this group (e.g., 'BRANDS')."
    )

    def __str__(self):
        return self.name

class Category(models.Model):
    name = models.CharField(max_length=100)
    group = models.ForeignKey(CategoryGroup, related_name='categories', on_delete=models.CASCADE)
    code = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        help_text="A unique code for this category (e.g., 'NIKE')."
    )

    class Meta:
        unique_together = ('name', 'group')
        verbose_name_plural = "Categories"

    def __str__(self):
        return f"{self.group.name} - {self.name}"


class Product(models.Model):
    name = models.CharField(max_length=200)
    sku = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Stock Keeping Unit"
    )
    description = models.TextField(null=True, blank=True)
    selling_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="The customer-facing selling price."
    )
    profit_margin = models.DecimalField(
        max_digits=5, # e.g., 999.99%
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Profit margin percentage (e.g., 20.00 for 20%)"
    )
    members_only = models.BooleanField(default=False)
    categories = models.ManyToManyField(Category, related_name='products', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    featured_image = models.ForeignKey(
        'images.MediaImage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='featured_in_products'
    )
    # Added new gallery field
    gallery_images = models.ManyToManyField(
        'images.MediaImage',
        blank=True,
        related_name="product_galleries"
    )
    suppliers = models.ManyToManyField(
        'inventory.Supplier', # <-- Use string 'app_name.ModelName'
        related_name='products',
        blank=True,
        help_text="Suppliers who provide this product."
    )

    @property
    def base_cost(self):
        """
        Gets the latest landed cost from the most recent Quotation Item
        for this product.
        """
        # Import here to avoid circular dependency
        from inventory.models import QuotationItem

        # --- START MODIFICATION ---
        # Check if data was prefetched by an API view
        if hasattr(self, 'latest_quotation_items'):
            # This attribute is created by the Prefetch in the API views
            # We use self.latest_quotation_items[0] if the list is not empty
            latest_item = self.latest_quotation_items[0] if self.latest_quotation_items else None
        else:
            # Original query for non-API use (e.g., templates, admin)
            # We add select_related and prefetch_related here to optimize the standard non-api call
            latest_item = QuotationItem.objects.filter(
                product=self
            ).select_related('quotation').prefetch_related('quotation__items').order_by('-quotation__date_quoted').first()
        # --- END MODIFICATION ---

        if latest_item:
            # Use the new property from QuotationItem
            # This is now efficient because the related 'quotation' and 'quotation.items'
            # were prefetched in either branch.
            return latest_item.landed_cost_per_unit

        return None # Return None if no quotation has been logged
    # --- END MODIFIED PROPERTY ---

    def get_absolute_url(self):
        """
        Returns the public URL for the product.
        """
        # Note: This requires a product_detail view and URL pattern
        if self.sku:
            return reverse('product:product_detail', kwargs={'sku': self.sku})
        return reverse('product:product_list') # Fallback

    def __str__(self):
        return self.name
