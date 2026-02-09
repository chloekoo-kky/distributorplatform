import logging
from import_export import resources, fields
from import_export.widgets import BooleanWidget, ManyToManyWidget, ForeignKeyWidget
from .models import Product, Category, CategoryGroup
from inventory.models import Supplier

# --- SETUP LOGGER ---
logger = logging.getLogger(__name__)

class DualLanguageManyToManyWidget(ManyToManyWidget):
    """
    Extends ManyToManyWidget to:
    1. EXPORT: Return only the English part (ASCII) to prevent encoding errors.
    2. IMPORT: Robustly match categories by English name or Full name.
    3. SAFETY: Handles None values to prevent 'NoneType' object has no attribute 'all' crashes.
    """

    def render(self, value, obj=None):
        """
        Export logic:
        Takes the list of categories and returns only the English part.
        Includes safety check for None values.
        """
        # --- FIX: Safety Check for None ---
        if value is None:
            return ""
        # ----------------------------------

        # Handle case where value might be a list (from clean) instead of Manager
        if isinstance(value, list):
            ids = [item.pk for item in value]
        else:
            # Assume it's a Manager or QuerySet
            try:
                ids = [related.pk for related in value.all()]
            except (AttributeError, ValueError):
                # Fallback for edge cases (e.g. unsaved instance)
                return ""

        objects = self.model.objects.filter(pk__in=ids)

        names = []
        for o in objects:
            original_name = getattr(o, self.field)
            final_name = original_name.strip()

            if '|' in original_name:
                parts = [p.strip() for p in original_name.split('|')]

                # Loop through parts and find the first one that is ASCII (English)
                english_part = None
                for p in parts:
                    if all(ord(c) < 128 for c in p):
                        english_part = p
                        break

                if english_part:
                    final_name = english_part
                else:
                    final_name = parts[0]

            names.append(final_name)

        return self.separator.join(names)

    def clean(self, value, row=None, *args, **kwargs):
        """
        Import logic:
        Accepts "Skin Care" or "Skin Care | 护肤" and finds the correct category.
        """
        if not value:
            return self.model.objects.none()

        if isinstance(value, str):
            value = value.replace('，', ',')

        raw_values = [v.strip() for v in value.split(self.separator) if v.strip()]

        found_objects = []
        for raw_val in raw_values:
            # 1. Try Exact Match
            obj = self.model.objects.filter(**{self.field: raw_val}).first()

            # 2. Try StartsWith
            if not obj:
                obj = self.model.objects.filter(**{f"{self.field}__istartswith": raw_val}).first()

            # 3. Try Contains (fallback)
            if not obj:
                 obj = self.model.objects.filter(**{f"{self.field}__icontains": raw_val}).first()

            if obj:
                found_objects.append(obj)
            else:
                logger.warning(f"[IMPORT DEBUG] Could not find match for: '{raw_val}'")

        return found_objects


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
        widget=ForeignKeyWidget(CategoryGroup, field='name')
    )
    class Meta:
        model = Category
        import_id_fields = ['code']
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
        readonly=True,
    )

    # --- UPDATED: Use DualLanguageManyToManyWidget ---
    categories = fields.Field(
        column_name='categories',
        attribute='categories',
        widget=DualLanguageManyToManyWidget(Category, field='name', separator=',')
    )
    suppliers = fields.Field(
        column_name='suppliers',
        attribute='suppliers',
        widget=DualLanguageManyToManyWidget(Supplier, field='name', separator=',')
    )
    # -------------------------------------------------

    def dehydrate_base_cost(self, product):
        cost = product.base_cost
        return cost if cost is not None else None

    def before_import_row(self, row, **kwargs):
        """
        Clean data before looking up or importing the instance.
        """
        if 'sku' in row:
            sku_val = row['sku']
            if sku_val == '' or (isinstance(sku_val, str) and not sku_val.strip()):
                row['sku'] = None

    class Meta:
        model = Product
        import_id_fields = ['id']

        fields = (
            'id', 'sku', 'name', 'description', 'origin_country',
            'members_only', 'categories', 'suppliers',
            'base_cost', 'selling_price', 'profit_margin'
        )
        export_order = (
            'id', 'sku', 'name', 'description', 'origin_country',
            'members_only', 'categories', 'suppliers',
            'base_cost', 'selling_price', 'profit_margin', 'created_at'
        )

        skip_unchanged = True
        report_skipped = True
