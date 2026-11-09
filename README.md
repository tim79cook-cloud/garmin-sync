# Garmin Personal API — GitHub Actions sync

No Python installation required on your Windows computer. GitHub runs the sync remotely.

## Set up once

1. Sign into GitHub and create a **private** repository (e.g. `my-garmin-sync`). Do **not** make it public: the repository contains your sync configuration and may have private cached training files.
2. On the repository page select **Add file → Upload files**. Upload `sync.py` and `README.md` from this package and commit. (GitHub's browser uploader may not preserve hidden folders reliably.)
3. Create the workflow in the browser: **Add file → Create new file**, name it `.github/workflows/garmin-sync.yml`, paste the contents of the supplied `.github/workflows/garmin-sync.yml`, and commit.
4. Go to **Settings → Secrets and variables → Actions → New repository secret**. Name: `GARMIN_PERSONAL_API_KEY`. Value: your Garmin Personal API key. Never paste the key into source code or a chat.
5. Go to **Actions → Garmin one-click sync → Run workflow → Run workflow**. It may take a minute for Actions to appear after the first workflow commit.
6. When the run completes, open its run page and download the **garmin-chatgpt-export** artifact under Artifacts. GitHub downloads an outer ZIP; extract it to get `garmin_upload_to_chatgpt.zip` and upload that inner ZIP to ChatGPT.

## What it does

- Scans the preceding 12 months of activities and selects running/treadmill activities.
- Downloads original activity ZIPs (which typically include FIT files) and Garmin activity detail JSON.
- Saves activity data to a private GitHub Actions cache so later runs usually only download missing original files.
- Rebuilds a full upload-ready ZIP every time, including the available cached history.
- Never embeds your API key in the export. Activity files can include precise GPS locations.

## Important limitations

- GitHub Actions **cache is not durable storage**: it can expire or be evicted. If it disappears, the next run redownloads the 12-month window; activities older than that window may be lost from the export. Download and keep a copy of your export ZIPs for a permanent archive.
- A sync scans 12 months every time, even after the first run. This helps catch activities imported late, but changes to existing downloaded FIT files are not automatically redownloaded.
- The ZIP may be large; Github-hosted runner and artifact size limits apply.
- Garmin API availability and permissions can vary. This package has not been tested against your account.
- Actions usage/storage quotas may apply to your GitHub plan.
- This runs on GitHub's infrastructure, so your Garmin key and private activity data are processed by GitHub.

## Troubleshooting

Open **Actions → your failed run → sync → Download and package running activities** and share the error text, **not** your key. If the first run fails, check the secret's exact name and your Garmin API key's validity. If GitHub Actions is blocked by your work network, try from a personal device.
