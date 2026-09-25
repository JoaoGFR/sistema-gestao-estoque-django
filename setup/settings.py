"""
Django settings for setup project.
"""

from pathlib import Path
import os 
import dj_database_url 


BASE_DIR = Path(__file__).resolve().parent.parent

# Carrega variáveis do arquivo .env local em desenvolvimento se existir
env_file = BASE_DIR / '.env'
if env_file.exists():
    try:
        with open(env_file, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and (k not in os.environ or not os.environ[k]):
                        os.environ[k] = v
    except Exception:
        pass


DEBUG = os.getenv('DEBUG', 'False') == 'True'

# [SEGURANÇA] Validação da SECRET_KEY
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        import warnings
        warnings.warn("ALERTA DE SEGURANÇA: SECRET_KEY não definida no ambiente de produção! Configure-a no painel do servidor.")
    SECRET_KEY = 'django-insecure-jgtech-sistema-estoque-vercel-chave-segura-2026-prod'


# [SEGURANÇA] ALLOWED_HOSTS restrito aos domínios e IPs legítimos (sem wildcard '*')
ALLOWED_HOSTS = [
    '127.0.0.1', 
    'localhost',
    '192.168.0.7', 
    '.vercel.app', 
]
allowed_hosts_env = os.getenv('ALLOWED_HOSTS', '')
if allowed_hosts_env:
    ALLOWED_HOSTS.extend([h.strip() for h in allowed_hosts_env.split(',') if h.strip()])



CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'http://192.168.0.7:8000', 
    'https://*.vercel.app',    
]
csrf_origins_env = os.getenv('CSRF_TRUSTED_ORIGINS', '')
if csrf_origins_env:
    CSRF_TRUSTED_ORIGINS.extend([o.strip() for o in csrf_origins_env.split(',') if o.strip()])

# Informa ao Django que está atrás do proxy reverso HTTPS da Vercel
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


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
    # Gestão de Assinaturas SaaS & 3 Dias de Degustação Grátis
    'estoque.middleware.AssinaturaMiddleware',
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

def get_client_ip(request):
    """Extrai o IP real do cliente atrás do proxy da Vercel para evitar DoS global"""
    if request:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR')
    return None

AXES_CLIENT_IP_CALLABLE = get_client_ip

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


import sys

if 'test' in sys.argv and not database_url:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        }
    }
elif database_url:
    # conn_max_age=0 para evitar exaustão de pool de conexões no ambiente serverless
    DATABASES = {
        'default': dj_database_url.parse(database_url, conn_max_age=0)
    }
elif db_host:
    import socket
    usar_postgres = True
    if db_host == 'db':
        try:
            socket.gethostbyname('db')
        except (socket.gaierror, OSError):
            usar_postgres = False

    if usar_postgres:
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


STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
WHITENOISE_MANIFEST_STRICT = False


MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'landing_page'


# ---------------------------------------------------------------------------
# [SEGURANÇA B1] Headers de Segurança HTTP
# Divididos em dois grupos:
#   GRUPO 1 — Seguros em qualquer ambiente (HTTP ou HTTPS): sempre ativos em produção.
#   GRUPO 2 — Exigem HTTPS: ativados em produção na Vercel ou quando HTTPS_ENABLED=True.
# ---------------------------------------------------------------------------

# --- GRUPO 1: Ativos em produção (HTTP e HTTPS) ---
if not DEBUG:
    # Impede que o browser "adivinhe" o tipo MIME (MIME sniffing attack)
    SECURE_CONTENT_TYPE_NOSNIFF = True

    # Proteção contra Clickjacking
    X_FRAME_OPTIONS = 'DENY'

    # Controla quais informações vão no header Referer entre páginas
    SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

    # Torna os cookies inacessíveis via JavaScript (mitigação de XSS)
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_HTTPONLY = True

# Limites defensivos de upload para mitigar exaustão de memória (5MB max)
DATA_UPLOAD_MAX_MEMORY_SIZE = 5242880
FILE_UPLOAD_MAX_MEMORY_SIZE = 5242880

# --- GRUPO 2: Quando HTTPS estiver ativo no servidor ---
IS_VERCEL = os.getenv('VERCEL') == '1' or 'VERCEL' in os.environ
HTTPS_ENABLED = os.getenv('HTTPS_ENABLED', 'False') == 'True' or IS_VERCEL

if not DEBUG and HTTPS_ENABLED:
    # Força o browser a usar HTTPS por 1 ano (HSTS)
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    # Cookies só trafegam via HTTPS
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# ---------------------------------------------------------------------------
# MERCADO PAGO - INTEGRAÇÃO DE PAGAMENTOS SAAS
# ---------------------------------------------------------------------------
MERCADO_PAGO_ACCESS_TOKEN = os.getenv(
    'MERCADO_PAGO_ACCESS_TOKEN',
    'APP_USR-616570918127832-092117-891dbcb003f168421350b51f32929901-649556782'
)
MERCADO_PAGO_PUBLIC_KEY = os.getenv(
    'MERCADO_PAGO_PUBLIC_KEY',
    'APP_USR-d62bfd7f-d6c9-416b-b797-2686ec9755b1'
)
MERCADO_PAGO_CLIENT_ID = os.getenv('MERCADO_PAGO_CLIENT_ID', '616570918127832')
MERCADO_PAGO_CLIENT_SECRET = os.getenv('MERCADO_PAGO_CLIENT_SECRET', 'Z9IOyMKrNxfilCHVIGghVrV3olva50Ti')
MERCADO_PAGO_WEBHOOK_SECRET = os.getenv('MERCADO_PAGO_WEBHOOK_SECRET', '')
