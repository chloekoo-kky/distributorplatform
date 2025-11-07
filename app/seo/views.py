# distributorplatform/app/seo/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import PageMetadata
from .forms import PageMetadataForm
from inventory.views import staff_required
from django.urls import reverse

@staff_required
def manage_seo_create(request):
    if request.method == 'POST':
        form = PageMetadataForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "SEO settings created successfully.")
            return redirect(reverse('core:manage_dashboard') + '#seo')
    else:
        form = PageMetadataForm()

    context = {
        'form': form,
        'title': 'Create New SEO Setting',
        'is_subpage': True
    }
    return render(request, 'seo/manage_seo_form.html', context)

@staff_required
def manage_seo_edit(request, meta_id):
    metadata = get_object_or_404(PageMetadata, pk=meta_id)
    if request.method == 'POST':
        form = PageMetadataForm(request.POST, instance=metadata)
        if form.is_valid():
            form.save()
            messages.success(request, f"SEO settings for '{metadata.page_name}' updated.")
            return redirect(reverse('core:manage_dashboard') + '#seo')
    else:
        form = PageMetadataForm(instance=metadata)

    context = {
        'form': form,
        'title': f"Editing SEO for: {metadata.page_name}",
        'metadata': metadata,
        'is_subpage': True
    }
    return render(request, 'seo/manage_seo_form.html', context)
