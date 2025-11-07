# distributorplatform/app/product/models.py
from django.db import models

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

        # Find the most recent quotation item for this product
        # We order by the quotation's date
        latest_item = QuotationItem.objects.filter(
            product=self
        ).order_by('-quotation__date_quoted').first()

        if latest_item:
            # Use the new property from QuotationItem
            return latest_item.landed_cost_per_unit

        return None # Return None if no quotation has been logged
    # --- END MODIFIED PROPERTY ---

    def __str__(self):
        return self.name
