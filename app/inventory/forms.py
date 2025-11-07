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
    """ Form for entering a new Inventory Batch. Configured for 'Receive Stock' modal. """
    received_date = forms.DateField(
        widget=forms.DateInput(
            attrs={
                'type': 'date',
                'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500'
            }
        ),
        initial=datetime.date.today # Set default to today
    )
    quantity = forms.IntegerField(
         label="Quantity Received",
         min_value=0, # Allow receiving zero? Or 1?
         widget=forms.NumberInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500'})
    )
    batch_number = forms.CharField(
         label="Batch",
         widget=forms.TextInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500', 'placeholder': 'e.g., PO-12345 or BatchXYZ'})
    )
    expiry_date = forms.DateField(
        required=False, # Make it optional
        widget=forms.DateInput(
            attrs={'type': 'date', 'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500'}
        )
    )
    product = forms.ModelChoiceField(
        queryset=Product.objects.all(),
        widget=forms.HiddenInput() # Use HiddenInput
    )
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.all(),
        widget=forms.HiddenInput() # Use HiddenInput
    )
    quotation = forms.ModelChoiceField(
        queryset=Quotation.objects.all(),
        required=False, # Make sure it's not required if it might be missing
        widget=forms.HiddenInput() # Use HiddenInput
    )
    invoice_item = forms.ModelChoiceField(
        queryset=InvoiceItem.objects.all(),
        required=False,
        widget=forms.HiddenInput())

    class Meta:
        model = InventoryBatch
        # Fields list remains the same, but widgets above define visibility
        fields = [
            'batch_number',
            'expiry_date', # Moved expiry_date after batch_number
            'quantity',
            'received_date',
            'product',      # Hidden fields remain
            'supplier',
            'quotation',
            'invoice_item'
        ]

    def __init__(self, *args, **kwargs):
        # Pop invoice_item instance if passed during initialization
        self.invoice_item_instance = kwargs.pop('invoice_item', None)
        super().__init__(*args, **kwargs)

        # Set max value for quantity input if invoice_item is provided
        if self.invoice_item_instance:
            remaining_qty = self.invoice_item_instance.quantity_remaining
            self.fields['quantity'].widget.attrs['max'] = remaining_qty
            self.fields['quantity'].max_value = remaining_qty # Server-side validation
            self.fields['quantity'].help_text = f"Maximum receivable: {remaining_qty}"
            # Pre-fill hidden invoice_item field
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
        label="Select Quotation File (.xlsx, .csv)",
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
