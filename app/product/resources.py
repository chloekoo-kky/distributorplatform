import logging
import re
import random
import string
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

    # Add *args and **kwargs to the method signature
    def render(self, value, obj=None, *args, **kwargs):
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

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Track SKUs generated in the current import session to prevent intra-file duplicates
        self._generated_skus = set()

    def dehydrate_base_cost(self, product):
        cost = product.base_cost
        return cost if cost is not None else None

    def _assign_sku_from_name(self, row):
        """Set row['sku'] from English portion of row['name'] when sku is missing (collision-aware)."""
        if row.get('sku') or not row.get('name'):
            return
        original_name = str(row['name'])
        english_part = original_name.split('|')[0].strip() if '|' in original_name else original_name
        clean_string = re.sub(r'[^a-zA-Z0-9\s]', ' ', english_part).strip()
        words = clean_string.split()
        if not words:
            random_suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
            final_sku = f"PRD-{random_suffix}"
        else:
            part1 = words[0][:3].upper().ljust(3, 'X')
            if len(words) > 1:
                part2 = words[1][:3].upper().ljust(3, 'X')
            else:
                part2 = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
            base_sku = f"{part1}-{part2}"
            final_sku = base_sku

            def is_sku_taken(check_sku):
                return check_sku in self._generated_skus or Product.objects.filter(sku=check_sku).exists()

            if is_sku_taken(final_sku):
                if len(words) > 2:
                    part3 = words[2][:3].upper().ljust(3, 'X')
                    final_sku = f"{base_sku}-{part3}"
                while is_sku_taken(final_sku):
                    random_suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=3))
                    final_sku = f"{base_sku}-{random_suffix}"

        self._generated_skus.add(final_sku)
        row['sku'] = final_sku

    def before_import_row(self, row, **kwargs):
        # Do not apply exported database PK — updates are keyed by SKU only.
        row.pop('id', None)

        # 0. Normalize product name: replace underscores with spaces, then PascalCase to Title Case
        if row.get('name') and isinstance(row['name'], str):
            name = row['name'].replace('_', ' ').strip()
            # Split camelCase only after lowercase (not digits): "100U" and "3M" stay intact;
            # "iPhone"/"camelCase" still break before capitals that follow a letter.
            name = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', name)
            row['name'] = name.title().strip()

        # 1. Handle missing or blank SKU
        sku_val = row.get('sku')
        if sku_val == '' or (isinstance(sku_val, str) and not sku_val.strip()):
            row['sku'] = None

        # 2. Auto-generate SKU from name if SKU is missing
        self._assign_sku_from_name(row)

        def _is_blank(val):
            if val is None:
                return True
            if isinstance(val, str) and not val.strip():
                return True
            return False

        sku_key = row.get('sku')
        if isinstance(sku_key, str):
            sku_key = sku_key.strip()
            row['sku'] = sku_key or None
            sku_key = row['sku']

        # Updates (existing SKU): omit blank optional cells so we do not clear categories, suppliers, etc.
        if sku_key and Product.objects.filter(sku=sku_key).exists():
            for key in (
                'categories',
                'suppliers',
                'name',
                'description',
                'origin_country',
                'display_order',
                'members_only',
                'selling_price',
                'profit_margin',
            ):
                if _is_blank(row.get(key)):
                    row.pop(key, None)
        else:
            # New row: DB requires a non-empty name; default from SKU when the file leaves name blank.
            if _is_blank(row.get('name')):
                row['name'] = str(sku_key) if sku_key else 'Imported product'
            self._assign_sku_from_name(row)

    @staticmethod
    def get_effective_sku_for_row(row_dict):
        """
        Returns the SKU for a row dict, generating from name if blank.
        Used for preview so the same logic as before_import_row is applied.
        """
        sku_val = row_dict.get('sku')
        if sku_val and (not isinstance(sku_val, str) or sku_val.strip()):
            return sku_val.strip() if isinstance(sku_val, str) else str(sku_val)
        name = row_dict.get('name')
        if not name:
            return None
        original_name = str(name)
        english_part = original_name.split('|')[0].strip() if '|' in original_name else original_name
        clean_string = re.sub(r'[^a-zA-Z0-9\s]', ' ', english_part).strip()
        words = clean_string.split()
        if not words:
            random_suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
            return f"PRD-{random_suffix}"
        part1 = words[0][:3].upper().ljust(3, 'X')
        if len(words) > 1:
            part2 = words[1][:3].upper().ljust(3, 'X')
        else:
            part2 = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
        return f"{part1}-{part2}"

    class Meta:
        model = Product
        # Use SKU as the natural key so uploads can update by SKU without an id column.
        import_id_fields = ['sku']

        fields = (
            'id', 'sku', 'name', 'display_order', 'description', 'origin_country',
            'members_only', 'categories', 'suppliers',
            'base_cost', 'selling_price', 'profit_margin'
        )
        export_order = (
            'id', 'sku', 'name', 'display_order', 'description', 'origin_country',
            'members_only', 'categories', 'suppliers',
            'base_cost', 'selling_price', 'profit_margin', 'created_at'
        )

        skip_unchanged = True
        report_skipped = True
        # Populate RowResult.row_values so upload preview can read file cells (categories, etc.).
        store_row_values = True
