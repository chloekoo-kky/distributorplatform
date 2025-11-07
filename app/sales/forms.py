# distributorplatform/app/sales/forms.py
from django import forms
from .models import Invoice

class InvoiceUpdateForm(forms.ModelForm):
    """ Form for updating specific fields of an existing Invoice. """
    # --- UPDATED field definition ---
    payment_date = forms.DateField(
        required=False, # Payment date is optional until paid
        widget=forms.DateInput(
            attrs={
                'type': 'date',
                'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500'
            }
        )
    )

    class Meta:
        model = Invoice
        # --- UPDATED fields ---
        fields = ['status', 'payment_date', 'notes'] # Fields editable in the modal
        widgets = {
            'status': forms.Select(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500'}),
            'notes': forms.Textarea(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500', 'rows': 3}),
        }
