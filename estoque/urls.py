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
    path('produto/<int:pk>/status/', views.alternar_status_produto, name='alternar_status_produto'),
    
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
    path('equipe/editar/<int:pk>/', views.editar_funcionario, name='editar_funcionario'),
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
    path('backups/restaurar-upload/', views.restaurar_backup_upload, name='restaurar_backup_upload'),

    # --- TABELA DE PREÇOS DE VENDA ---
    path('tabela-precos/', views.tabela_precos, name='tabela_precos'),
    path('api/produto/<int:pk>/atualizar-preco/', views.atualizar_preco_produto_api, name='atualizar_preco_produto_api'),
    path('api/produto/<int:pk>/historico-precos/', views.api_historico_precos, name='api_historico_precos'),

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

    # --- CLIENTES ---
    path('clientes/', views.lista_clientes, name='lista_clientes'),
    path('clientes/novo/', views.criar_cliente, name='criar_cliente'),
    path('clientes/editar/<int:pk>/', views.editar_cliente, name='editar_cliente'),
    path('clientes/ficha/<int:pk>/', views.detalhe_cliente, name='detalhe_cliente'),
    path('api/clientes/', views.api_buscar_clientes, name='api_buscar_clientes'),
    path('api/produtos/', views.api_buscar_produtos, name='api_buscar_produtos'),

    # --- VENDAS ---
    path('vendas/', views.lista_vendas, name='lista_vendas'),
    path('vendas/nova/', views.registrar_venda, name='registrar_venda'),
    path('vendas/<int:pk>/', views.detalhe_venda, name='detalhe_venda'),
    path('vendas/<int:pk>/cupom/', views.imprimir_cupom_venda, name='imprimir_cupom_venda'),
    path('vendas/<int:pk>/cancelar/', views.cancelar_venda, name='cancelar_venda'),

    # --- CREDIÁRIO / CONTAS A RECEBER ---
    path('crediario/', views.painel_crediario, name='painel_crediario'),
    path('crediario/baixar/<int:pk>/', views.baixar_parcela, name='baixar_parcela'),

    # --- GESTÃO DE ASSINATURAS SAAS & MERCADO PAGO ---
    path('minha-assinatura/', views.minha_assinatura, name='minha_assinatura'),
    path('assinatura/pagar/', views.iniciar_checkout_mercadopago, name='iniciar_checkout_mercadopago'),
    path('assinatura/simular-pagamento/', views.simular_pagamento_mp, name='simular_pagamento_mp'),
    path('api/mercadopago/webhook/', views.webhook_mercadopago, name='webhook_mercadopago'),

    # --- PAINEL SUPERADMIN ---
    path('superadmin/assinaturas/', views.painel_superadmin_assinaturas, name='painel_superadmin_assinaturas'),
    path('superadmin/empresa/<int:pk>/prorrogar/', views.prorrogar_trial_superadmin, name='prorrogar_trial_superadmin'),
    path('superadmin/empresa/<int:pk>/ativar/', views.ativar_assinatura_superadmin, name='ativar_assinatura_superadmin'),
    path('superadmin/empresa/<int:pk>/bloquear/', views.toggle_bloqueio_empresa_superadmin, name='toggle_bloqueio_empresa_superadmin'),
    path('superadmin/pagamento/<int:pk>/salvar-order-id/', views.salvar_order_id_pagamento_superadmin, name='salvar_order_id_pagamento_superadmin'),
    path('superadmin/executar-migracoes/', views.executar_migracoes_superadmin, name='executar_migracoes_superadmin'),
    path('superadmin/pagamento-teste-1-real/', views.iniciar_checkout_teste_superadmin, name='iniciar_checkout_teste_superadmin'),
]