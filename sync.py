"""Incremental Garmin Personal API exporter with bounded, rate-aware retries."""
import io
import json
import os
import random
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from garmin_personal_api import GarminPersonalApiClient, PersonalApiAuthenticator

ROOT = Path('garmin_data')
ACT = ROOT / 'activities'
DETAIL = ROOT / 'details'
ACT.mkdir(parents=True, exist_ok=True)
DETAIL.mkdir(parents=True, exist_ok=True)
MIN_REQUEST_INTERVAL = float(os.environ.get('GARMIN_REQUEST_INTERVAL_SECONDS', '2'))
MAX_RETRIES = int(os.environ.get('GARMIN_MAX_RETRIES', '8'))
MAX_WAIT = 300
_last_request = 0.0


def year_ago(d):
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def activity_id(item):
    return item.get('activityId') or item.get('activity_id') or item.get('id')


def is_run(item):
    t = item.get('activityType') or item.get('activity_type') or {}
    if isinstance(t, dict):
        t = t.get('typeKey') or t.get('typeName') or t.get('parentTypeId') or ''
    return 'run' in str(t).lower() or 'treadmill' in str(t).lower()


def paced_call(label, operation):
    global _last_request
    for attempt in range(MAX_RETRIES + 1):
        delay = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request)
        if delay > 0:
            time.sleep(delay)
        _last_request = time.monotonic()
        try:
            return operation()
        except Exception as exc:
            message = str(exc)
            is_429 = bool(re.search(r'\b(?:HTTP\s*)?429\b', message))
            is_transient = is_429 or bool(re.search(r'\b(?:HTTP\s*)?(?:500|502|503|504)\b', message))
            if not is_transient or attempt >= MAX_RETRIES:
                raise
            match = re.search(r'["\']?retryInSeconds["\']?\s*:\s*(\d+)', message)
            wait = min(MAX_WAIT, max(int(match.group(1)) + 5 if match else 0, min(15 * (2 ** attempt), MAX_WAIT)))
            wait += random.uniform(0, 2)
            print(f'{label}: server throttled/unavailable; waiting {wait:.0f}s before retry {attempt+1}/{MAX_RETRIES}', flush=True)
            time.sleep(wait)


def valid_zip(path):
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            return bool(archive.namelist()) and archive.testzip() is None
    except (zipfile.BadZipFile, OSError):
        return False


def main():
    key = os.environ.get('GARMIN_PERSONAL_API_KEY', '').strip()
    if not key:
        raise RuntimeError('Missing GARMIN_PERSONAL_API_KEY repository secret')
    today = datetime.now(timezone.utc).date()
    start = year_ago(today)
    with PersonalApiAuthenticator() as auth:
        token = auth.obtain_token(key)
    with GarminPersonalApiClient(token.access_token) as client:
        offset = 0
        all_items = []
        while True:
            page = paced_call('List activities', lambda: client.search_activities(
                start=offset, limit=100, start_date=start.isoformat(), end_date=today.isoformat()))
            if isinstance(page, dict):
                page = page.get('activities') or page.get('results') or page.get('items') or []
            if not isinstance(page, list):
                raise RuntimeError('Unexpected Garmin activity listing response')
            all_items.extend(page)
            print(f'Listed {len(all_items)} activities', flush=True)
            if len(page) < 100:
                break
            offset += len(page)
            if offset > 20000:
                raise RuntimeError('Pagination safety limit exceeded')

        runs_by_id = {str(activity_id(x)): x for x in all_items
                      if isinstance(x, dict) and is_run(x) and activity_id(x)}
        failures = []
        new_downloads = 0
        new_details = 0
        for index, (aid, item) in enumerate(runs_by_id.items(), 1):
            (ACT / f'{aid}.json').write_text(json.dumps(item, indent=2, ensure_ascii=False), encoding='utf-8')
            target = ACT / f'{aid}.zip'
            if not valid_zip(target):
                target.unlink(missing_ok=True)
                try:
                    data = paced_call(f'Download {aid}', lambda aid=aid: client.download_activity(int(aid)))
                    if not zipfile.is_zipfile(io.BytesIO(data)):
                        raise ValueError('Download is not a ZIP')
                    with zipfile.ZipFile(io.BytesIO(data)) as archive:
                        if not archive.namelist() or archive.testzip() is not None:
                            raise ValueError('Downloaded ZIP failed validation')
                    target.write_bytes(data)
                    new_downloads += 1
                except Exception as exc:
                    failures.append({'id': aid, 'kind': 'download', 'error': str(exc)[:250]})
                    print(f'Download {aid} failed: {type(exc).__name__}: {str(exc)[:120]}', flush=True)
            detail = DETAIL / f'{aid}.json'
            if not detail.exists() or detail.stat().st_size == 0:
                try:
                    data = paced_call(f'Detail {aid}', lambda aid=aid: client.get_activity(int(aid)))
                    detail.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
                    new_details += 1
                except Exception as exc:
                    failures.append({'id': aid, 'kind': 'detail', 'error': str(exc)[:250]})
                    print(f'Detail {aid} failed: {type(exc).__name__}: {str(exc)[:120]}', flush=True)
            if index % 25 == 0:
                print(f'Processed {index}/{len(runs_by_id)} running activities', flush=True)

        missing_downloads = [aid for aid in runs_by_id if not valid_zip(ACT / f'{aid}.zip')]
        missing_details = [aid for aid in runs_by_id if not (DETAIL / f'{aid}.json').is_file()]
        summary = {
            'generated_utc': datetime.now(timezone.utc).isoformat(),
            'window_start': start.isoformat(), 'window_end': today.isoformat(),
            'running_activities_found': len(runs_by_id),
            'activity_zip_count': len(runs_by_id) - len(missing_downloads),
            'activity_detail_count': len(runs_by_id) - len(missing_details),
            'new_downloads': new_downloads, 'new_details': new_details,
            'missing_download_ids': missing_downloads,
            'missing_detail_ids': missing_details,
            'failed_downloads': failures,
            'complete': not missing_downloads and not missing_details,
            'note': 'Original Garmin ZIPs may contain FIT files; FIT availability varies by activity.'
        }
        (ROOT / 'manifest.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        out = Path('garmin_upload_to_chatgpt.zip')
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in ROOT.rglob('*'):
                if path.is_file():
                    archive.write(path, path.relative_to(ROOT))
        print(f'Created {out} ({out.stat().st_size:,} bytes)', flush=True)
        print(f'Completeness: {summary["activity_zip_count"]}/{len(runs_by_id)} ZIPs; '
              f'{summary["activity_detail_count"]}/{len(runs_by_id)} detail JSONs. '
              f'Missing: {len(missing_downloads)} ZIPs, {len(missing_details)} details.', flush=True)
        if failures:
            print('Some files are still missing. Rerun this workflow to retry them using the saved cache.', flush=True)

if __name__ == '__main__':
    main()
