from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Rotas de Login/Logout/Senha (Geridas pelo Django)
    path('accounts/', include('django.contrib.auth.urls')),
    
    # Rotas do App Estoque (Geridas pelo arquivo que criamos no passo 1)
    path('', include('estoque.urls')), 
]