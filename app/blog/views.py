# distributorplatform/app/blog/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Post
from .forms import PostForm
from inventory.views import staff_required
from django.db.models import Q, ProtectedError
from django.http import Http404, JsonResponse
from django.urls import reverse
from django.utils.text import slugify
import json
import os
import traceback
from django.core.paginator import Paginator, EmptyPage
from django.views.decorators.http import require_POST, require_GET

from django.core.files.base import ContentFile

from images.forms import ImageUploadForm
from product.models import Product

def get_accessible_posts(user):
    """
    Helper function to get all posts accessible by a specific user.
    """
    base_query = Post.objects.filter(status=Post.PostStatus.PUBLISHED).prefetch_related('user_groups')

    if user.is_authenticated and not user.is_anonymous:
        user_groups = user.user_groups.all()
        return base_query.filter(
            Q(user_groups=None) | Q(user_groups__in=user_groups)
        ).distinct()
    else:
        return base_query.filter(user_groups=None).distinct()

def post_list(request):
    """
    Public page showing all PUBLISHED posts of type 'NEWS'.
    Now includes sidebar data.
    """
    all_accessible = get_accessible_posts(request.user)

    # Main Content: Latest News
    posts = all_accessible.filter(
        post_type=Post.PostType.MARKET_INSIGHTS
    ).order_by('-created_at')

    # --- SIDEBAR DATA ---
    announcements = all_accessible.filter(
        post_type=Post.PostType.ANNOUNCEMENT
    ).order_by('-created_at')[:3]

    featured_products = Product.objects.filter(
        is_featured=True
    ).select_related('featured_image').order_by('-created_at')[:5]

    context = {
        'posts': posts,
        'announcements': announcements,
        'featured_products': featured_products,
    }
    return render(request, 'blog/post_list.html', context)

def post_detail(request, slug):
    """
    Public page showing a single PUBLISHED blog post.
    Now includes sidebar data.
    """
    # Retrieve the post first to check permissions
    post = get_object_or_404(
        Post.objects.prefetch_related(
            'user_groups',
            'related_products', # Prefetch the products
            'related_products__featured_image', # Prefetch product images
            'featured_image'
        ),
        slug=slug,
        status=Post.PostStatus.PUBLISHED
    )
    # Permission Check
    if not post.is_public:
        if not request.user.is_authenticated or request.user.is_anonymous:
            raise Http404
        if not request.user.user_groups.filter(id__in=post.user_groups.all()).exists():
            raise Http404

    # --- SIDEBAR DATA ---
    all_accessible = get_accessible_posts(request.user)

    announcements = all_accessible.filter(
        post_type=Post.PostType.ANNOUNCEMENT
    ).order_by('-created_at')[:3]

    sidebar_posts = all_accessible.filter(
        featured_image__isnull=False,
        post_type=Post.PostType.NEWS
    ).order_by('-created_at')[:5]

    context = {
        'post': post,
        'announcements': announcements,
        'sidebar_posts': sidebar_posts,
    }
    return render(request, 'blog/post_detail.html', context)

def manage_post_create(request):
    if request.method == 'POST':
        form = PostForm(request.POST)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.save()
            form.save_m2m()
            messages.success(request, f"Blog post '{post.title}' created successfully.")
            # FIX: Updated to 'core:manage_dashboard' to prevent NoReverseMatch error
            return redirect(reverse('core:manage_dashboard') + '#blog')
    else:
        form = PostForm()

    image_upload_form = ImageUploadForm()
    context = {
        'form': form,
        'title': 'Create New Blog Post',
        'is_subpage': True,
        'image_upload_form': image_upload_form,
    }
    return render(request, 'blog/manage_blog_form.html', context)

def manage_post_edit(request, post_id):
    post = get_object_or_404(Post, pk=post_id)
    if request.method == 'POST':
        form = PostForm(request.POST, instance=post)
        if form.is_valid():
            form.save()
            messages.success(request, f"Blog post '{post.title}' updated successfully.")
            # FIX: Updated to 'core:manage_dashboard' to prevent NoReverseMatch error
            return redirect(reverse('core:manage_dashboard') + '#blog')
    else:
        form = PostForm(instance=post)

    image_upload_form = ImageUploadForm()
    context = {
        'form': form,
        'title': f"Editing: {post.title}",
        'post': post,
        'is_subpage': True,
        'image_upload_form': image_upload_form,
    }
    return render(request, 'blog/manage_blog_form.html', context)

def manage_post_delete(request, post_id):
    post = get_object_or_404(Post, pk=post_id)
    if request.method == 'POST':
        title = post.title
        post.delete()
        messages.success(request, f"Blog post '{title}' has been deleted.")
    # FIX: Updated to 'core:manage_dashboard' to prevent NoReverseMatch error
    return redirect(reverse('core:manage_dashboard') + '#blog')

def api_manage_posts(request):
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    search_query = request.GET.get('search', '')
    page_number = request.GET.get('page', 1)
    limit = request.GET.get('limit', 50)

    queryset = Post.objects.all().select_related(
        'author', 'featured_image'
    ).prefetch_related(
        'user_groups', 'gallery_images'
    ).order_by('-created_at')

    if search_query:
        queryset = queryset.filter(title__icontains=search_query)

    queryset = queryset.distinct()

    paginator = Paginator(queryset, limit)
    try:
        page_obj = paginator.page(page_number)
    except EmptyPage:
        return JsonResponse({'items': [], 'pagination': {}})

    serialized_posts = []
    for post in page_obj.object_list:
        post_data = {
            'id': post.pk,
            'title': post.title,
            'status': post.status,
            'is_public': post.is_public,
            'author': post.author.username if post.author else 'N/A',
            'created_at': post.created_at.strftime('%Y-%m-%d'),
            'user_groups': [group.name for group in post.user_groups.all()],
            'featured_image_id': post.featured_image_id,
            'gallery_image_ids': list(post.gallery_images.all().values_list('id', flat=True)),
            'edit_url': reverse('blog:manage_post_edit', args=[post.id]),
            'view_url': post.get_absolute_url(),
            'delete_url': reverse('blog:manage_post_delete', args=[post.id]),
        }
        serialized_posts.append(post_data)

    return JsonResponse({
        'items': serialized_posts,
        'pagination': {
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
        }
    })


@staff_required
@require_GET
def api_get_post_details(request, post_id):
    """Fetch details of a post for editing in modal."""
    post = get_object_or_404(Post, pk=post_id)
    data = {
        'id': post.id,
        'title': post.title,
        'slug': post.slug,
        'content': post.content,
        'post_type': post.post_type,
        'is_published': post.status == Post.PostStatus.PUBLISHED,
        'featured_image': post.featured_image.id if post.featured_image else None,
        'featured_image_url': post.featured_image.image.url if post.featured_image else '',
        'user_groups': list(post.user_groups.values_list('id', flat=True)),
        'related_products': list(post.related_products.values_list('id', flat=True)),
        'related_products_title': post.related_products_title,
    }
    return JsonResponse(data)

@staff_required
@require_POST
def api_save_post(request, post_id=None):
    """Create or update a post via API."""
    try:
        data = json.loads(request.body)

        # 1. Handle Slug Generation Logic manually before form validation
        slug = data.get('slug', '').strip()
        if not slug and data.get('title'):
            slug = slugify(data.get('title'))
            original_slug = slug
            counter = 1
            # Check for uniqueness, excluding current post if editing
            qs = Post.objects.filter(slug=slug)
            if post_id:
                qs = qs.exclude(pk=post_id)

            while qs.exists():
                slug = f'{original_slug}-{counter}'
                counter += 1
                qs = Post.objects.filter(slug=slug)
                if post_id:
                    qs = qs.exclude(pk=post_id)

        # 2. Handle featured_image normalization (empty string -> None)
        featured_image = data.get('featured_image')
        if featured_image == "":
            featured_image = None

        # Prepare data for Form
        form_data = {
            'title': data.get('title'),
            'slug': slug,
            'content': data.get('content', ''),
            'post_type': data.get('post_type', 'NEWS'),
            'is_published': data.get('is_published', False),
            'related_products_title': data.get('related_products_title', ''),
            'featured_image': featured_image,
        }

        if post_id:
            post = get_object_or_404(Post, pk=post_id)
            form = PostForm(data=form_data, instance=post)
        else:
            form = PostForm(data=form_data)

        if form.is_valid():
            post = form.save(commit=False)
            if not post_id:
                post.author = request.user

            # Ensure manually generated slug is saved
            post.slug = slug
            post.save()

            if 'user_groups' in data:
                post.user_groups.set(data['user_groups'])
            if 'related_products' in data:
                post.related_products.set(data['related_products'])
            if 'gallery_images' in data:
                post.gallery_images.set(data['gallery_images'])

            return JsonResponse({'success': True, 'message': 'Post saved successfully!'})
        else:
            return JsonResponse({'success': False, 'errors': form.errors}, status=400)

    except Exception as e:
        # Print error for debugging
        print("API Save Post Error:")
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
