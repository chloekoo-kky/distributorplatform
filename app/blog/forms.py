# distributorplatform/app/blog/forms.py
from django import forms
from .models import Post, UserGroup
from images.models import MediaImage

class PostForm(forms.ModelForm):
    user_groups = forms.ModelMultipleChoiceField(
        queryset=UserGroup.objects.all().order_by('name'),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
        help_text="Select groups to restrict this post to. Leave blank for a public post."
    )

    # --- START MODIFICATION ---
    # Explicitly define gallery_images here
    gallery_images = forms.ModelMultipleChoiceField(
        queryset=MediaImage.objects.all().order_by('title'),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )

    class Meta:
        model = Post
        fields = [
            'title', 'content', 'featured_image', 'status',
            'user_groups', 'slug', 'gallery_images'  # <-- Added 'gallery_images'
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
            'featured_image': forms.HiddenInput(),
            'status': forms.Select(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
            'slug': forms.TextInput(attrs={'class': 'w-full p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'}),
        }
        help_texts = {
            'slug': 'A unique URL-friendly path. Leave blank to auto-generate from title.',
        }
