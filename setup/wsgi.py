"""
WSGI config for setup project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os
import logging
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'setup.settings')

application = get_wsgi_application()

app = application

# Executa migrações pendentes automaticamente ao inicializar no ambiente serverless (Vercel)
# Isso impede Server Error 500 caso novas colunas ou modelos tenham sido adicionados no Git
try:
    from django.core.management import call_command
    call_command('migrate', interactive=False)
except Exception as e:
    logging.getLogger('setup.wsgi').warning(f"[WSGI Auto-Migrate] Aviso ao executar migrate automático: {e}")