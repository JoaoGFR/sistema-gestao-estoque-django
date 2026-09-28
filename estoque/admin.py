from django.contrib import admin
from .models import (
    Produto, Emprestimo, HistoricoEmprestimo, SaidaEstoque, Empresa, UserProfile,
    AliquotaImposto, SimulacaoPreco, HistoricoPreco, PagamentoAssinatura, ConfiguracaoEmpresa,
    Venda, ItemVenda, Cliente, ContaReceber
)

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

@admin.register(ConfiguracaoEmpresa)
class ConfiguracaoEmpresaAdmin(admin.ModelAdmin):
    list_display = (
        'empresa', 'modulo_emprestimos', 'modulo_vendas_pdv',
        'modulo_clientes_crediario', 'modulo_simulador_precos', 'modulo_controle_lotes'
    )
    search_fields = ('empresa__nome',)

class HistoricoEmprestimoInline(admin.TabularInline):
    model = HistoricoEmprestimo
    extra = 0
    readonly_fields = ('tipo_acao', 'quantidade', 'saldo_restante', 'usuario', 'data_registro', 'observacao')
    can_delete = False

@admin.register(Emprestimo)
class EmprestimoAdmin(admin.ModelAdmin):
    list_display = ('id', 'produto', 'lote', 'quantidade', 'quantidade_devolvida', 'solicitante', 'devolvido', 'data_saida', 'data_devolucao')
    list_filter = ('devolvido', 'produto__empresa')
    search_fields = ('solicitante', 'produto__nome', 'lote__numero_lote', 'observacao')
    inlines = [HistoricoEmprestimoInline]

@admin.register(HistoricoEmprestimo)
class HistoricoEmprestimoAdmin(admin.ModelAdmin):
    list_display = ('id', 'emprestimo', 'tipo_acao', 'quantidade', 'saldo_restante', 'usuario', 'data_registro')
    list_filter = ('tipo_acao', 'data_registro')
    search_fields = ('emprestimo__solicitante', 'emprestimo__produto__nome', 'observacao')
admin.site.register(SaidaEstoque)
admin.site.register(AliquotaImposto)
admin.site.register(SimulacaoPreco)
admin.site.register(HistoricoPreco)

@admin.register(PagamentoAssinatura)
class PagamentoAssinaturaAdmin(admin.ModelAdmin):
    list_display = ('id', 'empresa', 'valor', 'status', 'metodo', 'mp_order_id', 'mp_payment_id', 'data_criacao')
    search_fields = ('empresa__nome', 'mp_order_id', 'mp_payment_id', 'mp_preference_id')
    list_filter = ('status', 'metodo')

class ItemVendaInline(admin.TabularInline):
    model = ItemVenda
    extra = 0
    readonly_fields = ('produto', 'nome_produto', 'lote', 'quantidade', 'preco_unitario', 'subtotal', 'saida_estoque')

@admin.register(Venda)
class VendaAdmin(admin.ModelAdmin):
    list_display = ('codigo_venda', 'empresa', 'cliente', 'usuario', 'valor_subtotal', 'desconto', 'valor_adicional', 'valor_total', 'forma_pagamento', 'status', 'status_pagamento', 'data_venda')
    list_filter = ('forma_pagamento', 'status', 'status_pagamento', 'data_venda', 'empresa')
    search_fields = ('codigo_venda', 'cliente__nome', 'usuario__username', 'observacoes', 'descricao_adicional')
    inlines = [ItemVendaInline]

admin.site.register(Cliente)
admin.site.register(ContaReceber)