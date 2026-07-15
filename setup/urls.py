from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('gerencia-segura/', admin.site.urls), 
    
  
    path('accounts/', include('django.contrib.auth.urls')),
    
  
    path('', include('estoque.urls')), 

    path('admin/', admin.site.urls),
    
]

from django.views.static import serve
from django.urls import re_path

urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]