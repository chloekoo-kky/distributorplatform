# distributorplatform/app/blog/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Post
from .forms import PostForm
from inventory.views import staff_required
from django.db.models import Q, ProtectedError
from django.http import Http404, JsonResponse
from django.urls import reverse
import json
import os
from django.core.paginator import Paginator, EmptyPage

from django.core.files.base import ContentFile

from images.forms import ImageUploadForm

# ... (get_accessible_posts, post_list, post_detail views are unchanged) ...
def get_accessible_posts(user):
    """
    Helper function to get all posts accessible by a specific user.
    """
    base_query = Post.objects.filter(status=Post.PostStatus.PUBLISHED).prefetch_related('user_groups')

    if user.is_authenticated and not user.is_anonymous:
        # Get the user's groups
        user_groups = user.user_groups.all()
        # Show posts that are public (no groups) OR are in the user's groups
        return base_query.filter(
            Q(user_groups=None) | Q(user_groups__in=user_groups)
        ).distinct()
    else:
        # For anonymous users, only show public posts (no groups)
        return base_query.filter(user_groups=None).distinct()

def post_list(request):
    """
    Public page showing all PUBLISHED blog posts.
    """
    posts = get_accessible_posts(request.user)
    context = {
        'posts': posts,
    }
    return render(request, 'blog/post_list.html', context)

def post_detail(request, slug):
    """
    Public page showing a single PUBLISHED blog post.
    """
    post = get_object_or_404(Post.objects.prefetch_related('user_groups'),
                             slug=slug,
                             status=Post.PostStatus.PUBLISHED)

    if post.is_public:
        pass
    elif not request.user.is_authenticated or request.user.is_anonymous:
        raise Http404
    elif not request.user.user_groups.filter(id__in=post.user_groups.all()).exists():
        raise Http404

    context = {
        'post': post,
    }
    return render(request, 'blog/post_detail.html', context)


@staff_required
def manage_post_create(request):
    if request.method == 'POST':
        form = PostForm(request.POST)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.save()
            form.save_m2m()
            messages.success(request, f"Blog post '{post.title}' created successfully.")

            # --- START MODIFICATION ---
            return redirect(reverse('manage_dashboard') + '#blog')
            # --- END MODIFICATION ---
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

@staff_required
def manage_post_edit(request, post_id):
    post = get_object_or_404(Post, pk=post_id)
    if request.method == 'POST':
        form = PostForm(request.POST, instance=post)
        if form.is_valid():
            form.save()
            messages.success(request, f"Blog post '{post.title}' updated successfully.")

            # --- START MODIFICATION ---
            return redirect(reverse('manage_dashboard') + '#blog')
            # --- END MODIFICATION ---
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

@staff_required
def manage_post_delete(request, post_id):
    post = get_object_or_404(Post, pk=post_id)
    if request.method == 'POST':
        title = post.title
        post.delete()
        messages.success(request, f"Blog post '{title}' has been deleted.")

    # --- START MODIFICATION ---
    return redirect(reverse('manage_dashboard') + '#blog')
    # --- END MODIFICATION ---

@staff_required
def api_manage_posts(request):
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    # --- 1. Get Filters ---
    search_query = request.GET.get('search', '')
    page_number = request.GET.get('page', 1)
    limit = request.GET.get('limit', 50) # Default to 50

    # --- 2. Build Base Queryset ---
    queryset = Post.objects.all().select_related(
        'author', 'featured_image'
    ).prefetch_related(
        'user_groups', 'gallery_images'
    ).order_by('-created_at')

    # --- 3. Apply Filters ---
    if search_query:
        queryset = queryset.filter(title__icontains=search_query)

    queryset = queryset.distinct()

    # --- 4. Paginate ---
    paginator = Paginator(queryset, limit)
    try:
        page_obj = paginator.page(page_number)
    except EmptyPage:
        return JsonResponse({'items': [], 'pagination': {}})

    # --- 5. Serialize ---
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

    # --- 6. Return JSON ---
    return JsonResponse({
        'items': serialized_posts,
        'pagination': {
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
        }
    })
