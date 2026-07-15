from django.contrib import admin
from .models import Produto, Emprestimo, SaidaEstoque, Empresa, UserProfile, AliquotaImposto, SimulacaoPreco

# Configuração para editar o UserProfile dentro da tela de Usuário
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False

class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]

# Remove o admin padrão e coloca o nosso com Profile
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

admin.site.register(Empresa)
admin.site.register(UserProfile)
admin.site.register(Produto)
admin.site.register(Emprestimo)
admin.site.register(SaidaEstoque)
admin.site.register(AliquotaImposto)
admin.site.register(SimulacaoPreco)