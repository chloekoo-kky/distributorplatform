# distributorplatform/app/seo/forms.py
from django import forms
from .models import PageMetadata

class PageMetadataForm(forms.ModelForm):
    class Meta:
        model = PageMetadata
        fields = ['page_name', 'page_path', 'meta_title', 'meta_description']
        widgets = {
            'page_name': forms.TextInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
            'page_path': forms.TextInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
            'meta_title': forms.TextInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
            'meta_description': forms.Textarea(attrs={'rows': 3, 'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
        }
