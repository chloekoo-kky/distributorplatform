# distributorplatform/app/images/views.py
from django.shortcuts import render, get_object_or_404
from django.contrib import messages
from django.db.models import ProtectedError
from django.http import JsonResponse
from django.urls import reverse

import json
import os
import re
from PIL import Image
from io import BytesIO
from django.core.files.base import ContentFile
import logging

# --- New Imports ---
from .models import MediaImage, ImageCategory
from .forms import ImageUploadForm
from product.models import Product
from blog.models import Post
from inventory.views import staff_required
from django.db import transaction
# --- End New Imports ---

logger = logging.getLogger(__name__)


def format_image_title(name):
    """
    Apply same formatting as product names: replace underscores with spaces,
    split PascalCase/camelCase, then Title Case. Used for image titles from filenames.
    """
    if not name or not isinstance(name, str):
        return name or ''
    s = name.replace('_', ' ').strip()
    s = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', s)
    return s.title().strip()


@staff_required
def ajax_get_images(request):
    """
    Returns a JSON list of all images in the gallery,
    optionally filtered by category.
    """
    category_id = request.GET.get('category_id')

    # 1. Prefetch all relationships to avoid N+1 query performance issues
    images_query = MediaImage.objects.all().select_related('category').prefetch_related(
        'featured_in_products',
        'product_galleries',
        'featured_in_posts',
        'post_galleries'
    )

    if category_id:
        images_query = images_query.filter(category_id=category_id)

    data = []
    for img in images_query:
        # 2. Build the list of assignments
        assigned_to = []

        # Product: Featured
        for p in img.featured_in_products.all():
            assigned_to.append({'type': 'F.Product', 'name': p.name})

        # Product: Gallery
        for p in img.product_galleries.all():
            assigned_to.append({'type': 'Product', 'name': p.name})

        # Post: Featured
        for p in img.featured_in_posts.all():
            assigned_to.append({'type': 'F.Post', 'name': p.title})

        # Post: Gallery
        for p in img.post_galleries.all():
            assigned_to.append({'type': 'Post', 'name': p.title})

        data.append({
            'id': img.id,
            'title': img.title,
            'url': img.image.url,
            'alt_text': img.alt_text,
            'category_id': img.category_id,
            'category_name': img.category.name if img.category else 'Uncategorized',
            'assigned_to': assigned_to, # <--- Add this field
        })

    categories = list(ImageCategory.objects.values('id', 'name'))
    return JsonResponse({'images': data, 'categories': categories})

@staff_required
def ajax_upload_image(request):
    """
    Handles image uploads from the gallery modal.
    Resizes and converts images to WebP on-the-fly.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=400)

    form = ImageUploadForm(request.POST, request.FILES)

    if form.is_valid():
        uploaded_files = request.FILES.getlist('images')
        base_title = form.cleaned_data.get('title', '').strip()
        alt_text = form.cleaned_data.get('alt_text', '')
        category = form.cleaned_data.get('category')

        # Optional per-file titles from confirmation modal (JSON array)
        image_titles = []
        raw_titles = request.POST.get('image_titles')
        if raw_titles:
            try:
                image_titles = json.loads(raw_titles)
            except (json.JSONDecodeError, TypeError):
                pass

        created_images = []

        for i, uploaded_file in enumerate(uploaded_files, 1):
            img = Image.open(uploaded_file)
            original_ext = os.path.splitext(uploaded_file.name)[1] or ''
            detected_format = (img.format or '').upper()
            # Fallback to extension-based format when Pillow cannot infer it.
            if not detected_format:
                ext_to_format = {
                    '.jpg': 'JPEG',
                    '.jpeg': 'JPEG',
                    '.png': 'PNG',
                    '.gif': 'GIF',
                    '.bmp': 'BMP',
                    '.tif': 'TIFF',
                    '.tiff': 'TIFF',
                    '.webp': 'WEBP',
                }
                detected_format = ext_to_format.get(original_ext.lower(), 'PNG')
            MAX_SIZE = (1280, 1280)
            img.thumbnail(MAX_SIZE, Image.Resampling.LANCZOS)
            output_buffer = BytesIO()
            save_kwargs = {'format': detected_format}
            if detected_format in ('JPEG', 'WEBP'):
                save_kwargs['quality'] = 85
            img.save(output_buffer, **save_kwargs)
            output_buffer.seek(0)
            new_file_content = ContentFile(output_buffer.getvalue())
            base_filename = os.path.splitext(uploaded_file.name)[0]
            format_to_ext = {
                'JPEG': '.jpg',
                'PNG': '.png',
                'GIF': '.gif',
                'BMP': '.bmp',
                'TIFF': '.tiff',
                'WEBP': '.webp',
            }
            final_ext = original_ext if original_ext else format_to_ext.get(detected_format, '.png')
            new_filename = f"{base_filename}{final_ext}"

            # Use per-file title from confirmation modal, or formatted filename, or base_title
            if image_titles and i <= len(image_titles) and image_titles[i - 1]:
                final_title = (image_titles[i - 1] or '').strip() or format_image_title(base_filename)
            elif base_title and len(uploaded_files) > 1:
                final_title = f"{base_title} ({i})"
            elif base_title:
                final_title = base_title
            else:
                final_title = format_image_title(base_filename)

            image_instance = MediaImage(
                title=final_title,
                alt_text=alt_text,
                category=category
            )

            image_instance.image.save(new_filename, new_file_content, save=False)
            image_instance.save()

            created_images.append({
                'id': image_instance.id,
                'title': image_instance.title,
                'url': image_instance.image.url,
                'alt_text': image_instance.alt_text,
                'category_id': image_instance.category_id,
                'category_name': image_instance.category.name if image_instance.category else 'Uncategorized',
                'assigned_to': [], # <--- New images have no assignments
            })

        return JsonResponse({
            'success': True,
            'images': created_images
        })

    else:
        error_string = '. '.join([' '.join(errors) for errors in form.errors.values()])
        return JsonResponse({'success': False, 'errors': error_string or 'Invalid data.'}, status=400)


@staff_required
def ajax_delete_image(request, image_id):
    """
    Handles the POST request to delete a MediaImage.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=400)

    image = get_object_or_404(MediaImage, pk=image_id)
    try:
        image.delete()
        return JsonResponse({'success': True, 'message': 'Image deleted successfully.'})
    except ProtectedError:
        return JsonResponse({
            'success': False,
            'error': 'Cannot delete image. It is currently being used as a featured image on one or more blog posts or products.'
        }, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@staff_required
def ajax_bulk_delete_images(request):
    """
    Deletes multiple MediaImage records in one request.
    """
    if request.method != 'POST' or request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=400)

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        payload = {}

    image_ids = payload.get('image_ids') or []
    if not isinstance(image_ids, list) or not image_ids:
        return JsonResponse({'success': False, 'error': 'No images selected for deletion.'}, status=400)

    # Ensure IDs are integers
    try:
        image_ids = [int(i) for i in image_ids]
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid image ID list.'}, status=400)

    to_delete = MediaImage.objects.filter(id__in=image_ids)
    deleted_ids = []
    protected_ids = []

    for img in to_delete:
        img_id = img.id
        try:
            img.delete()
            deleted_ids.append(img_id)
        except ProtectedError:
            protected_ids.append(img_id)
        except Exception:
            # Skip unexpected errors for individual images but continue with others
            continue

    if not deleted_ids and protected_ids:
        return JsonResponse({
            'success': False,
            'error': 'None of the selected images could be deleted because they are in use.',
            'protected_ids': protected_ids,
        }, status=400)

    return JsonResponse({
        'success': True,
        'message': f'Deleted {len(deleted_ids)} image(s).',
        'deleted_ids': deleted_ids,
        'protected_ids': protected_ids,
    })

@staff_required
@transaction.atomic
def ajax_assign_to_products(request):
    """
    Handles POST request to assign a MediaImage to multiple Products.
    Featured: Sets image as featured (exclusive).
    Gallery: Syncs image in gallery (Adds to selected, Removes from unselected).
    """
    if request.method != 'POST' or not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=400)

    try:
        data = json.loads(request.body)
        image_id = data.get('image_id')
        product_ids = data.get('product_ids', [])
        assignment_type = data.get('assignment_type') # 'featured' or 'gallery'

        if not image_id or not assignment_type:
            return JsonResponse({'success': False, 'error': 'Missing image_id or assignment_type.'}, status=400)

        image_instance = get_object_or_404(MediaImage, pk=image_id)

        if assignment_type == 'featured':
            # 1. Set this image for all products in the list
            products_to_set = Product.objects.filter(id__in=product_ids)
            set_count = products_to_set.update(featured_image=image_instance)

            # 2. Clear this image from any products NOT in the list
            products_to_clear = Product.objects.filter(featured_image=image_instance).exclude(id__in=product_ids)
            cleared_count = products_to_clear.update(featured_image=None)

            logger.info(f"Assign Featured Image to Products: Set {set_count}, Cleared {cleared_count} for Image {image_id}")

        elif assignment_type == 'gallery':
            # 1. Add image to Selected Products
            products_to_set = Product.objects.filter(id__in=product_ids)
            for product in products_to_set:
                product.gallery_images.add(image_instance)

            # 2. Remove image from Unselected Products (that previously had it)
            products_to_remove = Product.objects.filter(gallery_images=image_instance).exclude(id__in=product_ids)
            for product in products_to_remove:
                product.gallery_images.remove(image_instance)

            logger.info(f"Gallery Sync for Image {image_id}: Added to {products_to_set.count()}, Removed from {products_to_remove.count()}")

        else:
            return JsonResponse({'success': False, 'error': 'Invalid assignment_type.'}, status=400)


        # Send back the updated list of all products
        all_products_qs = Product.objects.all().prefetch_related('gallery_images').select_related('featured_image')
        all_products_list = [
            {
                'id': p.id,
                'name': p.name,
                'sku': p.sku or '-',
                'featured_image_id': p.featured_image_id,
                'featured_image_title': p.featured_image.title if p.featured_image else None, # <--- ADD THIS
                'gallery_image_ids': list(p.gallery_images.all().values_list('id', flat=True))
            } for p in all_products_qs
        ]

        return JsonResponse({
            'success': True,
            'message': 'Product assignments updated successfully.',
            'all_products': all_products_list
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON.'}, status=400)
    except Exception as e:
        logger.error(f"Error in ajax_assign_to_products: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@staff_required
@transaction.atomic
def ajax_assign_to_posts(request):
    """
    Handles POST request to assign a MediaImage to multiple Blog Posts.
    Featured: Sets image as featured.
    Gallery: Syncs image in gallery (Adds to selected, Removes from unselected).
    """
    if request.method != 'POST' or not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=400)

    try:
        data = json.loads(request.body)
        image_id = data.get('image_id')
        post_ids = data.get('post_ids', [])
        assignment_type = data.get('assignment_type') # 'featured' or 'gallery'

        if not image_id or not assignment_type:
            return JsonResponse({'success': False, 'error': 'Missing image_id or assignment_type.'}, status=400)

        image_instance = get_object_or_404(MediaImage, pk=image_id)

        if assignment_type == 'featured':
            # 1. Set this image for all posts in the list
            posts_to_set = Post.objects.filter(id__in=post_ids)
            set_count = posts_to_set.update(featured_image=image_instance)

            # 2. Clear this image from any posts NOT in the list
            posts_to_clear = Post.objects.filter(featured_image=image_instance).exclude(id__in=post_ids)
            cleared_count = posts_to_clear.update(featured_image=None)

            logger.info(f"Assign Featured Image to Posts: Set {set_count}, Cleared {cleared_count} for Image {image_id}")

        elif assignment_type == 'gallery':
            # 1. Add image to Selected Posts
            posts_to_set = Post.objects.filter(id__in=post_ids)
            for post in posts_to_set:
                post.gallery_images.add(image_instance)

            # 2. Remove image from Unselected Posts
            posts_to_remove = Post.objects.filter(gallery_images=image_instance).exclude(id__in=post_ids)
            for post in posts_to_remove:
                post.gallery_images.remove(image_instance)

            logger.info(f"Gallery Sync for Image {image_id}: Added to {posts_to_set.count()}, Removed from {posts_to_remove.count()}")

        else:
            return JsonResponse({'success': False, 'error': 'Invalid assignment_type.'}, status=400)

        # Send back the updated list of all posts
        all_posts_qs = Post.objects.all().prefetch_related('gallery_images').select_related('featured_image')
        all_posts_list = [
            {
                'id': p.id,
                'title': p.title,
                'featured_image_id': p.featured_image_id,
                'gallery_image_ids': list(p.gallery_images.all().values_list('id', flat=True))
            } for p in all_posts_qs
        ]

        return JsonResponse({
            'success': True,
            'message': 'Post assignments updated successfully.',
            'all_posts': all_posts_list
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON.'}, status=400)
    except Exception as e:
        logger.error(f"Error in ajax_assign_to_posts: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@staff_required
@transaction.atomic
def ajax_bulk_assign(request):
    """
    Handles POST request to assign MULTIPLE images to a SINGLE
    product or post's gallery.
    """
    if request.method != 'POST' or not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=400)

    try:
        data = json.loads(request.body)
        image_ids = data.get('image_ids', [])
        target_id = data.get('target_id')
        target_type = data.get('target_type') # 'product' or 'post'

        if not image_ids or not target_id or not target_type:
            return JsonResponse({'success': False, 'error': 'Missing image_ids, target_id, or target_type.'}, status=400)

        images = MediaImage.objects.filter(id__in=image_ids)
        if not images.exists():
            return JsonResponse({'success': False, 'error': 'No valid images found.'}, status=400)

        if target_type == 'product':
            target_obj = get_object_or_404(Product, pk=target_id)
            target_obj.gallery_images.add(*images)
            logger.info(f"Bulk assigned {len(image_ids)} images to Product ID {target_id} gallery.")

        elif target_type == 'post':
            target_obj = get_object_or_404(Post, pk=target_id)
            target_obj.gallery_images.add(*images)
            logger.info(f"Bulk assigned {len(image_ids)} images to Post ID {target_id} gallery.")

        else:
            return JsonResponse({'success': False, 'error': 'Invalid target_type.'}, status=400)

        # We must send back the updated product/post lists
        # so the "Already in gallery" badges can update

        all_products_qs = Product.objects.all().prefetch_related('gallery_images').select_related('featured_image')
        all_products_list = [
            {
                'id': p.id, 'name': p.name, 'sku': p.sku or '-',
                'featured_image_id': p.featured_image_id,
                'gallery_image_ids': list(p.gallery_images.all().values_list('id', flat=True))
            } for p in all_products_qs
        ]

        all_products_qs = Product.objects.all().prefetch_related('gallery_images').select_related('featured_image')
        all_products_list = [
            {
                'id': p.id, 'name': p.name, 'sku': p.sku or '-',
                'featured_image_id': p.featured_image_id,
                'featured_image_title': p.featured_image.title if p.featured_image else None, # <--- ADD THIS
                'gallery_image_ids': list(p.gallery_images.all().values_list('id', flat=True))
            } for p in all_products_qs
        ]

        return JsonResponse({
            'success': True,
            'message': 'Images successfully bulk-assigned to gallery.',
            'all_products': all_products_list,
            'all_posts': all_posts_list
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON.'}, status=400)
    except Exception as e:
        logger.error(f"Error in ajax_bulk_assign: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@staff_required
@transaction.atomic
def ajax_bulk_auto_assign(request):
    """
    Handles POST request to bulk-set featured images for products.
    Expects payload of the form:
        {"assignments": [{"image_id": 1, "product_id": 10}, ...]}
    """
    if request.method != 'POST' or request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=400)

    try:
        data = json.loads(request.body)
        assignments = data.get('assignments', [])

        if not isinstance(assignments, list):
            return JsonResponse({'success': False, 'error': 'Invalid assignments payload.'}, status=400)

        updated_count = 0
        for assignment in assignments:
            image_id = assignment.get('image_id')
            product_id = assignment.get('product_id')

            if not image_id or not product_id:
                continue

            Product.objects.filter(id=product_id).update(featured_image_id=image_id)
            updated_count += 1

        logger.info(f"Bulk auto-assign featured images processed {updated_count} assignments.")

        # Return refreshed products list so frontend can sync state
        all_products_qs = Product.objects.all().prefetch_related('gallery_images').select_related('featured_image')
        all_products_list = [
            {
                'id': p.id,
                'name': p.name,
                'sku': p.sku or '-',
                'featured_image_id': p.featured_image_id,
                'featured_image_title': p.featured_image.title if p.featured_image else None,
                'gallery_image_ids': list(p.gallery_images.all().values_list('id', flat=True))
            } for p in all_products_qs
        ]

        return JsonResponse({
            'success': True,
            'message': 'Featured images auto-assigned successfully.',
            'all_products': all_products_list
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON.'}, status=400)
    except Exception as e:
        logger.error(f"Error in ajax_bulk_auto_assign: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@staff_required
def ajax_edit_image(request, image_id):
    """
    Handles POST request to update an image's details (title, alt_text, category).
    """
    if request.method != 'POST' or not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=400)

    image = get_object_or_404(MediaImage, pk=image_id)

    try:
        data = json.loads(request.body)

        # Get data from the payload
        title = data.get('title', '').strip()
        alt_text = data.get('alt_text', '').strip()
        category_id = data.get('category_id') # Can be null/None

        if not title:
            return JsonResponse({'success': False, 'error': 'Title is required.'}, status=400)

        # Update the instance
        image.title = title
        image.alt_text = alt_text

        # Handle category (it's a ForeignKey)
        if category_id:
            # Ensure the category exists before assigning
            image.category = get_object_or_404(ImageCategory, pk=category_id)
        else:
            image.category = None

        image.save()

        # Return the updated object, serialized
        serialized_image = {
            'id': image.id,
            'title': image.title,
            'url': image.image.url,
            'alt_text': image.alt_text,
            'category_id': image.category_id,
            'category_name': image.category.name if image.category else 'Uncategorized',
            'assigned_to': [], # <--- Maintain structure (assignments don't change on edit details)
        }

        return JsonResponse({'success': True, 'image': serialized_image})

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON.'}, status=400)
    except Exception as e:
        logger.error(f"Error in ajax_edit_image for image {image_id}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
