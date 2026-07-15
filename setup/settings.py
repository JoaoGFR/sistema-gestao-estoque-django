"""
Django settings for setup project.
"""

from pathlib import Path
import os 
import dj_database_url 


BASE_DIR = Path(__file__).resolve().parent.parent


SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-chave-temporaria-dev')


DEBUG = os.getenv('DEBUG', 'False') == 'True'


allowed_hosts_env = os.getenv('ALLOWED_HOSTS', '')
ALLOWED_HOSTS = [
    '127.0.0.1', 
    'localhost',
    '192.168.0.7', 
    '.vercel.app', 
]
if allowed_hosts_env:
    ALLOWED_HOSTS.extend(allowed_hosts_env.split(','))



CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'http://192.168.0.7:8000', 
    'https://*.vercel.app',    
]


CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'estoque',
    'crispy_forms',
    'crispy_bootstrap5',
    'axes',  # [SEGURANÇA M1] Rate limiting no login
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
    # [SEGURANÇA M1] axes — deve ficar após AuthenticationMiddleware
    'axes.middleware.AxesMiddleware',
]

ROOT_URLCONF = 'setup.urls'

# ---------------------------------------------------------------------------
# [SEGURANÇA M1] django-axes — Rate Limiting / Proteção contra Força Bruta
# ---------------------------------------------------------------------------
AUTHENTICATION_BACKENDS = [
    # O backend do axes DEVE ser o primeiro da lista
    'axes.backends.AxesStandaloneBackend',
    # Backend padrão do Django (autenticação normal)
    'django.contrib.auth.backends.ModelBackend',
]

AXES_FAILURE_LIMIT = 5          # Bloqueia após 5 tentativas falhas
AXES_COOLOFF_TIME = 1           # Cooldown de 1 hora antes de liberar
AXES_LOCK_OUT_AT_FAILURE = True # Ativa o bloqueio após atingir o limite
AXES_RESET_ON_SUCCESS = True    # Reseta o contador após login bem-sucedido
AXES_LOCKOUT_TEMPLATE = None    # Usa o comportamento padrão de retornar 403
AXES_ENABLE_ADMIN = True        # Permite gerenciar bloqueios pelo admin Django

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'setup.wsgi.application'


database_url = os.getenv('POSTGRES_URL', os.getenv('DATABASE_URL'))


db_user = os.getenv('POSTGRES_USER')
db_password = os.getenv('POSTGRES_PASSWORD')
db_name = os.getenv('POSTGRES_DB')
db_host = os.getenv('DB_HOST')
db_port = os.getenv('DB_PORT')


if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

if database_url:
    DATABASES = {
        'default': dj_database_url.parse(database_url, conn_max_age=600, ssl_require=True)
    }
elif db_host:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': db_name,
            'USER': db_user,
            'PASSWORD': db_password,
            'HOST': db_host,
            'PORT': db_port,
        }
    }
else:

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Porto_Velho'
USE_I18N = True
USE_TZ = True


STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"


MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'


# ---------------------------------------------------------------------------
# [SEGURANÇA B1] Headers de Segurança HTTP
# Divididos em dois grupos:
#   GRUPO 1 — Seguros em qualquer ambiente (HTTP ou HTTPS): sempre ativos em produção.
#   GRUPO 2 — Exigem HTTPS: ativados apenas quando HTTPS_ENABLED=True no .env.
#             ⚠️  Intranet HTTP: mantenha HTTPS_ENABLED=False (padrão).
#                 Se ativar com HTTP, o login vai travar (cookies secure bloqueados).
# ---------------------------------------------------------------------------

# --- GRUPO 1: Ativos em produção (HTTP e HTTPS) ---
if not DEBUG:
    # Impede que o browser "adivinhe" o tipo MIME (MIME sniffing attack)
    SECURE_CONTENT_TYPE_NOSNIFF = True

    # Controla quais informações vão no header Referer entre páginas
    SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

    # Torna os cookies inacessíveis via JavaScript (mitigação de XSS)
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_HTTPONLY = True

# --- GRUPO 2: Apenas quando HTTPS estiver ativo no servidor ---
# Para ativar: adicione HTTPS_ENABLED=True no .env do servidor de produção.
HTTPS_ENABLED = os.getenv('HTTPS_ENABLED', 'False') == 'True'

if not DEBUG and HTTPS_ENABLED:
    # Força o browser a usar HTTPS por 1 ano (HSTS)
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    # Cookies só trafegam via HTTPS — NUNCA ativar sem SSL real!
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True