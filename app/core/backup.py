"""
Full-site backup helpers: PostgreSQL dump + media files in a zip archive.

Used by Django admin create/download and upload/restore views.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import django
from django.conf import settings
from django.db import connection, connections

logger = logging.getLogger(__name__)

BACKUP_FORMAT = 'distributorplatform-backup'
BACKUP_FORMAT_VERSION = 1
MANIFEST_NAME = 'manifest.json'
DB_DUMP_NAME = 'database.dump'
MEDIA_PREFIX = 'media/'


class BackupError(Exception):
    """Raised when backup create or restore fails."""


def _db_settings():
    db = settings.DATABASES['default']
    return {
        'NAME': db['NAME'],
        'USER': db['USER'],
        'PASSWORD': db.get('PASSWORD') or '',
        'HOST': db.get('HOST') or 'localhost',
        'PORT': str(db.get('PORT') or '5432'),
    }


def _pg_env():
    db = _db_settings()
    env = os.environ.copy()
    env['PGPASSWORD'] = db['PASSWORD']
    env['PGHOST'] = db['HOST']
    env['PGPORT'] = db['PORT']
    env['PGUSER'] = db['USER']
    env['PGDATABASE'] = db['NAME']
    return env


def _require_pg_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise BackupError(
            f"'{name}' was not found on PATH. Rebuild the app image so "
            'postgresql-client is installed.'
        )
    return path


def create_backup_archive() -> tuple[str, str]:
    """
    Build a zip containing database.dump + media/ + manifest.json.

    Returns (temp_file_path, download_filename).
    Caller must delete the temp file after the response is sent.
    """
    pg_dump = _require_pg_tool('pg_dump')
    db = _db_settings()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    download_name = f'distributorplatform-backup-{stamp}.zip'

    tmp_dir = tempfile.mkdtemp(prefix='dp-backup-')
    dump_path = os.path.join(tmp_dir, DB_DUMP_NAME)
    zip_path = os.path.join(tmp_dir, download_name)

    try:
        result = subprocess.run(
            [
                pg_dump,
                '--format=custom',
                '--no-owner',
                '--no-acl',
                '--file', dump_path,
                db['NAME'],
            ],
            env=_pg_env(),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise BackupError(
                f'pg_dump failed (exit {result.returncode}): '
                f'{(result.stderr or result.stdout or "").strip()}'
            )

        manifest = {
            'format': BACKUP_FORMAT,
            'version': BACKUP_FORMAT_VERSION,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'django_version': django.get_version(),
            'database_name': db['NAME'],
            'includes_media': True,
        }

        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
            zf.write(dump_path, arcname=DB_DUMP_NAME)

            media_root = Path(settings.MEDIA_ROOT)
            if media_root.is_dir():
                for path in media_root.rglob('*'):
                    if path.is_file():
                        arcname = MEDIA_PREFIX + path.relative_to(media_root).as_posix()
                        zf.write(path, arcname=arcname)

        return zip_path, download_name
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def _validate_backup_zip(zf: zipfile.ZipFile) -> dict:
    names = set(zf.namelist())
    if MANIFEST_NAME not in names:
        raise BackupError('Invalid backup: missing manifest.json')
    if DB_DUMP_NAME not in names:
        raise BackupError('Invalid backup: missing database.dump')

    try:
        manifest = json.loads(zf.read(MANIFEST_NAME).decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError(f'Invalid backup: cannot read manifest ({exc})') from exc

    if manifest.get('format') != BACKUP_FORMAT:
        raise BackupError('Invalid backup: unrecognized format')
    if int(manifest.get('version', 0)) != BACKUP_FORMAT_VERSION:
        raise BackupError(
            f"Unsupported backup version {manifest.get('version')}; "
            f'expected {BACKUP_FORMAT_VERSION}'
        )
    return manifest


def _clear_media_root() -> None:
    media_root = Path(settings.MEDIA_ROOT)
    media_root.mkdir(parents=True, exist_ok=True)
    for child in media_root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _extract_media(zf: zipfile.ZipFile) -> int:
    media_root = Path(settings.MEDIA_ROOT)
    media_root.mkdir(parents=True, exist_ok=True)
    count = 0
    for info in zf.infolist():
        name = info.filename
        if info.is_dir() or not name.startswith(MEDIA_PREFIX):
            continue
        rel = name[len(MEDIA_PREFIX):]
        if not rel or rel.endswith('/'):
            continue
        # Prevent zip-slip
        dest = (media_root / rel).resolve()
        try:
            dest.relative_to(media_root.resolve())
        except ValueError as exc:
            raise BackupError(f'Invalid media path in backup: {name}') from exc
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(dest, 'wb') as out:
            shutil.copyfileobj(src, out)
        count += 1
    return count


def _terminate_other_db_sessions() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid <> pg_backend_pid()
              AND backend_type = 'client backend'
            """
        )


def restore_backup_archive(uploaded_path: str) -> str:
    """
    Replace the current database and media from a backup zip.

    Only call this when settings.DEBUG is True (enforced by the view).
    Returns a short success summary for messages.
    """
    if not settings.DEBUG:
        raise BackupError('Restore is blocked when DJANGO_DEBUG is False.')

    pg_restore = _require_pg_tool('pg_restore')
    db = _db_settings()

    with tempfile.TemporaryDirectory(prefix='dp-restore-') as tmp_dir:
        dump_path = os.path.join(tmp_dir, DB_DUMP_NAME)

        with zipfile.ZipFile(uploaded_path, 'r') as zf:
            _validate_backup_zip(zf)
            with zf.open(DB_DUMP_NAME) as src, open(dump_path, 'wb') as out:
                shutil.copyfileobj(src, out)

            # Close Django DB connections before destructive restore.
            connections.close_all()
            _terminate_other_db_sessions()
            connections.close_all()

            result = subprocess.run(
                [
                    pg_restore,
                    '--clean',
                    '--if-exists',
                    '--no-owner',
                    '--no-acl',
                    '--dbname', db['NAME'],
                    dump_path,
                ],
                env=_pg_env(),
                capture_output=True,
                text=True,
                check=False,
            )
            # pg_restore often exits 1 with non-fatal warnings; treat only
            # hard failures (exit >= 2, or empty DB) as errors.
            if result.returncode >= 2:
                raise BackupError(
                    f'pg_restore failed (exit {result.returncode}): '
                    f'{(result.stderr or result.stdout or "").strip()}'
                )

            connections.close_all()
            _clear_media_root()
            media_count = _extract_media(zf)

        warning = (result.stderr or '').strip()
        summary = f'Database restored; {media_count} media file(s) extracted.'
        if warning and result.returncode != 0:
            logger.warning('pg_restore warnings: %s', warning)
            summary += ' (pg_restore reported non-fatal warnings; check logs.)'
        return summary
