#!/usr/bin/env python3
"""Print Rclone RC upload progress without changing migration or remote files."""
import argparse
from datetime import datetime
import json
import time
import urllib.error
import urllib.request


def rc(base, endpoint):
    request = urllib.request.Request(
        f'{base}/{endpoint}', data=b'{}',
        headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def item_path(item):
    return f"{item.get('dstFs', '').rstrip('/')}/{item.get('name', '?')}".lstrip('/')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, required=True, help='Port of the active rclone rcd process')
    p.add_argument('--interval', type=float, default=3.0)
    a = p.parse_args()
    if not (1 <= a.port <= 65535) or a.interval <= 0:
        p.error('Invalid port or interval')
    base = f'http://127.0.0.1:{a.port}'
    seen = set()
    buckets = {}
    # History is bounded by Rclone; do not replay entries that predate the monitor.
    try:
        data = rc(base, 'core/transferred')
        seen = {(x.get('group'), x.get('name'), x.get('completed_at'))
                for x in data.get('transferred', []) if x.get('completed_at')}
    except Exception as exc:
        print(f'History unavailable at startup: {exc}', flush=True)
    print(f'Watching Rclone RC on {base}; Ctrl+C stops ONLY the monitor.', flush=True)
    while True:
        try:
            stats = rc(base, 'core/stats')
            for x in stats.get('transferring', []):
                path = item_path(x)
                done = x.get('bytes') or 0
                size = x.get('size') or 0
                percent = min(100, int(done * 100 / size)) if size > 0 else 0
                tick = percent // 10
                now = datetime.now().strftime('%H:%M:%S')
                if path not in buckets:
                    print(f'[{now}] UPLOADING {path}', flush=True)
                    buckets[path] = -1
                if tick > buckets[path]:
                    print(f'[{now}] PROGRESS {percent:3d}% {path}', flush=True)
                    buckets[path] = tick
            history = rc(base, 'core/transferred')
            for x in history.get('transferred', []):
                completed_at = x.get('completed_at')
                if not completed_at:
                    continue
                marker = (x.get('group'), x.get('name'), completed_at)
                if marker in seen:
                    continue
                seen.add(marker)
                path = item_path(x)
                now = datetime.now().strftime('%H:%M:%S')
                if x.get('error'):
                    print(f'[{now}] ERROR {path}: {x["error"]}', flush=True)
                else:
                    print(f'[{now}] COPIED {path}', flush=True)
                buckets.pop(path, None)
            time.sleep(a.interval)
        except KeyboardInterrupt:
            print('\nMonitor stopped. Migration is unaffected.', flush=True)
            return 0
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            print(f'[{datetime.now():%H:%M:%S}] Monitor unavailable: {exc}', flush=True)
            time.sleep(5)


if __name__ == '__main__':
    raise SystemExit(main())
