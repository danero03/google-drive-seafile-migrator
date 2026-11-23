#!/usr/bin/env python3
"""Unified Google Drive -> Seafile migration: plan, run, verify.

Requires Python 3.9+, rclone 1.76+, configured gdrive: and seafile: (Media).
Read-only source; no delete/overwrite operations. Uses Google Drive file IDs to
preserve duplicate source names. Compatible with v4 manifests and v5 state.
"""
import argparse
import collections
import concurrent.futures
import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request

ROOT_DEFAULT = '25_E7_5I-1i-UqOzf2UP1JFLOxBa7NGWM'
FOLDER = 'application/vnd.google-apps.folder'
SHORTCUT = 'application/vnd.google-apps.shortcut'
EXPORTS = {
    'application/vnd.google-apps.document': '.docx',
    'application/vnd.google-apps.spreadsheet': '.xlsx',
    'application/vnd.google-apps.presentation': '.pptx',
    'application/vnd.google-apps.drawing': '.svg',
}
DEFAULT_WORK = Path.home() / 'rclone-migration-duplicates'
TRANSIENT = ('failed to authenticate', '429', 'too many requests', 'rate limit',
             '502', '503', '504', 'timed out', 'timeout', 'connection reset',
             'connection refused', 'eof', 'temporarily unavailable', 'broken pipe')


def run(cmd, capture=True):
    p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.PIPE if capture else None)
    if p.returncode:
        detail = (p.stderr or p.stdout or '').strip()[-1200:]
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd[:3])}\n{detail}")
    return p.stdout if capture else ''

def safe_name(name):
    # Keep Unicode filenames while avoiding invalid names and traversal.
    name = unicodedata.normalize('NFC', str(name)).replace('/', '／').replace('\\', '＼')
    name = name.replace('\x00', '').strip()
    if name in ('', '.', '..'):
        name = '_unnamed_'
    return name


def key(name):
    return unicodedata.normalize('NFC', name).casefold()


def hashed_name(name, drive_id, used):
    name = safe_name(name)
    stem, ext = os.path.splitext(name)
    digest = hashlib.sha256(drive_id.encode()).hexdigest()[:10]
    candidate = f'{stem}__id_{digest}{ext}'
    i = 2
    while key(candidate) in used:
        candidate = f'{stem}__id_{digest}_{i}{ext}'
        i += 1
    return candidate


def atomic_json(path, obj):
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(temp, path)


def query_children(folder_id, remote, attempts=5):
    expr = f"'{folder_id}' in parents and trashed = false"
    for attempt in range(1, attempts + 1):
        try:
            raw = run(['rclone', 'backend', 'query', remote, expr])
            value = json.loads(raw)
            if value is None:
                # Rclone's Drive backend may encode an empty result slice as JSON null.
                # This is not the same as a failed command (run() checks exit status).
                # Log the folder ID so an operator can audit empty folders later.
                print(f'NOTICE: query returned null for folder {folder_id}; treating as empty. Verify this folder if unexpected.', flush=True)
                items = []
            elif isinstance(value, list):
                items = value
            elif isinstance(value, dict):
                # Some wrappers expose Drive API style responses with a `files` key.
                # Do not mistake an error or unexpected response for an empty folder.
                if isinstance(value.get('files'), list) and not value.get('nextPageToken'):
                    items = value['files']
                elif value.get('nextPageToken'):
                    raise RuntimeError('query response is paginated; refusing incomplete inventory')
                else:
                    keys = ', '.join(sorted(value.keys()))
                    err = value.get('error', value.get('message', ''))
                    raise RuntimeError(f'unexpected query response object (keys: {keys}; error: {str(err)[:350]})')
            else:
                raise RuntimeError(f'backend query returned unexpected JSON type {type(value).__name__}')
            if not all(isinstance(item, dict) for item in items):
                raise RuntimeError('backend query list contains non-object entries')
            return items
        except (RuntimeError, ValueError) as e:
            if attempt == attempts:
                raise RuntimeError(f'Cannot list folder {folder_id}: {e}') from e
            time.sleep(min(3 * attempt, 15))


def plan(root_id, remote, dest_dir):
    folders = []
    files = []
    unsupported = []
    seen = set()
    active = set()
    queue = collections.deque([(root_id, dest_dir)])
    duplicated = 0
    while queue:
        parent_id, prefix = queue.popleft()
        if parent_id in active or parent_id in seen:
            continue
        active.add(parent_id)
        children = query_children(parent_id, remote)
        children.sort(key=lambda o: (key(safe_name(o.get('name', ''))), str(o.get('id', ''))))
        used = set()
        for child in children:
            object_id = child.get('id')
            mime = child.get('mimeType')
            if not isinstance(object_id, str) or not object_id:
                raise RuntimeError(f'Missing id for object in folder {parent_id}')
            original = safe_name(child.get('name', 'unnamed'))
            if mime in EXPORTS:
                original += EXPORTS[mime]
            chosen = original
            if key(chosen) in used:
                chosen = hashed_name(original, object_id, used)
                duplicated += 1
            used.add(key(chosen))
            rel = prefix + '/' + chosen if prefix else chosen
            record = {'id': object_id, 'path': rel, 'name': child.get('name', ''),
                      'mimeType': mime, 'size': child.get('size'), 'parent_id': parent_id}
            if mime == FOLDER:
                folders.append(record)
                queue.append((object_id, rel))
            elif mime == SHORTCUT:
                unsupported.append({**record, 'reason': 'Google Drive shortcut (not copied)'})
            elif isinstance(mime, str) and mime.startswith('application/vnd.google-apps.') and mime not in EXPORTS:
                unsupported.append({**record, 'reason': 'Unsupported Google native document type'})
            else:
                files.append(record)
        active.remove(parent_id)
        seen.add(parent_id)
        if len(seen) % 25 == 0:
            print(f'Inventoried {len(seen)} folders / {len(files)} files...', flush=True)
    return {'root_id': root_id, 'source': remote, 'target_dir': dest_dir,
            'generated': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'folders': folders, 'files': files, 'unsupported': unsupported,
            'renamed_duplicates': duplicated}



def atomic_json(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', encoding='utf8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def short_error(exc):
    return str(exc).replace('\n', ' ')[-500:]


class APIError(RuntimeError):
    pass


class RC:
    def __init__(self, rclone='rclone', attempts=7, retry_wait=5.0, delay=0.2):
        self.rclone = rclone
        self.attempts = attempts
        self.retry_wait = retry_wait
        self.delay = delay
        self.proc = None
        self.port = None
        self.lock = threading.Lock()
        self.last = 0.0
        self.log_file = None

    def __enter__(self):
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        self.port = sock.getsockname()[1]
        sock.close()
        self.log_file = open(os.devnull, 'w')
        self.proc = subprocess.Popen([
            self.rclone, 'rcd', '--rc-addr', f'127.0.0.1:{self.port}',
            '--rc-no-auth', '--log-level', 'ERROR',
        ], stdin=subprocess.DEVNULL, stdout=self.log_file, stderr=self.log_file)
        for _ in range(100):
            if self.proc.poll() is not None:
                raise RuntimeError('rclone rcd exited before readiness; check rclone version')
            try:
                self.once('rc/noop', {}, timeout=2)
                return self
            except Exception:
                time.sleep(0.15)
        raise RuntimeError('rclone RC did not start on local loopback')

    def __exit__(self, typ, value, tb):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if self.log_file:
            self.log_file.close()

    def once(self, method, payload, timeout=3600):
        raw = json.dumps(payload).encode('utf8')
        req = urllib.request.Request(
            f'http://127.0.0.1:{self.port}/{method}',
            data=raw, headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = response.read()
        except urllib.error.HTTPError as exc:
            message = exc.read().decode('utf8', 'replace')
            raise APIError(f'RC HTTP {exc.code}: {message[-800:]}') from exc
        try:
            answer = json.loads(data)
        except json.JSONDecodeError as exc:
            raise APIError(f'Invalid RC JSON: {data[:200]!r}') from exc
        if isinstance(answer, dict) and ('error' in answer) and answer['error']:
            raise APIError(str(answer['error']))
        return answer

    def call(self, method, payload, timeout=3600):
        for attempt in range(1, self.attempts + 1):
            with self.lock:
                waiting = self.delay - (time.monotonic() - self.last)
                if waiting > 0:
                    time.sleep(waiting)
                self.last = time.monotonic()
            try:
                return self.once(method, payload, timeout)
            except (APIError, urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                msg = str(exc).lower()
                temporary = any(term in msg for term in TRANSIENT)
                if attempt >= self.attempts or not temporary:
                    raise
                wait = min(self.retry_wait * (2 ** (attempt - 1)), 90)
                print(f'RETRY {attempt}/{self.attempts} after {wait:.0f}s: '
                      f'{method}: {short_error(exc)}', file=sys.stderr, flush=True)
                time.sleep(wait)


def normalize_path(p):
    return p.replace('\\', '/').strip('/')


def validate_manifest(manifest):
    if not isinstance(manifest, dict):
        raise RuntimeError('Invalid manifest object')
    required = ('root_id', 'source', 'target_dir', 'files', 'folders')
    if any(k not in manifest for k in required):
        raise RuntimeError('Manifest missing required fields')
    if manifest['source'] != 'gdrive:':
        raise RuntimeError('Only gdrive: source is supported by this script')
    if not isinstance(manifest['files'], list) or not isinstance(manifest['folders'], list):
        raise RuntimeError('Bad manifest arrays')
    target = normalize_path(manifest['target_dir'])
    if target != 'GoogleDrive-Import':
        raise RuntimeError('Safety check: expected target_dir=GoogleDrive-Import')
    all_paths = set()
    ids = set()
    for item in [*manifest['folders'], *manifest['files']]:
        name = item.get('path', '')
        path = normalize_path(name)
        if path != name or not path.startswith(target + '/') or any(x in ('', '.', '..') for x in path.split('/')):
            raise RuntimeError(f'Unsafe manifest path: {name!r}')
        if path.casefold() in all_paths:
            raise RuntimeError(f'Duplicate target path in manifest: {path}')
        all_paths.add(path.casefold())
        if item.get('id') in ids or not item.get('id'):
            raise RuntimeError('Missing/duplicate Drive ID')
        ids.add(item['id'])
    return target


def dest_entries(rclone, destination, target):
    """Read-only listing of all files and folders, keyed relative to target.

    Unlike the previous operations/list implementation this does not depend
    on RC Path prefix conventions, which caused false missing-file errors.
    """
    location = destination + target
    entries = {}
    for flag, directory in [('--files-only', False), ('--dirs-only', True)]:
        raw = run([rclone, 'lsjson', location, '--recursive', flag])
        items = json.loads(raw)
        if not isinstance(items, list):
            raise RuntimeError('rclone lsjson returned an unexpected response')
        for obj in items:
            p = normalize_path(obj.get('Path') or '')
            if not p:
                continue
            if p == target or p.startswith(target + '/'):
                p = p[len(target):].lstrip('/')
            if p in entries:
                raise RuntimeError(f'Duplicate Seafile path: {p}')
            if bool(obj.get('IsDir')) != directory:
                raise RuntimeError(f'Unexpected directory flag on {p}')
            entries[p] = obj
    return entries


def matches_size(f, stat):
    if not stat or stat.get('IsDir'):
        return False
    if f.get('size') is None:
        return True  # Google native docs: no source size; only verify presence
    try:
        return int(f['size']) == int(stat['Size'])
    except (ValueError, KeyError, TypeError):
        return False



def main():
    ap = argparse.ArgumentParser(description=__doc__)
    modes = ap.add_mutually_exclusive_group(required=True)
    modes.add_argument('--plan', action='store_true', help='Create manifest without uploading; reuse if present')
    modes.add_argument('--run', action='store_true', help='Upload missing files; auto-create manifest if missing')
    modes.add_argument('--verify', action='store_true', help='Read-only audit of destination; auto-create manifest if missing')
    ap.add_argument('--root-id', default=ROOT_DEFAULT, help='Original shared Google Drive folder ID')
    ap.add_argument('--source', default='gdrive:')
    ap.add_argument('--workdir', default=str(DEFAULT_WORK))
    ap.add_argument('--destination', default='seafile:', help='Configured Seafile Media library remote')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--request-delay', type=float, default=0.5)
    ap.add_argument('--retries', type=int, default=7)
    ap.add_argument('--retry-wait', type=float, default=10)
    ap.add_argument('--rclone', default='rclone')
    args = ap.parse_args()
    if not 1 <= args.workers <= 20 or args.request_delay < 0 or args.retries < 1 or args.retry_wait < 0:
        ap.error('Invalid concurrency/retry settings')
    if args.destination != 'seafile:' or args.source != 'gdrive:':
        ap.error('Safety check requires gdrive: source and seafile: (Media library) destination')
    if args.root_id != ROOT_DEFAULT:
        ap.error('Safety check: unexpected source folder ID')

    work = Path(args.workdir).expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(work, 0o700)
    manifest_file = work / 'manifest.json'
    target = 'GoogleDrive-Import'
    if not manifest_file.is_file():
        print('Manifest not found: inventorying Google Drive (read-only)...', flush=True)
        manifest = plan(args.root_id, args.source, target)
        validate_manifest(manifest)
        atomic_json(manifest_file, manifest)
        print(f"Manifest created: {manifest_file} | folders={len(manifest['folders'])} "
              f"files={len(manifest['files'])} collisions={manifest['renamed_duplicates']} "
              f"unsupported={len(manifest['unsupported'])}", flush=True)
    else:
        manifest = json.loads(manifest_file.read_text(encoding='utf8'))
        print(f'Using existing manifest: {manifest_file}', flush=True)
    target = validate_manifest(manifest)
    if manifest['root_id'] != args.root_id or manifest['source'] != args.source:
        raise RuntimeError('Manifest belongs to a different source; refusing to proceed')
    files = manifest['files']
    folders = manifest['folders']
    if args.plan:
        print(f"Plan: folders={len(folders)}, files={len(files)}, "
              f"collisions={manifest.get('renamed_duplicates', '?')}, "
              f"unsupported={len(manifest.get('unsupported', []))}")
        return 0

    state_file = work / 'state_v5.json'  # intentionally compatible with existing migration
    errors_file = work / 'errors_v6.json'  # preserve original v5 errors
    state = json.loads(state_file.read_text(encoding='utf8')) if state_file.exists() else {
        'destination': args.destination, 'root_id': manifest['root_id'], 'completed': {}
    }
    if state.get('destination') != args.destination or state.get('root_id') != manifest['root_id']:
        raise RuntimeError('State belongs to a different migration')
    if not isinstance(state.get('completed'), dict):
        raise RuntimeError('Invalid progress state')
    # Detect manifest regeneration that changed path mappings of previously-copied IDs.
    by_id = {f['id']: f['path'] for f in files}
    for fid, prev in state['completed'].items():
        if fid not in by_id or by_id[fid] != prev:
            raise RuntimeError('Manifest does not match v5 state for Drive ID ' + fid +
                               '; preserve data and reconcile before retrying')
    print(f'Migration: {len(folders)} folders / {len(files)} files -> {args.destination}{target}', flush=True)
    if args.run:
        # Allow a genuinely empty destination: create only the target directory.
        with RC(args.rclone, args.retries, args.retry_wait, args.request_delay) as setup_rc:
            target_stat = setup_rc.call('operations/stat', {'fs': args.destination, 'remote': target})
            target_obj = target_stat.get('item') if isinstance(target_stat, dict) else None
            if target_obj is None:
                setup_rc.call('operations/mkdir', {'fs': args.destination, 'remote': target})
            elif not target_obj.get('IsDir'):
                raise RuntimeError('Target is not a directory')
    print('Listing files and folders independently via rclone lsjson...', flush=True)
    existing = dest_entries(args.rclone, args.destination, target)
    print(f"Found {sum(not v['IsDir'] for v in existing.values())} files and "
          f"{sum(bool(v['IsDir']) for v in existing.values())} folders.", flush=True)
    errors = []
    for folder in folders:
        rel = folder['path'][len(target)+1:]
        ent = existing.get(rel)
        if args.verify and (not ent or not ent.get('IsDir')):
            errors.append({'type': 'folder', 'path': folder['path'], 'id': folder['id'],
                           'error': 'Missing folder'})

    completed = 0
    verified = 0
    if args.verify:
        for idx, file in enumerate(files, 1):
            rel = file['path'][len(target)+1:]
            obj = existing.get(rel)
            if not matches_size(file, obj):
                reason = 'Missing file' if not obj else f"Size/type mismatch: found size={obj.get('Size')}"
                errors.append({'type': 'file', 'id': file['id'], 'path': file['path'], 'error': reason})
                print(f'[{idx}/{len(files)}] ERROR {file["path"]}: {reason}', file=sys.stderr, flush=True)
            else:
                verified += 1
                if idx % 200 == 0:
                    print(f'[{idx}/{len(files)}] VERIFIED', flush=True)
    else:
        # Read-only destination listing above also ensures never overwrite unknown files.
        state_lock = threading.Lock()
        with RC(args.rclone, args.retries, args.retry_wait, args.request_delay) as rc:
            # Prepare only missing directories; no deletion.
            stat = rc.call('operations/stat', {'fs': args.destination, 'remote': target})
            obj = stat.get('item') if isinstance(stat, dict) else None
            if obj is None:
                rc.call('operations/mkdir', {'fs': args.destination, 'remote': target})
            elif not obj.get('IsDir'):
                raise RuntimeError('Destination target is not a directory')
            for idx, folder in enumerate(folders, 1):
                rel = folder['path'][len(target)+1:]
                obj = existing.get(rel)
                if obj:
                    if not obj.get('IsDir'):
                        errors.append({'type': 'folder', 'id': folder['id'], 'path': folder['path'],
                                       'error': 'Target path is a file'})
                    continue
                try:
                    rc.call('operations/mkdir', {'fs': args.destination, 'remote': folder['path']})
                    existing[rel] = {'IsDir': True, 'Path': rel}
                except Exception as exc:
                    errors.append({'type': 'folder', 'id': folder['id'], 'path': folder['path'],
                                   'error': short_error(exc)})
                    print(f'FOLDER ERROR [{idx}/{len(folders)}]: {short_error(exc)}', file=sys.stderr, flush=True)

            def process(pair):
                idx, file = pair
                fid, path = file['id'], file['path']
                rel = path[len(target)+1:]
                obj = existing.get(rel)
                with state_lock:
                    previous = state['completed'].get(fid)
                try:
                    if previous:
                        if previous != path or not matches_size(file, obj):
                            raise RuntimeError('Previously copied file missing or mismatched; refusing overwrite')
                        return ('verified', idx, path, None)
                    if obj is not None:
                        raise RuntimeError('Existing file not recorded in state; refusing overwrite')
                    rc.call('backend/command', {'command': 'copyid', 'fs': manifest['source'],
                                                'arg': [fid, args.destination + path]})
                    with state_lock:
                        state['completed'][fid] = path
                        atomic_json(state_file, state)
                    return ('copied', idx, path, None)
                except Exception as exc:
                    return ('error', idx, path, short_error(exc))

            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
                for status, idx, path, err in pool.map(process, enumerate(files, 1)):
                    if status == 'error':
                        errors.append({'type': 'file', 'id': files[idx-1]['id'], 'path': path, 'error': err})
                        print(f'[{idx}/{len(files)}] ERROR {path}: {err}', file=sys.stderr, flush=True)
                    elif status == 'copied':
                        completed += 1
                        print(f'[{idx}/{len(files)}] COPIED {path}', flush=True)
                    else:
                        verified += 1
                        if idx % 200 == 0:
                            print(f'[{idx}/{len(files)}] VERIFIED', flush=True)

    unsupported = manifest.get('unsupported', [])
    atomic_json(errors_file, errors)
    print(f'Finished: copied={completed}, verified={verified}, errors={len(errors)}, '
          f'unsupported={len(unsupported)}', flush=True)
    print(f'Manifest: {manifest_file} | Progress: {state_file} | Problems: {errors_file}', flush=True)
    if errors or unsupported:
        print('INCOMPLETE: consult errors_v6.json or manifest unsupported items.', file=sys.stderr)
        return 2
    print('SUCCESS: all expected paths and reported sizes matched.' if args.verify else
          'SUCCESS: completed according to Rclone; run --verify for a read-only audit.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('Interrupted; state retained.', file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f'FATAL: {short_error(exc)}', file=sys.stderr)
        sys.exit(1)
