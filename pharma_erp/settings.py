import os
import urllib.parse
from pathlib import Path
from dotenv import load_dotenv
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-dummy-key-for-scaffolding')
DEBUG = os.environ.get('DEBUG', 'False').lower() in ('true', '1', 't')

# ALLOWED_HOSTS configuration for Render and local environments
allowed_hosts_env = os.environ.get('ALLOWED_HOSTS')
if allowed_hosts_env:
    ALLOWED_HOSTS = [h.strip() for h in allowed_hosts_env.split(',') if h.strip()]
else:
    ALLOWED_HOSTS = ['*', '.onrender.com', 'localhost', '127.0.0.1']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Modular Apps
    'apps.accounts',
    'apps.production',
    'apps.maintenance',
    'apps.inventory',
    'apps.logistics',
    'apps.ai_chat',
    'django_apscheduler',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'pharma_erp.middleware.NetworkResilienceMiddleware',
    'apps.production.middleware.DailyImputationMiddleware',
]


ROOT_URLCONF = 'pharma_erp.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'pharma_erp.wsgi.application'

def _sanitize_database_url(url):
    """
    Sanitizes DATABASE_URL by URL-encoding special characters in username/password
    (such as '@' or '/') that would otherwise break standard URI parsing.
    """
    if not url:
        return url
    url = url.strip()
    if '://' in url and '@' in url:
        scheme, rest = url.split('://', 1)
        last_at = rest.rfind('@')
        if last_at != -1:
            user_pass = rest[:last_at]
            host_path = rest[last_at + 1:]
            if ':' in user_pass:
                u, p = user_pass.split(':', 1)
                enc_user = urllib.parse.quote(urllib.parse.unquote(u), safe='')
                enc_pass = urllib.parse.quote(urllib.parse.unquote(p), safe='')
                return f"{scheme}://{enc_user}:{enc_pass}@{host_path}"
    return url

# Database Configuration: Supabase PostgreSQL (via DATABASE_URL) with SQLite Fallback
DATABASE_URL = _sanitize_database_url(os.environ.get('DATABASE_URL'))

# Supabase PgBouncer pooler recommendation: set conn_max_age to 0 (or short duration)
# to avoid using stale, closed server connections.
db_conn_max_age = int(os.environ.get('DB_CONN_MAX_AGE', 0))

if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=db_conn_max_age,
            ssl_require=True
        )
    }
    # Ensure health checks, persistent options and SSL for PostgreSQL on Render / Supabase
    DATABASES['default']['CONN_HEALTH_CHECKS'] = True
    DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True
    if 'OPTIONS' not in DATABASES['default']:
        DATABASES['default']['OPTIONS'] = {}
    DATABASES['default']['OPTIONS']['sslmode'] = 'require'
    DATABASES['default']['OPTIONS'].setdefault('connect_timeout', 10)
    DATABASES['default']['OPTIONS'].setdefault('keepalives', 1)
    DATABASES['default']['OPTIONS'].setdefault('keepalives_idle', 30)
    DATABASES['default']['OPTIONS'].setdefault('keepalives_interval', 10)
    DATABASES['default']['OPTIONS'].setdefault('keepalives_count', 5)
else:
    # Development fallback to local SQLite when DATABASE_URL is not set
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
            'CONN_MAX_AGE': 60,
        }
    }

# Robust Python Logging for Production Debugging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} [{name}:{lineno}] {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': os.environ.get('LOG_LEVEL', 'INFO'),
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'pharma_erp': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}


CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'pharma-erp-fast-cache',
        'TIMEOUT': 300,
    }
}
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# WhiteNoise production static file storage with compression & caching
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'
WHITENOISE_MANIFEST_STRICT = False
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'accounts.User'
