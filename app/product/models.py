# distributorplatform/app/product/models.py
from django.db import models
from django.urls import reverse
from tinymce.models import HTMLField
from decimal import Decimal

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
    display_order = models.PositiveIntegerField(
        default=0,
        help_text="Order of display in navigation menus (lowest number appears first. )"
    )

    description = HTMLField(
        blank=True,
        null=True,
        help_text="Description text displayed on the product list page when this category is selected."
    )

    page_title = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Custom title to display on the product list page (overrides the category name)."
    )

    class Meta:
        unique_together = ('name', 'group')
        verbose_name_plural = "Categories"
        ordering = ['display_order', 'name']

    def __str__(self):
        return f"{self.group.name} - {self.name}"

    @property
    def display_name_lines(self):
        """
        Splits the category name by '|' to support dual-language display.
        Example: "Shoes | 鞋子" -> ["Shoes", "鞋子"]
        """
        if '|' in self.name:
            return [line.strip() for line in self.name.split('|')]
        return [self.name]

    # --- MOVED HERE FROM CategoryContentSection ---
    @property
    def display_title_lines(self):
        """
        Returns the lines for the Page Title if set, otherwise falls back to Name.
        Supports 'Title | Subtitle' format.
        """
        # Prioritize page_title, fallback to name
        text = self.page_title if self.page_title else self.name

        if text and '|' in text:
            return [line.strip() for line in text.split('|')]
        return [text] if text else []

# --- NEW MODEL: CategoryContentSection ---
class CategoryContentSection(models.Model):
    category = models.ForeignKey(Category, related_name='content_sections', on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    content = HTMLField()
    order = models.PositiveIntegerField(default=0)

    @property
    def display_name_lines(self):
        """Splits the section title by '|'."""
        if '|' in self.title:
            return [line.strip() for line in self.title.split('|')]
        return [self.title]

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.title} for {self.category.name}"


class Product(models.Model):
    name = models.CharField(max_length=200)
    alias_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional short or alternate name for manual orders and internal copy (e.g. platform listing title). Searched alongside product name.",
    )
    sku = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Stock Keeping Unit"
    )
    description_title = models.CharField(
        max_length=255,
        default="Product Description",
        blank=True,
        help_text="Header for the main description section."
    )
    description = HTMLField(null=True, blank=True)

    origin_country = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Country of origin for the product (e.g., 'Malaysia', 'Korea')."
    )

    is_promotion = models.BooleanField(
        default=False,
        help_text="Check if this product is currently on promotion (triggers promotional styling)."
    )
    promotion_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="The rate/percentage defined for this promotion."
    )
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
    saved_base_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="User-selected base cost (from a specific supplier quote). Used for pricing; shown in Set Product Pricing modal."
    )
    saved_base_cost_supplier = models.ForeignKey(
        'inventory.Supplier',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        help_text="Supplier tied to saved_base_cost so cost stays in sync when that supplier's quotation changes.",
    )
    members_only = models.BooleanField(default=False)
    is_featured = models.BooleanField(
        default=False,
        help_text="If checked, this product will appear on the Home page (subject to user permissions)."
    )
    is_best_seller = models.BooleanField(
        default=False,
        help_text="If checked, this product will be highlighted as a Best Seller."
    )
    display_order = models.IntegerField(
        default=0,
        help_text="Order of display on the product list page (lowest number appears first)."
    )
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
        'inventory.Supplier',
        related_name='products',
        blank=True,
        help_text="Suppliers who provide this product."
    )

    class Meta:
        # --- UPDATE ORDERING ---
        # Sort by display_order first (ascending), then by creation date (newest first)
        ordering = ['display_order', '-created_at']
        # -----------------------

    def __str__(self):
        return self.name

    @property
    def order_display_name(self) -> str:
        """Label for orders, WhatsApp summaries, and copy: alias if set, otherwise full product name."""
        alias = (self.alias_name or '').strip()
        if alias:
            return alias
        return (self.name or '').strip()

    @property
    def name_lines(self):
        """
        Splits the product name by '|' for dual-language display.
        Example: "Nike Air | 耐克气垫" -> ["Nike Air", "耐克气垫"]
        """
        if self.name and '|' in self.name:
            return [line.strip() for line in self.name.split('|')]
        return [self.name]

    @property
    def discounted_price(self):
        """
        Calculates the price after applying the promotion rate.
        Returns the original selling_price if no promotion is active.
        """
        if self.is_promotion and self.promotion_rate and self.selling_price:
            discount_multiplier = Decimal('1.00') - (self.promotion_rate / Decimal('100.00'))
            return self.selling_price * discount_multiplier
        return self.selling_price

    @property
    def base_cost(self):
        """
        Base cost used for pricing. If the user has chosen a source in Set Product
        Pricing (saved_base_cost), that value is returned. Otherwise the latest
        landed cost from the most recent Quotation Item is used.
        """
        if self.saved_base_cost is not None:
            return self.saved_base_cost

        # Import here to avoid circular dependency
        from inventory.models import QuotationItem

        # Check if data was prefetched by an API view
        if hasattr(self, 'latest_quotation_items'):
            # This attribute is created by the Prefetch in the API views
            latest_item = self.latest_quotation_items[0] if self.latest_quotation_items else None
        else:
            latest_item = QuotationItem.objects.filter(
                product=self
            ).select_related('quotation').prefetch_related('quotation__items').order_by('-quotation__date_quoted').first()

        if latest_item:
            return latest_item.landed_cost_per_unit

        return None

    def get_absolute_url(self):
        """
        Returns the public URL for the product.
        """
        # Note: This requires a product_detail view and URL pattern
        if self.sku:
            return reverse('product:product_detail', kwargs={'sku': self.sku})
        return reverse('product:product_list') # Fallback

    def get_price_for_quantity(self, quantity):
        """
        Returns the selling price per unit for the given quantity.
        If the product has price tiers, returns the best matching tier price
        (highest min_quantity that is <= quantity). Otherwise returns selling_price.
        """
        if quantity is None or quantity < 1:
            return self.selling_price
        tiers = getattr(self, '_price_tiers_cache', None)
        if tiers is None:
            tiers = list(self.price_tiers.order_by('-min_quantity'))
            self._price_tiers_cache = tiers
        for tier in tiers:
            if quantity >= tier.min_quantity:
                return tier.price
        return self.selling_price

    def __str__(self):
        return self.name


class ProductPriceTier(models.Model):
    """
    Tiered pricing: minimum order quantity triggers a lower selling price.
    E.g. min_quantity=10, price=9.00 means "order 10+ units at RM 9 each".
    Tiers are evaluated by highest min_quantity first (order by min_quantity desc).
    """
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='price_tiers'
    )
    min_quantity = models.PositiveIntegerField(
        help_text="Minimum order quantity to get this price (e.g. 10 for '10+ units')."
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Selling price per unit when order quantity meets min_quantity."
    )

    class Meta:
        ordering = ['-min_quantity']
        unique_together = [('product', 'min_quantity')]
        verbose_name = "Price tier"
        verbose_name_plural = "Price tiers"

    def __str__(self):
        return f"{self.product.name}: {self.min_quantity}+ @ RM {self.price}"


class ProductContentSection(models.Model):
    product = models.ForeignKey(Product, related_name='content_sections', on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    content = models.TextField()
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.title} for {self.product.name}"


class IgnoredMergeSuggestion(models.Model):
    """
    Stores product ID combinations that the user has dismissed as "Not duplicates".
    Used by the Duplicate Checklist to hide suggestions that exactly match a dismissed set.
    If a new product is added and the algorithm suggests a group that includes it,
    the group has a different composition so it will reappear.
    """
    product_ids_signature = models.CharField(
        max_length=500,
        unique=True,
        help_text="Sorted comma-separated product IDs, e.g. '12,34,56'. Used to match and exclude dismissed groups."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ignored merge suggestion"
        verbose_name_plural = "Ignored merge suggestions"

    def __str__(self):
        return f"Dismissed: {self.product_ids_signature}"
