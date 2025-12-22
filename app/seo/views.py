# distributorplatform/app/seo/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from .models import PageMetadata
from .forms import PageMetadataForm
from inventory.views import staff_required
from django.urls import reverse
import json

@staff_required
def manage_seo_create(request):
    if request.method == 'POST':
        # Check for AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            try:
                # Support both JSON body and standard form data
                if request.content_type == 'application/json':
                    data = json.loads(request.body)
                    form = PageMetadataForm(data)
                else:
                    form = PageMetadataForm(request.POST)

                if form.is_valid():
                    form.save()
                    return JsonResponse({'success': True, 'message': "SEO settings created successfully."})
                else:
                    return JsonResponse({'success': False, 'errors': form.errors}, status=400)
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)}, status=500)

        # Fallback for standard submit (if ever used)
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

    # Handle AJAX GET to fetch data for the modal
    if request.method == 'GET' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        data = {
            'id': metadata.id,
            'page_name': metadata.page_name,
            'page_path': metadata.page_path,
            'meta_title': metadata.meta_title,
            'meta_description': metadata.meta_description,
            'update_url': reverse('seo:manage_seo_edit', args=[metadata.id])
        }
        return JsonResponse(data)

    if request.method == 'POST':
        # Check for AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            try:
                if request.content_type == 'application/json':
                    data = json.loads(request.body)
                    form = PageMetadataForm(data, instance=metadata)
                else:
                    form = PageMetadataForm(request.POST, instance=metadata)

                if form.is_valid():
                    form.save()
                    return JsonResponse({'success': True, 'message': f"SEO settings for '{metadata.page_name}' updated."})
                else:
                    return JsonResponse({'success': False, 'errors': form.errors}, status=400)
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)}, status=500)

        # Fallback
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
