# Deploying HWCheck to Render + Porkbun

## 1. Push this repo to GitHub

```bash
git remote add origin <your-repo-url>
git push -u origin main
```

## 2. Deploy on Render (Blueprint)

This repo includes `render.yaml`, so Render can set up the web service,
persistent disk, and env var slots automatically.

1. Go to [dashboard.render.com](https://dashboard.render.com) and sign in
   (GitHub login is easiest).
2. **New +** → **Blueprint** → connect your GitHub account if prompted →
   select this repo.
3. Render reads `render.yaml` and shows a plan: one web service (`hwcheck`)
   on the **Starter** plan (~$7/mo — required for the persistent disk;
   the free plan doesn't support disks, and without one the SQLite database
   and uploaded homework photos would be wiped on every deploy).
4. It will prompt for the two secret env vars (marked `sync: false` in
   `render.yaml`, so they're never stored in the repo):
   - `OPENAI_API_KEY` — your key from platform.openai.com
   - `ADMIN_PASSWORD` — pick a new strong password for the live site (don't
     reuse the local dev one)
5. Click **Apply** / **Create**. First deploy takes a few minutes.
6. Once live, open `https://hwcheck.onrender.com` (or whatever Render
   named it) and confirm `/submit` and `/admin/login` both load.

### If you'd rather set it up manually (no Blueprint)

New + → Web Service → connect repo → Runtime: Python → Build command
`pip install -r requirements.txt` → Start command `gunicorn app:app` →
under Advanced, add a Disk mounted at `/var/data` (1 GB is plenty to
start) → add env vars `DATA_DIR=/var/data`, `OPENAI_API_KEY`,
`ADMIN_PASSWORD`, and a random `FLASK_SECRET_KEY`.

## 3. Point hwcheck.tutorilya.com at it

In Render:

1. Open the `hwcheck` service → **Settings** → **Custom Domains** → **Add
   Custom Domain**.
2. Enter `hwcheck.tutorilya.com`.
3. Render shows you a CNAME target, something like `hwcheck.onrender.com`
   (copy the exact value it gives you — it can differ from the service
   name).

In Porkbun (porkbun.com, logged in):

1. **Account** → **Domain Management** → find `tutorilya.com` → **DNS**
   (or the "Details" / DNS records icon next to the domain).
2. **Add record**:
   - Type: `CNAME`
   - Host: `hwcheck`
   - Answer: the target Render gave you (e.g. `hwcheck.onrender.com`)
   - TTL: default is fine
3. Save.

DNS usually propagates within a few minutes to an hour. Render will show
the custom domain as "verifying" then flip to a green checkmark once it
sees the record and issues an SSL certificate automatically — no extra
steps needed for HTTPS.

## 4. Link it from tutorilya.com (Tilda)

Add a button/link somewhere on the site (e.g. near "Sign up") pointing to
`https://hwcheck.tutorilya.com/submit`.

## Updating the live app later

Any `git push` to the branch Render is watching triggers an automatic
redeploy. The persistent disk (`/var/data`) survives redeploys, so the
database and uploaded files aren't lost.
