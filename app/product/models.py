from django.db import models

class CategoryGroup(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class Category(models.Model):
    name = models.CharField(max_length=100)
    group = models.ForeignKey(CategoryGroup, related_name='categories', on_delete=models.CASCADE)

    class Meta:
        unique_together = ('name', 'group')
        verbose_name_plural = "Categories"

    def __str__(self):
        return f"{self.group.name} - {self.name}"


class Product(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField()
    members_only = models.BooleanField(default=False)
    categories = models.ManyToManyField(Category, related_name='products', blank=True)
    image = models.ImageField(upload_to='product_images/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def base_cost(self):
        """Gets the latest landed cost from the most recent inventory batch."""
        from inventory.models import InventoryBatch # Import here to avoid circular dependency
        latest_batch = InventoryBatch.objects.filter(product=self).order_by('-received_date').first()
        if latest_batch:
            return latest_batch.landed_cost_per_unit
        return None # Return None if no inventory has been logged

    def __str__(self):
        return self.name

