"""
Django settings for setup project.
"""

from pathlib import Path
import os  # <--- ESSENCIAL: Sem isso, o sistema quebra ao tentar ler o .env
import dj_database_url # <--- ESSENCIAL: Para conexão inteligente com o banco

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# --- SEGURANÇA: Lê do arquivo .env ---
# Se não achar a SECRET_KEY no .env, usa uma temporária (só para não crashar em dev)
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-chave-temporaria-dev')

# O DEBUG deve ser False em produção.
# No Vercel, você pode definir a variável de ambiente DEBUG como "False" nas configurações.
DEBUG = os.getenv('DEBUG', 'True') == 'True'

# --- CORREÇÃO ALLOWED_HOSTS ---
# 1. Pega do .env (se existir)
# 2. Adiciona automaticamente localhost e o coringa do Vercel
allowed_hosts_env = os.getenv('ALLOWED_HOSTS', '')
ALLOWED_HOSTS = [
    '127.0.0.1', 
    'localhost', 
    '.vercel.app', # O ponto libera qualquer subdomínio (ex: sistema-estoque-phi.vercel.app)
]
if allowed_hosts_env:
    ALLOWED_HOSTS.extend(allowed_hosts_env.split(','))


# --- CORREÇÃO DE SEGURANÇA (CSRF) ---
# Adiciona automaticamente o domínio do Vercel na lista de confiança para formulários POST
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'http://192.168.0.7:8000', # Seu IP local
    'https://*.vercel.app',    # Libera POSTs de qualquer site Vercel (HTTPS)
]

# Configuração do Crispy Forms
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# Application definition
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
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    "whitenoise.middleware.WhiteNoiseMiddleware", # <--- WhiteNoise para estáticos no Vercel
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'setup.urls'

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

# --- BANCO DE DADOS (CONFIGURAÇÃO VERCEL/NEON) ---

# 1. Primeiro tenta pegar a URL do banco que o Vercel cria (POSTGRES_URL)
#    ou uma genérica (DATABASE_URL)
database_url = os.getenv('POSTGRES_URL', os.getenv('DATABASE_URL'))

# Variáveis manuais (caso esteja usando Docker localmente)
db_user = os.getenv('POSTGRES_USER')
db_password = os.getenv('POSTGRES_PASSWORD')
db_name = os.getenv('POSTGRES_DB')
db_host = os.getenv('DB_HOST')
db_port = os.getenv('DB_PORT')

# CORREÇÃO IMPORTANTE PARA O VERCEL:
# O Vercel/Neon fornece a URL começando com 'postgres://', mas o Django exige 'postgresql://'
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

if database_url:
    # SE TIVER URL (Vercel ou Nuvem): Usa dj_database_url para configurar tudo sozinho
    DATABASES = {
        'default': dj_database_url.parse(database_url, conn_max_age=600, ssl_require=True)
    }
elif db_host:
    # SE TIVER HOST (Docker Local): Configuração manual do Postgres
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
    # FALLBACK (Desenvolvimento Local sem Docker): SQLite
    # Apenas para testes locais, pois no Vercel isso dá erro de leitura/escrita.
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Password validation
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

# Internationalization
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Porto_Velho'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Configuração de Media (Uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'