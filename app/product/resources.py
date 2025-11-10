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
        fields = ('id', 'code', 'name', 'group')
        export_order = ('id', 'code', 'name', 'group')
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

    class Meta:
        model = Product
        import_id_fields = ['sku']
        fields = ('id', 'sku', 'name', 'description', 'members_only', 'categories', 'suppliers', 'base_cost', 'selling_price', 'profit_margin')
        export_order = ('id', 'sku', 'name', 'description', 'members_only', 'categories', 'suppliers', 'base_cost', 'selling_price', 'profit_margin', 'created_at')
        skip_unchanged = True
        report_skipped = True
