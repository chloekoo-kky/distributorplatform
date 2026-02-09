# distributorplatform/app/product/resources.py
import logging
from import_export import resources, fields
from import_export.widgets import BooleanWidget, ManyToManyWidget, ForeignKeyWidget
from .models import Product, Category, CategoryGroup
from inventory.models import Supplier

# --- SETUP LOGGER ---
logger = logging.getLogger(__name__)

# --- CUSTOM WIDGET: HANDLES DUAL LANGUAGE (English | Chinese) ---
class DualLanguageManyToManyWidget(ManyToManyWidget):
    """
    Extends ManyToManyWidget to:
    1. EXPORT: Return only the English part (ASCII) to prevent encoding errors.
    2. IMPORT: Robustly match categories by English name or Full name.
    """

    def render(self, value, obj=None):
        """
        Export logic:
        Takes the list of categories (e.g., "肉毒 | Toxins" or "Skin Care | 护肤")
        and returns only the English part.
        """
        ids = [related.pk for related in value.all()]
        objects = self.model.objects.filter(pk__in=ids)

        names = []
        for o in objects:
            original_name = getattr(o, self.field)
            final_name = original_name.strip()

            if '|' in original_name:
                parts = [p.strip() for p in original_name.split('|')]

                # --- INTELLIGENT SELECTION ---
                # Loop through parts and find the first one that is ASCII (English)
                english_part = None
                for p in parts:
                    if all(ord(c) < 128 for c in p): # Check if characters are standard ASCII
                        english_part = p
                        break

                # If an English part was found, use it. Otherwise fallback to the first part.
                if english_part:
                    final_name = english_part
                else:
                    final_name = parts[0]

            # --- LOGGING ---
            # This helps trace what was chosen
            if final_name != original_name.strip():
                logger.info(f"[EXPORT DEBUG] Original: '{original_name}' -> Exporting: '{final_name}'")
            else:
                logger.info(f"[EXPORT DEBUG] Original: '{original_name}' -> Exporting: '{final_name}' (No split needed)")

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
                logger.warning(f"[IMPORT DEBUG] Could not find category match for: '{raw_val}'")

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

    # --- UPDATED: Use Custom Widget ---
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
    # ----------------------------------

    def dehydrate_base_cost(self, product):
        cost = product.base_cost
        return cost if cost is not None else None

    def before_import_row(self, row, **kwargs):
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
