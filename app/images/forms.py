# distributorplatform/app/images/forms.py
from django import forms
from .models import ImageCategory

class ImageUploadForm(forms.Form):
    title = forms.CharField(
        label="Image Title (Optional Prefix)",
        required=False,
        widget=forms.TextInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'})
    )
    images = forms.FileField(
        label="Image File(s)",
        required=True,
        widget=forms.FileInput(attrs={
            'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm'
        })
    )
    alt_text = forms.CharField(
        label="Alt Text (Optional)",
        required=False,
        widget=forms.TextInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'})
    )
    category = forms.ModelChoiceField(
        queryset=ImageCategory.objects.all(),
        required=False,
        label="Category",
        widget=forms.Select(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'})
    )
