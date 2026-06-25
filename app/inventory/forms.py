# distributorplatform/app/inventory/forms.py
from django import forms
import datetime # <-- Added import
from .models import InventoryBatch, Supplier, Quotation, QuotationItem
from product.models import Product
from sales.models import InvoiceItem


class QuotationItemForm(forms.ModelForm):
    """ A form for adding a QuotationItem to an existing Quotation. """
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(), # Start empty
        widget=forms.Select(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500'})
    )

    def __init__(self, *args, **kwargs):
        # --- Get supplier from kwargs ---
        supplier = kwargs.pop('supplier', None)
        super().__init__(*args, **kwargs)

        # --- Filter product queryset based on supplier ---
        if supplier:
            # Filter products where the supplier is linked
            self.fields['product'].queryset = Product.objects.filter(
                suppliers=supplier
            ).order_by('name')
        else:
             # Fallback: If no supplier provided, show all products (or keep empty)
             # self.fields['product'].queryset = Product.objects.all().order_by('name')
             self.fields['product'].queryset = Product.objects.none() # Keep empty if no supplier


    class Meta:
        model = QuotationItem
        fields = ['product', 'quantity', 'quoted_price']
        widgets = {
            'quantity': forms.NumberInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500', 'placeholder': 'e.g., 100'}),
            'quoted_price': forms.NumberInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500', 'placeholder': 'e.g., 12.50'}),
        }

class QuotationCreateForm(forms.ModelForm):
    """ A form for creating a new Quotation from the front-end. """

    class Meta:
        model = Quotation
        fields = ['supplier']
        widgets = {
            # Use RadioSelect instead of a dropdown
            'supplier': forms.RadioSelect,
        }


class InventoryBatchForm(forms.ModelForm):
    """
    Form for the 'Receive Stock' modal.
    Batch number and expiry are optional and can be set later from Inventory.
    """
    received_date = forms.DateField(
        widget=forms.DateInput(
            attrs={
                'type': 'date',
                'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500'
            }
        ),
        initial=datetime.date.today
    )
    quantity = forms.IntegerField(
        label="Quantity Received",
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500'})
    )
    product = forms.ModelChoiceField(
        queryset=Product.objects.all(),
        widget=forms.HiddenInput()
    )
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.all(),
        widget=forms.HiddenInput()
    )
    quotation = forms.ModelChoiceField(
        queryset=Quotation.objects.all(),
        required=False,
        widget=forms.HiddenInput()
    )
    invoice_item = forms.ModelChoiceField(
        queryset=InvoiceItem.objects.all(),
        required=False,
        widget=forms.HiddenInput()
    )

    class Meta:
        model = InventoryBatch
        fields = [
            'quantity',
            'received_date',
            'product',
            'supplier',
            'quotation',
            'invoice_item',
        ]

    def __init__(self, *args, **kwargs):
        self.invoice_item_instance = kwargs.pop('invoice_item', None)
        super().__init__(*args, **kwargs)

        if self.invoice_item_instance:
            remaining_qty = self.invoice_item_instance.quantity_remaining
            self.fields['quantity'].widget.attrs['max'] = remaining_qty
            self.fields['quantity'].max_value = remaining_qty
            self.fields['quantity'].help_text = f"Maximum receivable: {remaining_qty}"
            self.initial['invoice_item'] = self.invoice_item_instance.pk

    def clean_quantity(self):
        quantity = self.cleaned_data.get('quantity')
        if self.invoice_item_instance:
            max_qty = self.invoice_item_instance.quantity_remaining
            if quantity > max_qty:
                raise forms.ValidationError(f"Cannot receive more than the remaining quantity ({max_qty}).")
        if quantity < 0:
            raise forms.ValidationError("Quantity cannot be negative.")
        return quantity
    

class QuotationUploadForm(forms.Form):
    """ A simple form for uploading a quotation file. """
    file = forms.FileField(
        label="Select PO file (.xlsx, .csv)",
        widget=forms.FileInput(
            attrs={
                'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500',
                'accept': '.xlsx, .xls, .csv'
            }
        )
    )


class InvoiceUploadForm(forms.Form):
    """Upload a standalone invoice spreadsheet (no linked purchase order)."""
    file = forms.FileField(
        label="Select invoice file (.xlsx, .csv)",
        widget=forms.FileInput(
            attrs={
                'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500',
                'accept': '.xlsx, .xls, .csv'
            }
        )
    )

class InventoryBatchUploadForm(forms.Form):
    """ A simple form for uploading an inventory batch file. """
    file = forms.FileField(
        label="Select Batch File (.xlsx, .csv)",
        widget=forms.FileInput(
            attrs={
                'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500',
                'accept': '.xlsx, .xls, .csv'
            }
        )
    )
