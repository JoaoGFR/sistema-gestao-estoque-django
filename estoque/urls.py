from django.urls import path
from . import views

urlpatterns = [
    # --- PÚBLICO ---
    path('', views.landing_page, name='landing_page'),
    path('assinar/', views.cadastro_saas, name='cadastro_saas'),

    # --- DASHBOARD ---
    path('dashboard/', views.dashboard, name='dashboard'),

    # --- PRODUTOS ---
    path('produtos/', views.lista_produtos, name='lista_produtos'),
    path('novo/', views.criar_produto, name='criar_produto'),
    path('editar/<int:pk>/', views.editar_produto, name='editar_produto'),
    path('excluir/<int:pk>/', views.excluir_produto, name='excluir_produto'),
    
    # Histórico de Preços (Novo)
    path('produtos/historico/<int:pk>/', views.historico_produto, name='historico_produto'),

    # --- LOTES (ENTRADAS) ---
    path('estoque/entradas/', views.lista_lotes, name='lista_lotes'),
    path('estoque/nova-entrada/', views.entrada_estoque, name='entrada_estoque'),

    # --- SAÍDAS (BAIXAS) ---
    path('saidas/', views.lista_saidas, name='lista_saidas'),
    path('saidas/nova/', views.registrar_saida, name='registrar_saida'),

    # --- EMPRÉSTIMOS ---
    path('emprestimos/', views.lista_emprestimos, name='lista_emprestimos'),
    path('emprestimos/novo/', views.registrar_emprestimo, name='registrar_emprestimo'),
    path('emprestimos/devolver/<int:pk>/', views.devolver_item, name='devolver_item'),

    # --- EQUIPE ---
    path('equipe/', views.lista_funcionarios, name='lista_funcionarios'),
    path('equipe/novo/', views.criar_funcionario, name='criar_funcionario'),
    path('api/criar_localizacao/', views.criar_localizacao_api, name='criar_localizacao_api'),
 
    path('api/produto/<int:pk>/', views.api_detalhes_produto, name='api_detalhes_produto'),
    
 
    path('api/lotes/<int:pk>/', views.api_lotes_produto, name='api_lotes_produto'),
    path('estoque/editar/<int:pk>/', views.editar_lote, name='editar_lote'),
   
    path('api/criar_categoria/', views.criar_categoria_api, name='criar_categoria_api'),

    path('relatorios/', views.relatorios_gerais, name='relatorios_gerais'),
    path('relatorios/estoque/', views.relatorio_estoque_saldo, name='relatorio_estoque_saldo'),
    path('relatorios/movimentacoes/', views.relatorio_movimentacoes, name='relatorio_movimentacoes'),
    path('entradas/excluir/<int:pk>/', views.excluir_entrada, name='excluir_entrada'),
    path('saidas/excluir/<int:pk>/', views.excluir_saida, name='excluir_saida'),
    path('backups/', views.painel_backups, name='painel_backups'),
    path('backups/criar/', views.criar_backup, name='criar_backup'),
    path('backups/baixar/<str:filename>/', views.baixar_backup, name='baixar_backup'),
    path('backups/excluir/<str:filename>/', views.excluir_backup, name='excluir_backup'),
    path('backups/restaurar/<str:filename>/', views.restaurar_backup, name='restaurar_backup'),

    # --- SIMULADOR DE PREÇOS ---
    path('simulador/', views.simulador_preco, name='simulador_preco'),
    path('api/aliquotas/criar/', views.criar_aliquota_api, name='criar_aliquota_api'),
    path('api/produto-preco/<int:pk>/', views.api_produto_preco, name='api_produto_preco'),
    path('simulador/pdf/', views.simulador_pdf, name='simulador_pdf'),

    # --- SIMULAÇÕES SALVAS ---
    path('simulacoes/', views.lista_simulacoes, name='lista_simulacoes'),
    path('api/simulacoes/salvar/', views.salvar_simulacao_api, name='salvar_simulacao_api'),
    path('simulacoes/excluir/<int:pk>/', views.excluir_simulacao, name='excluir_simulacao'),
    path('simulacoes/pdf/', views.lista_simulacoes_pdf, name='lista_simulacoes_pdf'),

    # --- EXCLUIR ALÍQUOTA ---
    path('api/aliquotas/excluir/<int:pk>/', views.excluir_aliquota_api, name='excluir_aliquota_api'),
]