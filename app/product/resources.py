# distributorplatform/app/product/resources.py
from import_export import resources, fields
from import_export.widgets import BooleanWidget, DecimalWidget, ManyToManyWidget, ForeignKeyWidget
from .models import Product, Category, CategoryGroup
# --- Import Supplier ---
from inventory.models import Supplier

class CategoryGroupResource(resources.ModelResource):
    class Meta:
        model = CategoryGroup
        import_id_fields = ['code']
        fields = ('id', 'code', 'name')
        export_order = ('id', 'code', 'name')
        skip_unchanged = True
        report_skipped = True

class CategoryResource(resources.ModelResource):
    group = fields.Field(
        column_name='group',
        attribute='group',
        widget=ForeignKeyWidget(CategoryGroup, field='name') # Assuming group name is unique
    )
    class Meta:
        model = Category
        import_id_fields = ['code']
        # --- UPDATED: Added 'display_order' ---
        fields = ('id', 'display_order', 'code', 'name', 'group')
        export_order = ('id', 'display_order', 'code', 'name', 'group')
        skip_unchanged = True
        report_skipped = True

class ProductResource(resources.ModelResource):
    members_only = fields.Field(
        column_name='members_only',
        attribute='members_only',
        widget=BooleanWidget()
    )
    base_cost = fields.Field(
        column_name='base_cost',
        readonly=True, # Readonly for import
        # No need for widget=DecimalWidget() here unless custom formatting needed
    )
    categories = fields.Field(
        column_name='categories',
        attribute='categories',
        widget=ManyToManyWidget(Category, field='name', separator=',')
    )
    suppliers = fields.Field(
        column_name='suppliers',
        attribute='suppliers',
        widget=ManyToManyWidget(Supplier, field='name', separator=',')
    )

    def dehydrate_base_cost(self, product):
        # Ensure it returns a value that can be handled (e.g., None or Decimal)
        cost = product.base_cost
        return cost if cost is not None else None # Or return 0.00 if preferred

    # --- NEW METHOD TO CLEAN DATA BEFORE IMPORT ---
    def before_import_row(self, row, **kwargs):
        """
        Clean data before looking up or importing the instance.
        """
        # Convert empty strings in SKU to None (NULL).
        # This prevents unique constraint violations because DBs allow multiple NULLs but only one empty string.
        if 'sku' in row:
            sku_val = row['sku']
            # Check for empty string or string containing only whitespace
            if sku_val == '' or (isinstance(sku_val, str) and not sku_val.strip()):
                row['sku'] = None

    class Meta:
        model = Product
        # --- FIXED: Changed from 'sku' to 'id' to prevent UPDATE crashes on rows with empty SKUs ---
        import_id_fields = ['id']
        fields = ('id', 'sku', 'name', 'description', 'members_only', 'categories', 'suppliers', 'base_cost', 'selling_price', 'profit_margin')
        export_order = ('id', 'sku', 'name', 'description', 'members_only', 'categories', 'suppliers', 'base_cost', 'selling_price', 'profit_margin', 'created_at')
        skip_unchanged = True
        report_skipped = True
