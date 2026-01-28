from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('gerencia-segura/', admin.site.urls), # Mudou de 'admin/' para algo único
    
    # Rotas de Login/Logout/Senha (Geridas pelo Django)
    path('accounts/', include('django.contrib.auth.urls')),
    
    # Rotas do App Estoque (Geridas pelo arquivo que criamos no passo 1)
    path('', include('estoque.urls')), 

    path('admin/', admin.site.urls),
    
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)