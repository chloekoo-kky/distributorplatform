# distributorplatform/app/inventory/resources.py
from import_export import resources, fields, widgets
from .models import Quotation, QuotationItem, Supplier, InventoryBatch # <-- Add InventoryBatch
from product.models import Product # Keep Product import here
from django.utils.dateparse import parse_date
from datetime import date, datetime
from decimal import Decimal # Import Decimal

# --- UPDATED RESOURCE for Supplier ---
class SupplierResource(resources.ModelResource):
    class Meta:
        model = Supplier
        # --- Use 'code' as the unique key ---
        import_id_fields = ['code']
        # --- Added 'code' to fields ---
        fields = ('id', 'code', 'name', 'contact_person', 'email', 'phone')
        export_order = ('id', 'code', 'name', 'contact_person', 'email', 'phone')
        skip_unchanged = True
        report_skipped = True
# --- END UPDATED RESOURCE ---

class QuotationResource(resources.ModelResource):
    """ Resource for importing QuotationItems. """
    date_quoted_field = fields.Field(
        column_name='Date Quoted',
        widget=widgets.DateWidget(format='%Y-%m-%d') # Adjust format if needed
    )
    # --- ADDED: Fields for parent lookups during import ---
    supplier_name = fields.Field(column_name='Supplier', attribute='quotation__supplier__name') # Example, adjust as needed
    product_name = fields.Field(column_name='Product', attribute='product__name') # Example

    class Meta:
        model = QuotationItem
        fields = ('id', 'product_name', 'quantity', 'quoted_price', 'date_quoted_field', 'supplier_name') # Base fields for resource structure
        export_order = ('id', 'quotation__quotation_id', 'supplier_name', 'date_quoted_field', 'product_name', 'quantity', 'quoted_price', 'quotation__notes') # Define export columns

        import_id_fields = () # Handled manually
        skip_unchanged = True
        report_skipped = True
        # Per-row before_import_row / header-only rows need real saves (not bulk-only path).
        use_bulk = False

    def _clean_str(self, value, field_name, required=True):
        """ Helper to strip string and check if it's required. """
        if value is None:
            if required:
                raise ValueError(f"'{field_name}' is required and missing.")
            return None # Return None if not required and missing
        cleaned = str(value).strip()
        if required and not cleaned:
            raise ValueError(f"'{field_name}' is required and cannot be blank.")
        return cleaned or None # Return None if cleaned is empty but not required

    @staticmethod
    def _is_placeholder_product(value):
        """Rows exported for quotations with no line items use Product 'N/A'."""
        if value is None:
            return True
        s = str(value).strip().upper()
        return s in ('', 'N/A', 'NA', '-', 'NONE')

    def _parse_date_quoted(self, date_str):
        try:
            return self.fields['date_quoted_field'].widget.clean(date_str)
        except Exception:
            pass
        s = str(date_str).strip() if date_str is not None else ''
        parsed = parse_date(s[:10]) if len(s) >= 8 else parse_date(s) if s else None
        if parsed:
            return parsed
        raise ValueError(f"'Date Quoted' ('{date_str}') is not a valid date (use YYYY-MM-DD).")

    def _cell_to_date_str(self, raw, field_name):
        if raw is None or (isinstance(raw, str) and not str(raw).strip()):
            raise ValueError(f"'{field_name}' is required and missing.")
        if isinstance(raw, datetime):
            return raw.date().isoformat()
        if isinstance(raw, date):
            return raw.isoformat()
        return str(raw).strip()

    def _get_or_create_supplier(self, name):
        """ Finds or creates a supplier """
        supplier, _ = Supplier.objects.get_or_create(name=name)
        return supplier

    def _get_or_create_product(self, name):
        """ Finds or creates a product """
        product, _ = Product.objects.get_or_create(name=name, defaults={'description': 'Auto-imported'})
        return product

    def _get_or_create_quotation(self, quotation_id, supplier, date_quoted, notes, transport_cost):
        """ Finds or creates/updates a quotation header (notes must be str, not None). """
        notes_val = notes if notes is not None else ''
        quotation, created = Quotation.objects.get_or_create(
            quotation_id=quotation_id,
            defaults={
                'supplier': supplier, 'date_quoted': date_quoted,
                'notes': notes_val, 'transportation_cost': transport_cost
            }
        )
        if not created: # Update existing
            quotation.supplier = supplier
            quotation.date_quoted = date_quoted
            quotation.notes = notes_val
            quotation.transportation_cost = transport_cost
            quotation.save()
        return quotation

    def before_import(self, dataset, **kwargs):
        """Prepare data before importing rows (django-import-export passes extra flags in **kwargs)."""
        pass

    def _row_price_myr_raw(self, row):
        v = row.get('Quoted Price (MYR)')
        if v is None or (isinstance(v, str) and not str(v).strip()):
            v = row.get('Quoted Price (Unit)')
        return v

    def _resolve_product_from_row(self, row, product_name_required):
        """Match Product SKU first, then Product Name / Product; create by name if missing."""
        sku_raw = row.get('Product SKU')
        sku = str(sku_raw).strip() if sku_raw is not None and str(sku_raw).strip() else ''
        if sku:
            product = Product.objects.filter(sku=sku).first()
            if product:
                return product
        product = Product.objects.filter(name__iexact=product_name_required.strip()).first()
        if product:
            return product
        return self._get_or_create_product(product_name_required)

    def before_import_row(self, row, row_number=None, **kwargs):
        """ Process data and create/update parent objects before item import. """
        try:
            supplier_name = self._clean_str(row.get('Supplier'), 'Supplier')
            date_str = self._cell_to_date_str(row.get('Date Quoted'), 'Date Quoted')
            quotation_id = self._clean_str(row.get('Quotation ID'), 'Quotation ID')
            notes = self._clean_str(row.get('Quotation Notes'), 'Quotation Notes', required=False) or ''
            transport_cost_str = self._clean_str(row.get('Transportation Cost'), 'Transportation Cost', required=False) or '0'

            cleaned_date = self._parse_date_quoted(date_str)
            try:
                transport_cost = Decimal(str(transport_cost_str).replace(',', '').strip())
            except Exception:
                raise ValueError(f"'Transportation Cost' ('{transport_cost_str}') is not a valid number.")

            # --- Header-only row (matches export for quotations with no line items) ---
            placeholder_name = None
            for key in ('Quotation line product name', 'Product Name', 'Product', 'System product name'):
                v = row.get(key)
                if v is not None and str(v).strip():
                    placeholder_name = v
                    break
            if self._is_placeholder_product(placeholder_name):
                supplier = self._get_or_create_supplier(supplier_name)
                quotation = self._get_or_create_quotation(
                    quotation_id, supplier, cleaned_date, notes, transport_cost
                )
                row['_quotation_obj'] = quotation
                row['_skip_item'] = True
                return

            name_cell = row.get('Product Name')
            if name_cell is None or (isinstance(name_cell, str) and not str(name_cell).strip()):
                name_cell = row.get('Product')
            if name_cell is None or (isinstance(name_cell, str) and not str(name_cell).strip()):
                name_cell = row.get('System product name')
            product_name = self._clean_str(name_cell, 'Product Name')

            line_cell = row.get('Quotation line product name')
            if line_cell is not None and str(line_cell).strip():
                row['_source_line_label'] = str(line_cell).strip()[:255]
            else:
                row['_source_line_label'] = (str(name_cell).strip() if name_cell is not None else '')[:255]

            quantity_str = self._clean_str(row.get('Quantity'), 'Quantity')
            self._clean_str(self._row_price_myr_raw(row), 'Quoted Price (MYR)')  # validate early
            supplier = self._get_or_create_supplier(supplier_name)
            product = self._resolve_product_from_row(row, product_name)
            quotation = self._get_or_create_quotation(
                quotation_id, supplier, cleaned_date, notes, transport_cost
            )

            row['_supplier_obj'] = supplier
            row['_product_obj'] = product
            row['_quotation_obj'] = quotation

        except ValueError as e:
            raise ValueError(f"Row {row_number}: {e}")
        except Exception as e:
            raise ValueError(f"Row {row_number}: Unexpected error - {e}")

    def skip_row(self, instance, original, row, import_validation_errors=None):
        if row.get('_skip_item'):
            return True
        return super().skip_row(instance, original, row, import_validation_errors)

    def get_instance(self, instance_loader, row):
        """ Find existing QuotationItem based on quotation and product. """
        if row.get('_skip_item'):
            return None
        try:
            quotation = row['_quotation_obj']
            product = row['_product_obj']
            return QuotationItem.objects.get(quotation=quotation, product=product)
        except QuotationItem.DoesNotExist:
            return None  # Creates a new instance
        except Exception:
            return None

    def import_obj(self, instance, row, dry_run):
        """ Populate the QuotationItem instance fields. """
        try:
            instance.quotation = row['_quotation_obj']
            instance.product = row['_product_obj']

            quantity_str = self._clean_str(row.get('Quantity'), 'Quantity')
            price_str = self._clean_str(self._row_price_myr_raw(row), 'Quoted Price (MYR)')

            try:
                instance.quantity = int(quantity_str)
            except (ValueError, TypeError):
                raise ValueError(f"'Quantity' ('{quantity_str}') must be an integer.")
            try:
                instance.quoted_price = Decimal(str(price_str).replace(',', '').strip())
            except Exception:
                raise ValueError(f"'Quoted Price (MYR)' ('{price_str}') must be a valid number.")

            usd_optional = self._clean_str(row.get('Quoted Price (USD)'), 'Quoted Price (USD)', required=False)
            if usd_optional:
                try:
                    instance.input_currency = QuotationItem.INPUT_CURRENCY_USD
                    instance.input_value = Decimal(str(usd_optional).replace(',', '').strip())
                except Exception:
                    raise ValueError(f"'Quoted Price (USD)' ('{usd_optional}') must be a valid number.")
            else:
                instance.input_currency = QuotationItem.INPUT_CURRENCY_MYR
                instance.input_value = instance.quoted_price

            lbl = (row.get('_source_line_label') or '').strip()[:255]
            if lbl:
                instance.line_product_label = lbl
            elif row.get('_product_obj'):
                instance.line_product_label = (row['_product_obj'].name or '')[:255]

        except ValueError as e:
            raise ValueError(str(e))
        except Exception as e:
            raise ValueError(f"Unexpected error populating object: {e}")

    # Optional: Customize how data is extracted for export
    def dehydrate_supplier_name(self, item):
        return item.quotation.supplier.name if item.quotation and item.quotation.supplier else ''

    def dehydrate_date_quoted_field(self, item):
        return item.quotation.date_quoted if item.quotation else None

    def dehydrate_product_name(self, item):
        return item.product.name if item.product else ''

    def dehydrate_quotation__quotation_id(self, item): # Match export_order field name
         return item.quotation.quotation_id if item.quotation else ''

    def dehydrate_quotation__notes(self, item): # Match export_order field name
         return item.quotation.notes if item.quotation else ''


class InventoryBatchResource(resources.ModelResource):
    """ Resource for importing/exporting InventoryBatches. """
    product = fields.Field(
        column_name='Product SKU',
        attribute='product',
        widget=widgets.ForeignKeyWidget(Product, field='sku')
    )
    supplier = fields.Field(
        column_name='Supplier Code',
        attribute='supplier',
        widget=widgets.ForeignKeyWidget(Supplier, field='code')
    )
    quotation = fields.Field(
        column_name='Quotation ID',
        attribute='quotation',
        widget=widgets.ForeignKeyWidget(Quotation, field='quotation_id')
    )
    received_date = fields.Field(
        column_name='Received Date',
        attribute='received_date',
        widget=widgets.DateWidget(format='%Y-%m-%d') # Adjust format as needed
    )
    expiry_date = fields.Field(
        column_name='Expiry Date',
        attribute='expiry_date',
        widget=widgets.DateWidget(format='%Y-%m-%d')
        # --- REMOVED use_instance=True ---
    ) #

    class Meta:
        model = InventoryBatch
        import_id_fields = ['batch_number']
        fields = ('batch_number', 'product', 'supplier', 'quotation', 'quantity', 'received_date', 'expiry_date')
        export_order = ('batch_number', 'product', 'supplier', 'quotation', 'quantity', 'received_date', 'expiry_date')
        skip_unchanged = True
        report_skipped = True

    # Override dehydrate methods to export related object representations
    def dehydrate_product(self, batch):
        return batch.product.sku if batch.product else ''

    def dehydrate_supplier(self, batch):
        return batch.supplier.code if batch.supplier else ''

    def dehydrate_quotation(self, batch):
        return batch.quotation.quotation_id if batch.quotation else ''
