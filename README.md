# LifeTracker

A private journal and life-tracking app. Each day you record how it went, fill in
the parameters you chose to track (hours slept, mood, whether you exercised), and
write a few notes. Later you read the journal and the weekly review.

The idea: record reality, notice patterns, improve gradually. There are no streaks,
no scores and no badges. A day you skip is simply a day with no entry.

Built with Python, Django 5.2, PostgreSQL (Supabase in production, SQLite locally),
WhiteNoise, Gunicorn, and plain HTML/CSS with a little vanilla JavaScript.

---

## What it does

- **Accounts.** Register, log in, log out. Every page except login, registration and
  the health check requires a login. Every database query is filtered by the logged-in
  user, so changing an ID in a URL returns a 404 rather than someone else's data.
- **Day numbering.** You choose a start date; that date is Day 1. Day numbers are
  always calculated from the date difference, never stored, so missed days and
  backfilled entries get the correct number, and changing the start date renumbers
  everything. Dates before the start date are labelled "Before Day 1".
- **Parameters.** Four types: number (with optional unit), scale from 1 to 10, yes/no,
  and short text. You can add, rename, reorder, deactivate and delete them.
- **Daily check-in.** One entry per date. Create it, edit it later, or backfill past
  days. Every field is optional; a blank value is stored as "not recorded", never as zero.
- **Journal.** Newest first, with a preview of each entry.
- **Weekly review.** The last seven calendar days (today and the six before). Shows how
  many days were recorded, averages for number and 1 to 10 parameters using only the days
  that have a value, yes/no counts, and what you wrote.

### How inactive and deleted parameters behave

| Action | Effect |
| --- | --- |
| Deactivate | Hidden from new entries. All past values are kept and still shown in old entries and the weekly review. |
| Edit an old entry that has a value for an inactive parameter | That parameter still appears in the form, marked inactive, so the value stays editable. |
| Delete | Permanently deletes the parameter **and every value recorded for it**. Journal entries and notes stay. A confirmation page shows how many values will go. |
| Change a parameter's type | Not allowed after creation, because old values would change meaning. Add a new parameter instead. |

---

## Run it locally

You need Python 3.12 or newer.

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create your settings file
cp .env.example .env                 # Windows: copy .env.example .env
# The defaults work as-is: DEBUG=True and an empty DATABASE_URL (uses SQLite).

# 4. Create the database tables
python manage.py migrate

# 5. Start the server
python manage.py runserver
```

Open http://127.0.0.1:8000/, choose **Create an account**, and you are on Day 1.
(You do not need an admin account to use the app. See "Admin account" below.)

Set `TIME_ZONE` in `.env` (for example `Europe/London`) so that "today" matches your clock.

### Checks and tests

```bash
python manage.py check
python manage.py makemigrations --check --dry-run   # should say: No changes detected
python manage.py test
```

---

## Supabase PostgreSQL

LifeTracker talks to Supabase as an ordinary PostgreSQL database, from the server only.
It does not use the Supabase JavaScript client, API keys, the anon key, or Supabase Auth.
Django owns logins and permissions.

> **The database password is not an API key.** It is the password you chose when you
> created the Supabase project (reset it under *Project Settings → Database*). It goes
> only in the `DATABASE_URL` environment variable on the server, never in code,
> templates or JavaScript.

### 1. Get the connection string

1. Open your project in the Supabase dashboard and click **Connect**.
2. Choose the connection method (see the next section), copy the URI.
3. Replace `[YOUR-PASSWORD]` with your database password.
4. If the password contains special characters, percent-encode them in the URL
   (`@` → `%40`, `/` → `%2F`, `:` → `%3A`, `#` → `%23`, `?` → `%3F`).
   The easiest fix is a password that is long and uses only letters and digits.

### 2. Direct connection or session pooler?

| Connection | Host looks like | Use when |
| --- | --- | --- |
| **Session pooler** (recommended for Render) | `aws-…-<region>.pooler.supabase.com:5432`, user `postgres.<project-ref>` | Always works over IPv4 and IPv6. |
| Direct connection | `db.<project-ref>.supabase.co:5432`, user `postgres` | Your host supports IPv6, or you bought Supabase's IPv4 add-on. |
| Transaction pooler | `…pooler.supabase.com:6543` | Serverless functions. Not needed here. |

Supabase's direct connection is **IPv6-only** by default. Render's outbound traffic is
IPv4, so a direct connection from Render typically fails with an error such as
*"Network is unreachable"* or *"could not translate host name"*. If that happens, switch
`DATABASE_URL` to the **Session pooler** string. It behaves like a normal long-lived
PostgreSQL connection, which is what Django expects.

If you ever use the transaction pooler (port 6543), also set `DB_TRANSACTION_POOLER=True`,
which disables server-side cursors and prepared statements that this mode cannot handle.

### 3. Use it

Put the string in `DATABASE_URL`, in `.env` locally or in the Render dashboard.

```
DATABASE_URL=postgresql://postgres.<project-ref>:<password>@aws-<n>-<region>.pooler.supabase.com:5432/postgres
```

Then run `python manage.py migrate` once; the tables are created in your Supabase database.
SSL is required by default (`DB_SSLMODE=require`).

If `DATABASE_URL` is empty, a local `db.sqlite3` file is used. In production, always set it:
Render's disk is erased on every deploy, so SQLite there would lose your journal.

---

## Deploy to Render

1. **Push the code to GitHub.** Make sure `.env` is not included (`.gitignore` already
   excludes it). If `build.sh` loses its executable bit, run
   `git update-index --chmod=+x build.sh`. Render runs it with `bash build.sh` regardless.
2. **Create the service.** In Render choose **New → Blueprint**, connect the repository,
   and Render reads `render.yaml`. (Or create a **Web Service** manually: Python runtime,
   build command `bash build.sh`, start command
   `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT`, health check path `/healthz/`.)
3. **Fill in the environment variables** when prompted:

   | Variable | Value |
   | --- | --- |
   | `DATABASE_URL` | Your Supabase connection string (session pooler). Required. |
   | `SECRET_KEY` | Generated by the Blueprint. To make your own: `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |
   | `DEBUG` | `False` |
   | `TIME_ZONE` | e.g. `Europe/London` |
   | `ALLOWED_HOSTS` | Only for custom domains, e.g. `journal.example.com`. |
   | `CSRF_TRUSTED_ORIGINS` | Only for custom domains, e.g. `https://journal.example.com`. |

   Render provides `RENDER_EXTERNAL_HOSTNAME` (your `something.onrender.com` name). The
   settings automatically add it to `ALLOWED_HOSTS` and add `https://<that name>` to
   `CSRF_TRUSTED_ORIGINS`, so the default Render URL works with no extra setup.
4. **Deploy.** `build.sh` installs packages, collects static files and runs migrations
   against Supabase. Render then starts Gunicorn and watches `/healthz/`.
5. **Open the URL**, create your account, then set `ALLOW_REGISTRATION=False` in Render
   and redeploy if this is only for you. This stops strangers creating accounts.

Production mode redirects HTTP to HTTPS, marks cookies secure, and sends HSTS (one hour
to start; once everything works, set `SECURE_HSTS_SECONDS=31536000`).

### Admin account (optional)

The Django admin at `/admin/` is separate from normal accounts. You only need it to
inspect data. Render's free plan has no shell, so create the admin from your own computer
against the production database:

```bash
# in your local project folder, with the virtual environment active
DATABASE_URL="postgresql://…your Supabase string…" SECRET_KEY=anything python manage.py createsuperuser
```

(On Windows PowerShell set the variables first: `$env:DATABASE_URL="…"`.) On a paid
Render plan you can instead open the service's **Shell** tab and run
`python manage.py createsuperuser`. Set `ADMIN_URL` to something unguessable if you keep
the admin enabled.

### Troubleshooting

- **400 Bad Request on Render:** the host isn't allowed. Add it to `ALLOWED_HOSTS`.
- **"CSRF verification failed":** add the exact `https://…` origin to `CSRF_TRUSTED_ORIGINS`.
- **Build fails on `ImproperlyConfigured: SECRET_KEY`:** the variable isn't set.
- **Database "Network is unreachable":** use the Supabase session pooler string.
- **"password authentication failed":** wrong password, or special characters not percent-encoded.
- **Free instance is slow on the first request:** Render free services sleep when idle.

---

## Project layout

```
manage.py
config/            settings, root URLs, WSGI/ASGI
tracker/           models, forms, views, services, URLs, admin, tests, migrations
templates/         base layout, auth pages, tracker pages (+ 404/500)
static/tracker/    app.css, app.js
requirements.txt  .env.example  .gitignore  build.sh  render.yaml
```

- `tracker/utils.py` has the day-number maths. `tracker/services.py` has the weekly
  summary and profile helper. `tracker/forms.py` builds the check-in form from the user's
  own parameters and saves the entry and its values in one transaction.
- Migrations live in `tracker/migrations/`. After changing a model, run
  `python manage.py makemigrations` and commit the new file.

## Design notes

The interface is meant to read like a notebook: a warm paper background, charcoal text,
one muted forest green, a serif for headings and writing (Newsreader) and a plain sans
(Public Sans) for controls. A narrow left margin carries dates, day numbers and section
titles. There are no charts, because a handful of averages in a table says everything the
data can support. Fonts load from Google Fonts with Georgia and system fonts as fallbacks;
to avoid the external request entirely, delete the three font `<link>` tags in
`templates/base.html`.

## Privacy

Entries are visible only to their author. Pages are marked `noindex`. The only external
request the browser makes is the font stylesheet mentioned above. Back up your data from
the Supabase dashboard (Database → Backups) or with `pg_dump`.
