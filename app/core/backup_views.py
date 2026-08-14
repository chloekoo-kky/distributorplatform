"""Admin views for full-site backup create/download and upload/restore."""
from __future__ import annotations

import logging
import os
import shutil
import tempfile

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, HttpResponseForbidden
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from .backup import BackupError, create_backup_archive, restore_backup_archive

logger = logging.getLogger(__name__)


def _require_superuser(request):
    if not request.user.is_authenticated or not request.user.is_superuser:
        raise PermissionDenied


@require_POST
def backup_create_view(request):
    """Create a full backup (DB + media) and stream it as a zip download."""
    _require_superuser(request)

    try:
        zip_path, download_name = create_backup_archive()
    except BackupError as exc:
        messages.error(request, f'Backup failed: {exc}')
        return redirect('admin:index')
    except Exception:
        logger.exception('Unexpected backup create failure')
        messages.error(request, 'Backup failed due to an unexpected error. Check server logs.')
        return redirect('admin:index')

    tmp_dir = os.path.dirname(zip_path)
    try:
        response = FileResponse(
            open(zip_path, 'rb'),  # noqa: SIM115 — closed by FileResponse
            as_attachment=True,
            filename=download_name,
            content_type='application/zip',
        )
        response._resource_closers.append(
            lambda: shutil.rmtree(tmp_dir, ignore_errors=True)
        )
        return response
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


@require_POST
def backup_restore_view(request):
    """
    Upload a backup zip and replace the local DB + media.

    Hard-blocked when DJANGO_DEBUG is False so production cannot wipe itself.
    """
    _require_superuser(request)

    if not settings.DEBUG:
        return HttpResponseForbidden(
            'Upload & restore is disabled when DJANGO_DEBUG=False '
            '(live cannot wipe itself from the admin UI).'
        )

    if request.POST.get('confirm') != 'on':
        messages.error(request, 'Restore cancelled: confirmation checkbox is required.')
        return redirect('admin:index')

    upload = request.FILES.get('backup_file')
    if not upload:
        messages.error(request, 'Please choose a backup .zip file to upload.')
        return redirect('admin:index')

    if not upload.name.lower().endswith('.zip'):
        messages.error(request, 'Backup file must be a .zip archive.')
        return redirect('admin:index')

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip', prefix='dp-upload-') as tmp:
            for chunk in upload.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        summary = restore_backup_archive(tmp_path)
        messages.success(
            request,
            f'{summary} You may need to log in again with an account from the restored backup.',
        )
    except BackupError as exc:
        messages.error(request, f'Restore failed: {exc}')
    except Exception:
        logger.exception('Unexpected backup restore failure')
        messages.error(request, 'Restore failed due to an unexpected error. Check server logs.')
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return redirect('admin:index')
