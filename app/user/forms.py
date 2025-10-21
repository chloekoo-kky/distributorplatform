# distributorplatform/app/user/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from .models import CustomUser
from phonenumber_field.formfields import PhoneNumberField
from phonenumber_field.widgets import PhoneNumberPrefixWidget

class CustomUserCreationForm(UserCreationForm):
    phone_number = PhoneNumberField(
        widget=PhoneNumberPrefixWidget(
            initial='MY',
            country_attrs={
                'class': 'relative w-1/3 p-2 text-left bg-white border border-gray-300 rounded-l-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500'
            },
            attrs={
                'class': 'relative w-2/3 p-2 border border-gray-300 rounded-r-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 -ml-px',
                'placeholder': '12 345 6789'
            }
        ),
        # --- REFINED ERROR MESSAGE ---
        error_messages={'invalid': 'Please enter a valid phone number for the selected country.'}
    )

    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = ('username', 'email', 'phone_number')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if 'password2' in self.fields:
            del self.fields['password2']

        # Define the common styling for the input fields
        common_attrs = {
            'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500',
        }

        # Apply the styles and placeholders to each field
        self.fields['username'].widget.attrs.update({**common_attrs, 'placeholder': 'e.g., johnsmith'})
        self.fields['email'].widget.attrs.update({**common_attrs, 'placeholder': 'e.g., john.smith@example.com'})
        self.fields['password1'].widget.attrs.update({**common_attrs, 'placeholder': 'Enter your password', 'id': 'password-input'})
