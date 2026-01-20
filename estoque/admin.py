from django.contrib import admin
from .models import Produto, Emprestimo, SaidaEstoque

# Configuração para mostrar mais detalhes na listagem do admin (Opcional, mas ajuda muito)
class EmprestimoAdmin(admin.ModelAdmin):
    list_display = ('produto', 'nome_funcionario', 'data_saida', 'devolvido')
    list_filter = ('devolvido', 'data_saida')
    search_fields = ('nome_funcionario', 'produto__nome')

class SaidaEstoqueAdmin(admin.ModelAdmin):
    list_display = ('produto', 'quantidade', 'usuario', 'data')

# Registra as tabelas
admin.site.register(Produto)
admin.site.register(Emprestimo, EmprestimoAdmin)
admin.site.register(SaidaEstoque, SaidaEstoqueAdmin)