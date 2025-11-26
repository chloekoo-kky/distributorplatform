# distributorplatform/app/blog/forms.py
from django import forms
from .models import Post, UserGroup
from images.models import MediaImage
from product.models import Product

class PostForm(forms.ModelForm):
    user_groups = forms.ModelMultipleChoiceField(
        queryset=UserGroup.objects.all().order_by('name'),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
        help_text="Select groups to restrict this post to. Leave blank for a public post."
    )

    related_products = forms.ModelMultipleChoiceField(
        queryset=Product.objects.all().order_by('name'),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
        help_text="Select products related to this post."
    )

    gallery_images = forms.ModelMultipleChoiceField(
        queryset=MediaImage.objects.all().order_by('title'),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )

    is_published = forms.BooleanField(
        required=False,
        label="Publish",
        help_text="Check this box to publish the post immediately.",
        widget=forms.CheckboxInput(attrs={
            'class': 'h-4 w-4 text-indigo-600 border-gray-300 rounded focus:ring-indigo-500'
        })
    )

    class Meta:
        model = Post
        fields = [
            'title', 'post_type', 'content', 'featured_image',
            'gallery_images', 'related_products_title', 'related_products', # <-- Added title here
            'user_groups', 'slug'
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
            'post_type': forms.Select(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
            'featured_image': forms.HiddenInput(),
            # --- NEW: Styling for Title Input ---
            'related_products_title': forms.TextInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500', 'placeholder': 'Default: Related Products'}),
            'slug': forms.TextInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
        }
        help_texts = {
            'slug': 'A unique URL-friendly path. Leave blank to auto-generate from title.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['is_published'].initial = (self.instance.status == Post.PostStatus.PUBLISHED)

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.status = Post.PostStatus.PUBLISHED if self.cleaned_data['is_published'] else Post.PostStatus.DRAFT

        if commit:
            instance.save()
            self.save_m2m()
        return instance
