# distributorplatform/app/inventory/resources.py
from import_export import resources, fields, widgets
from .models import Quotation, QuotationItem, Supplier, InventoryBatch # <-- Add InventoryBatch
from product.models import Product # Keep Product import here
from django.db import transaction
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
        use_bulk = True # Optimize creation

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

    def _get_or_create_supplier(self, name):
        """ Finds or creates a supplier """
        supplier, _ = Supplier.objects.get_or_create(name=name)
        return supplier

    def _get_or_create_product(self, name):
        """ Finds or creates a product """
        product, _ = Product.objects.get_or_create(name=name, defaults={'description': 'Auto-imported'})
        return product

    def _get_or_create_quotation(self, quotation_id, supplier, date_quoted, notes, transport_cost):
        """ Finds or creates/updates a quotation header """
        quotation, created = Quotation.objects.get_or_create(
            quotation_id=quotation_id,
            defaults={
                'supplier': supplier, 'date_quoted': date_quoted,
                'notes': notes, 'transportation_cost': transport_cost
            }
        )
        if not created: # Update existing
            quotation.supplier = supplier
            quotation.date_quoted = date_quoted
            quotation.notes = notes
            quotation.transportation_cost = transport_cost
            quotation.save()
        return quotation

    @transaction.atomic
    def before_import(self, dataset, using_transactions, dry_run, **kwargs):
        """ Prepare data before importing rows (e.g., ensure parents exist). """
        pass # We handle creation/update per row in before_import_row for simplicity

    def before_import_row(self, row, row_number=None, **kwargs):
        """ Process data and create/update parent objects before item import. """
        try:
            # --- Clean required fields ---
            supplier_name = self._clean_str(row.get('Supplier'), 'Supplier')
            date_str = self._clean_str(row.get('Date Quoted'), 'Date Quoted')
            quotation_id = self._clean_str(row.get('Quotation ID'), 'Quotation ID')
            product_name = self._clean_str(row.get('Product'), 'Product')
            quantity_str = self._clean_str(row.get('Quantity'), 'Quantity')
            price_str = self._clean_str(row.get('Quoted Price (Unit)'), 'Quoted Price (Unit)')

            # --- Clean optional fields ---
            notes = self._clean_str(row.get('Quotation Notes'), 'Quotation Notes', required=False)
            transport_cost_str = self._clean_str(row.get('Transportation Cost'), 'Transportation Cost', required=False) or '0'

            # --- Validate and Convert ---
            try:
                cleaned_date = self.fields['date_quoted_field'].widget.clean(date_str)
            except Exception:
                raise ValueError(f"'Date Quoted' ('{date_str}') is not YYYY-MM-DD.")
            try:
                transport_cost = Decimal(transport_cost_str)
            except Exception:
                 raise ValueError(f"'Transportation Cost' ('{transport_cost_str}') is not a valid number.")

            # --- Get/Create Parents ---
            supplier = self._get_or_create_supplier(supplier_name)
            product = self._get_or_create_product(product_name) # Ensure product exists
            quotation = self._get_or_create_quotation(
                quotation_id, supplier, cleaned_date, notes, transport_cost
            )

            # Store parents on the row dict for get_instance and import_obj
            row['_supplier_obj'] = supplier
            row['_product_obj'] = product
            row['_quotation_obj'] = quotation

        except ValueError as e:
             from import_export.results import RowResult
             raise self.skip_row(f"Row {row_number}: {e}")
        except Exception as e:
             from import_export.results import RowResult
             raise self.skip_row(f"Row {row_number}: Unexpected error - {e}")

    def get_instance(self, instance_loader, row):
        """ Find existing QuotationItem based on quotation and product. """
        try:
            # Use pre-fetched objects from before_import_row
            quotation = row['_quotation_obj']
            product = row['_product_obj']
            return QuotationItem.objects.get(quotation=quotation, product=product)
        except QuotationItem.DoesNotExist:
            return None # Creates a new instance
        except Exception as e:
             return None

    def import_obj(self, instance, row, dry_run):
        """ Populate the QuotationItem instance fields. """
        try:
            # Set relationships using pre-fetched objects
            instance.quotation = row['_quotation_obj']
            instance.product = row['_product_obj']

            # Set quantity and price
            quantity_str = self._clean_str(row.get('Quantity'), 'Quantity')
            price_str = self._clean_str(row.get('Quoted Price (Unit)'), 'Quoted Price (Unit)')

            try:
                instance.quantity = int(quantity_str)
            except (ValueError, TypeError):
                 raise ValueError(f"'Quantity' ('{quantity_str}') must be an integer.")
            try:
                 instance.quoted_price = Decimal(price_str)
            except Exception:
                 raise ValueError(f"'Quoted Price (Unit)' ('{price_str}') must be a valid number.")

        except ValueError as e:
             from import_export.results import RowResult
             raise self.skip_row(str(e))
        except Exception as e:
             from import_export.results import RowResult
             raise self.skip_row(f"Unexpected error populating object: {e}")

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
