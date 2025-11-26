# distributorplatform/app/product/forms.py
from django import forms
# --- START MODIFICATION ---
from .models import Product
from images.models import MediaImage
from inventory.models import Supplier
from .models import Category
# --- END MODIFICATION ---

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
    """
    Form for editing a Product from the manage_tools UI.
    """
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

    # --- START MODIFICATION ---
    # Explicitly define featured_image to ensure it's not required
    featured_image = forms.ModelChoiceField(
        queryset=MediaImage.objects.all(),
        required=False,
        widget=forms.HiddenInput()
    )
    # --- END MODIFICATION ---

    class Meta:
        model = Product
        fields = [
            'name', 'sku', 'description', 'members_only', 'is_featured',
            'categories', 'suppliers', 'featured_image', 'gallery_images'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
            'sku': forms.TextInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
            'description': forms.Textarea(attrs={'rows': 5, 'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
            'members_only': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-indigo-600 border-gray-300 rounded focus:ring-indigo-500'}),
            'is_featured': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-indigo-600 border-gray-300 rounded focus:ring-indigo-500'}),
            'featured_image': forms.HiddenInput(), # This widget is fine, but the field definition above is key
        }
# --- END NEW FORM ---
