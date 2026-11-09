import json, os, zipfile, io, calendar
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from garmin_personal_api import GarminPersonalApiClient, PersonalApiAuthenticator

ROOT=Path('garmin_data'); ACT=ROOT/'activities'; DETAIL=ROOT/'details'
ACT.mkdir(parents=True,exist_ok=True); DETAIL.mkdir(parents=True,exist_ok=True)

def year_ago(d):
    try: return d.replace(year=d.year-1)
    except ValueError: return d.replace(year=d.year-1, day=28)

def activity_id(item):
    return item.get('activityId') or item.get('activity_id') or item.get('id')

def is_run(item):
    t=item.get('activityType') or item.get('activity_type') or {}
    if isinstance(t,dict): t=t.get('typeKey') or t.get('typeName') or t.get('parentTypeId') or ''
    return 'run' in str(t).lower() or 'treadmill' in str(t).lower()

def main():
    key=os.environ.get('GARMIN_PERSONAL_API_KEY','').strip()
    if not key: raise RuntimeError('Missing GARMIN_PERSONAL_API_KEY secret')
    today=datetime.now(timezone.utc).date()
    start=year_ago(today)
    # Scan entire 12-month window each time to catch late imports/edits.
    with PersonalApiAuthenticator() as auth:
        token=auth.obtain_token(key)
    with GarminPersonalApiClient(token.access_token) as client:
        offset=0; all_items=[]
        while True:
            page=client.search_activities(start=offset,limit=100,start_date=start.isoformat(),end_date=today.isoformat())
            if isinstance(page,dict):
                page=page.get('activities') or page.get('results') or page.get('items') or []
            if not isinstance(page,list): raise RuntimeError('Unexpected Garmin activity listing response')
            all_items.extend(page)
            print(f'Listed {len(all_items)} activities',flush=True)
            if len(page)<100: break
            offset+=len(page)
            if offset>20000: raise RuntimeError('Pagination safety limit exceeded')
        runs=[x for x in all_items if isinstance(x,dict) and is_run(x)]
        failures=[]; new=0
        for item in runs:
            aid=activity_id(item)
            if not aid: continue
            aid=str(aid)
            (ACT/f'{aid}.json').write_text(json.dumps(item,indent=2,ensure_ascii=False),encoding='utf-8')
            target=ACT/f'{aid}.zip'
            if not target.exists():
                try:
                    data=client.download_activity(int(aid))
                    if not zipfile.is_zipfile(io.BytesIO(data)): raise ValueError('Download is not a ZIP')
                    target.write_bytes(data); new+=1
                except Exception as e:
                    failures.append({'id':aid,'error':str(e)[:250]})
                    print(f'Activity {aid} download failed: {type(e).__name__}',flush=True)
            detail=DETAIL/f'{aid}.json'
            if not detail.exists():
                try: detail.write_text(json.dumps(client.get_activity(int(aid)),indent=2),encoding='utf-8')
                except Exception as e: failures.append({'id':aid,'detail_error':str(e)[:250]})
        summary={'generated_utc':datetime.now(timezone.utc).isoformat(),'window_start':start.isoformat(),'window_end':today.isoformat(),'running_activities_found':len(runs),'new_downloads':new,'failed_downloads':failures,'note':'Original Garmin activity ZIPs may contain FIT files; no FIT guarantee for every activity.'}
        (ROOT/'manifest.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        out=Path('garmin_upload_to_chatgpt.zip')
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for p in ROOT.rglob('*'):
                if p.is_file(): z.write(p,p.relative_to(ROOT))
        print(f'Created {out} ({out.stat().st_size:,} bytes); {len(runs)} runs, {new} new downloads, {len(failures)} errors',flush=True)

if __name__=='__main__': main()
