# distributorplatform/app/product/forms.py
from django import forms
from .models import Product
from images.models import MediaImage
from inventory.models import Supplier
from .models import Category
from tinymce.widgets import TinyMCE


class ProductUploadForm(forms.Form):
    """
    A simple form for uploading a product file.
    """
    file = forms.FileField(
        label="Select Product File (.xlsx, .csv)",
        widget=forms.FileInput(
            attrs={
                'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500',
                'accept': '.xlsx, .xls, .csv'
            }
        )
    )

# --- START NEW FORM ---
class ProductForm(forms.ModelForm):
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.all().select_related('group').order_by('group__name', 'name'),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    suppliers = forms.ModelMultipleChoiceField(
        queryset=Supplier.objects.all().order_by('name'),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    gallery_images = forms.ModelMultipleChoiceField(
        queryset=MediaImage.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )

    featured_image = forms.ModelChoiceField(
        queryset=MediaImage.objects.all(),
        required=False,
        widget=forms.HiddenInput()
    )

    class Meta:
        model = Product
        fields = [
            'name', 'sku', 'description_title', 'description', 'origin_country', 'members_only', 'is_featured', # Added origin_country
            'categories', 'suppliers', 'featured_image', 'gallery_images'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
            'sku': forms.TextInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
            'description_title': forms.TextInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 font-semibold', 'placeholder': 'Section Title (e.g. Description)'}),

            'origin_country': forms.TextInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500', 'placeholder': 'e.g. Korea'}),
            'description': TinyMCE(attrs={'cols': 80, 'rows': 10, 'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
            # --------------------------

            'members_only': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-indigo-600 border-gray-300 rounded focus:ring-indigo-500'}),
            'is_featured': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-indigo-600 border-gray-300 rounded focus:ring-indigo-500'}),
            'featured_image': forms.HiddenInput(),
        }


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'page_title', 'description']
        widgets = {
            # Added w-full and styling classes here:
            'name': forms.TextInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
            'page_title': forms.TextInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
            'description': TinyMCE(attrs={'cols': 80, 'rows': 10}),
        }
