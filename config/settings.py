"""
Django settings for LifeTracker.

Everything that differs between your laptop and production is read from
environment variables (see .env.example). Nothing secret lives in this file.
"""
import os
import sys
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# Load a local .env file if python-dotenv is installed. On Render the real
# environment variables are used and no .env file exists.
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # pragma: no cover
    pass


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=None):
    value = os.environ.get(name, "")
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or list(default or [])


DEBUG = env_bool("DEBUG", False)
# True while running `python manage.py test`.
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"

# --- Secret key -------------------------------------------------------------
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = "insecure-development-key-do-not-use-in-production"
    else:
        raise ImproperlyConfigured(
            "SECRET_KEY is not set. Generate one with: "
            'python -c "from django.core.management.utils import '
            'get_random_secret_key; print(get_random_secret_key())"'
        )

# --- Hosts and CSRF origins ---------------------------------------------------
# Render sets RENDER_EXTERNAL_HOSTNAME (e.g. lifetracker.onrender.com) for web
# services, so the default Render URL works without extra configuration.
RENDER_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()

ALLOWED_HOSTS = env_list(
    "ALLOWED_HOSTS", ["localhost", "127.0.0.1", "[::1]"] if DEBUG else []
)
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
if RENDER_HOSTNAME:
    if RENDER_HOSTNAME not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(RENDER_HOSTNAME)
    render_origin = f"https://{RENDER_HOSTNAME}"
    if render_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(render_origin)

# --- Application definition ---------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "tracker",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database -------------------------------------------------------------------
# DATABASE_URL set   -> that database (Supabase PostgreSQL in production).
# DATABASE_URL unset -> local SQLite file for development.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=int(os.environ.get("DB_CONN_MAX_AGE", "600")),
            conn_health_checks=True,
        )
    }
    if DATABASES["default"]["ENGINE"].endswith("postgresql"):
        options = DATABASES["default"].setdefault("OPTIONS", {})
        # Supabase requires encrypted connections.
        options.setdefault("sslmode", os.environ.get("DB_SSLMODE", "require"))
        # Only needed for Supabase's *transaction* pooler (port 6543).
        if env_bool("DB_TRANSACTION_POOLER", False):
            DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
            options["prepare_threshold"] = None
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Authentication ---------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# Set to False once you have created your account if this is a private install.
ALLOW_REGISTRATION = env_bool("ALLOW_REGISTRATION", True)

# Path of the Django admin site. Change it to make it harder to guess.
ADMIN_URL = os.environ.get("ADMIN_URL", "admin/").strip().lstrip("/")
if not ADMIN_URL.endswith("/"):
    ADMIN_URL += "/"

# --- Internationalisation -----------------------------------------------------------
LANGUAGE_CODE = "en-us"
# "Today" and day numbers follow this time zone, e.g. Europe/London.
TIME_ZONE = os.environ.get("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

# --- Static files ---------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

if DEBUG or TESTING:
    _static_backend = "django.contrib.staticfiles.storage.StaticFilesStorage"
else:
    _static_backend = "whitenoise.storage.CompressedManifestStaticFilesStorage"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": _static_backend},
}

# --- Production security ------------------------------------------------------------------
if not DEBUG and not TESTING:
    # Render terminates HTTPS at its proxy and forwards this header.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Start small; raise to 31536000 (one year) once HTTPS is confirmed working.
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "3600"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
    SECURE_HSTS_PRELOAD = False
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
