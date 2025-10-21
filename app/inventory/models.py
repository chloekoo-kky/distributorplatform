from django.db import models
from product.models import Product  # Import the Product model from your sales app

class Supplier(models.Model):
    name = models.CharField(max_length=255, unique=True)
    contact_person = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return self.name

class Quotation(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='quotations')
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='quotations')
    quoted_price = models.DecimalField(max_digits=10, decimal_places=2)
    date_quoted = models.DateField()
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"Quote for {self.product.name} from {self.supplier.name} at ${self.quoted_price}"

class InventoryBatch(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='batches')
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True)
    batch_number = models.CharField(max_length=100, unique=True, help_text="A unique number for this batch, e.g., PO-123")
    quantity = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, help_text="The cost per single item from the supplier")
    transportation_fees = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    other_costs = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    received_date = models.DateField()

    # You can link a batch to the quotation it was based on
    quotation = models.ForeignKey(Quotation, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name_plural = "Inventory Batches"

    @property
    def total_cost(self):
        """Calculates the total cost for the entire batch."""
        # ADD THIS CHECK: Only calculate if the required fields have values.
        if self.quantity is not None and self.unit_cost is not None:
            return (self.quantity * self.unit_cost) + self.transportation_fees + self.other_costs
        return 0  # Return 0 or another default value if fields are empty

    @property
    def landed_cost_per_unit(self):
        """Calculates the true cost of a single item after all fees."""
        # ADD THIS CHECK: Ensure quantity is not None and greater than 0.
        if self.quantity and self.quantity > 0 and self.unit_cost is not None:
            return self.total_cost / self.quantity
        return 0

    def __str__(self):
        return f"Batch {self.batch_number} for {self.product.name}"
