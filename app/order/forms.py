# distributorplatform/app/order/forms.py
from django import forms
from .models import Order


class ManualOrderForm(forms.ModelForm):
    """Form for manual order entry: sales channel, transaction date, and guest customer details."""

    class Meta:
        model = Order
        fields = ['sales_channel', 'transaction_date', 'customer_name', 'customer_phone', 'shipping_address']
        widgets = {
            'sales_channel': forms.Select(attrs={'class': 'w-full rounded-md border border-gray-300 shadow-sm focus:ring-indigo-500 focus:border-indigo-500'}),
            'transaction_date': forms.DateInput(attrs={
                'class': 'w-full rounded-md border border-gray-300 shadow-sm focus:ring-indigo-500 focus:border-indigo-500',
                'type': 'date',
            }),
            'customer_name': forms.TextInput(attrs={
                'class': 'w-full rounded-md border border-gray-300 shadow-sm focus:ring-indigo-500 focus:border-indigo-500',
                'placeholder': 'Customer name'
            }),
            'customer_phone': forms.TextInput(attrs={
                'class': 'w-full rounded-md border border-gray-300 shadow-sm focus:ring-indigo-500 focus:border-indigo-500',
                'placeholder': 'Phone number'
            }),
            'shipping_address': forms.Textarea(attrs={
                'class': 'w-full rounded-md border border-gray-300 shadow-sm focus:ring-indigo-500 focus:border-indigo-500',
                'rows': 3,
                'placeholder': 'Shipping address'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sales_channel'].required = False
        self.fields['transaction_date'].required = False
        self.fields['customer_name'].required = False
        self.fields['customer_phone'].required = False
        self.fields['shipping_address'].required = False
