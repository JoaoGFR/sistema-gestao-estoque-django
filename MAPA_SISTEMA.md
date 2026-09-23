# 🗺️ Mapa de Arquitetura e Funções do Sistema (Guia de Navegação Token-Saver)

> **Objetivo:** Este documento serve como índice mestre e mapa topográfico de todo o código-fonte do projeto **JG TECH - Sistema de Gestão de Estoque e Precificação (SaaS Multi-tenant)**.  
> **Finalidade para Agentes de IA e Devs:** Antes de ler arquivos inteiros (como `views.py` com ~1350 linhas ou templates de 60KB), consulte este mapa para localizar exatamente as linhas, funções, modelos, formulários e fluxos necessários, **economizando até 90% dos tokens de contexto**.

---

## 📑 Sumário de Navegação Rápida

1. [Tabela Rápida de Funções e Views (`estoque/views.py`)](#-tabela-rápida-de-funções-e-views)
2. [Detalhamento de Views por Módulo de Negócio](#-detalhamento-de-views-por-módulo)
   - [2.1 SaaS, Autenticação & Onboarding](#21-saas-autenticação--onboarding)
   - [2.2 Dashboard & Métricas](#22-dashboard--métricas)
   - [2.3 Catálogo de Produtos & Histórico](#23-catálogo-de-produtos--histórico)
   - [2.4 Lotes & Entradas de Estoque](#24-lotes--entradas-de-estoque)
   - [2.5 Saídas de Estoque (FIFO/FEFO & Manual)](#25-saídas-de-estoque-fifofefo--manual)
   - [2.6 Empréstimos & Devoluções](#26-empréstimos--devoluções)
   - [2.7 Gestão de Equipe & Usuários Multi-tenant](#27-gestão-de-equipe--usuários-multi-tenant)
   - [2.8 Relatórios Gerenciais](#28-relatórios-gerenciais)
   - [2.9 Módulo de Backups (Local & Serverless/Vercel)](#29-módulo-de-backups)
   - [2.10 Simulador de Preços (Pricing & PDF)](#210-simulador-de-preços-pricing--pdf)
   - [2.11 Endpoints de API Assíncrona (JSON)](#211-endpoints-de-api-assíncrona-json)
3. [Mapa de Modelos de Dados (`estoque/models.py`)](#-mapa-de-modelos-de-dados-estoquemodelspy)
4. [Mapa de Formulários & Validações (`estoque/forms.py`)](#-mapa-de-formulários-estoqueformspy)
5. [Mapa de Rotas e URLs (`urls.py`)](#-mapa-de-rotas-e-urls)
6. [Catálogo de Templates HTML (`estoque/templates/`)](#-catálogo-de-templates-html)
7. [Mapa de Scripts Frontend & Chamadas Assíncronas (AJAX / Fetch)](#-mapa-de-scripts-frontend--ajax)
8. [Configurações do Projeto & Segurança (`setup/settings.py`)](#-configurações-e-segurança)
9. [Instruções para Agentes IA: Leitura de Alta Eficiência (Economia de Tokens)](#-guia-de-economia-de-tokens-para-agentes-ia)

---

## ⚡ Tabela Rápida de Funções e Views

Arquivo: [`estoque/views.py`](file:///c:/sistemaestoque/estoque/views.py)

| Função | Linhas | Rota / URL | Método | Decorators / Regras | Resumo |
| :--- | :--- | :--- | :--- | :--- | :--- |
| [`get_empresa_usuario`](file:///c:/sistemaestoque/estoque/views.py#L37-L41) | L37-41 | *Interna (Helper)* | Python | - | Retorna `user.userprofile.empresa` ou `None` |
| [`landing_page`](file:///c:/sistemaestoque/estoque/views.py#L51-L55) | L51-55 | `/` | GET | Público | Homepage oficial reformulada: Vitrine completa de módulos, PDV, Crediário, Simulador, tabela de preços, FAQ e atalhos dinâmicos para usuários logados |
| [`cadastro_saas`](file:///c:/sistemaestoque/estoque/views.py#L57-L93) | L57-93 | `/assinar/` | GET, POST | Rate limit (5/h por IP), `@transaction.atomic` | Cadastro seguro de nova empresa, usuário administrador (`e_dono=True`), login imediato e redirecionamento para o dashboard |
| [`dashboard`](file:///c:/sistemaestoque/estoque/views.py#L84-L149) | L84-149 | `/dashboard/` | GET | `@login_required` | Cards de totais, estoque baixo, financeiro e vencimentos |
| [`lista_produtos`](file:///c:/sistemaestoque/estoque/views.py#L152-L200) | L152-200 | `/produtos/` | GET | `@login_required` | Listagem com busca (`q`), filtros (crítico, categoria) e paginação |
| [`criar_produto`](file:///c:/sistemaestoque/estoque/views.py#L202-L217) | L202-217 | `/novo/` | GET, POST | `@login_required` | Formulário de criação de produto vinculado à empresa |
| [`editar_produto`](file:///c:/sistemaestoque/estoque/views.py#L219-L234) | L219-234 | `/editar/<int:pk>/` | GET, POST | `@login_required` | Edição dos dados cadastrais do produto |
| [`excluir_produto`](file:///c:/sistemaestoque/estoque/views.py#L372-L417) | L372-417 | `/excluir/<int:pk>/` | GET, POST | `@login_required`, `@transaction.atomic` | Exclusão segura com opção de inativação e preservação do histórico de vendas |
| [`alternar_status_produto`](file:///c:/sistemaestoque/estoque/views.py#L419-L428) | L419-428 | `/produto/<int:pk>/status/` | POST | `@login_required` | Ativação / Inativação rápida de produto com 1 clique |
| [`lista_lotes`](file:///c:/sistemaestoque/estoque/views.py#L247-L251) | L247-251 | `/estoque/entradas/` | GET | `@login_required` | Tabela histórica de lotes de entrada da empresa |
| [`entrada_estoque`](file:///c:/sistemaestoque/estoque/views.py#L253-L269) | L253-269 | `/estoque/nova-entrada/` | GET, POST | `@login_required` | Registro de novo lote com NF (upload) e quantidades |
| [`registrar_saida`](file:///c:/sistemaestoque/estoque/views.py#L273-L473) | L273-473 | `/saidas/nova/` | GET, POST | `@login_required`, `@transaction.atomic` | Baixas de estoque: Suporte a Múltiplos Itens (carrinho) ou lote individual |
| [`lista_saidas`](file:///c:/sistemaestoque/estoque/views.py#L475-L481) | L475-481 | `/saidas/` | GET | `@login_required` | Histórico de saídas de estoque com tag de baixa agrupada |
| [`registrar_emprestimo`](file:///c:/sistemaestoque/estoque/views.py#L486-L550) | L486-550 | `/emprestimos/novo/` | GET, POST | `@login_required`, `@transaction.atomic` | Empréstimo com baixa em lote por FIFO |
| [`lista_emprestimos`](file:///c:/sistemaestoque/estoque/views.py#L552-L558) | L552-558 | `/emprestimos/` | GET | `@login_required` | Listagem de empréstimos ativos e concluídos |
| [`devolver_item`](file:///c:/sistemaestoque/estoque/views.py#L561-L587) | L561-587 | `/emprestimos/devolver/<int:pk>/` | POST | `@login_required`, `@transaction.atomic` | Estorno do empréstimo de volta para o lote original |
| [`lista_funcionarios`](file:///c:/sistemaestoque/estoque/views.py#L590-L598) | L590-598 | `/equipe/` | GET | `@login_required`, dono (`e_dono`) | Gestão de membros e funcionários da empresa |
| [`criar_funcionario`](file:///c:/sistemaestoque/estoque/views.py#L600-L637) | L600-637 | `/equipe/novo/` | GET, POST | `@login_required`, dono (`e_dono`) | Cria usuário com prefixo de empresa (`empresa.usuario`) |
| [`editar_funcionario`](file:///c:/sistemaestoque/estoque/views.py#L641-L701) | L641-701 | `/equipe/editar/<int:pk>/` | GET, POST | `@login_required`, `@transaction.atomic`, dono (`e_dono`) | Edição de cadastro, função e status ativo/inativo com preservação de histórico |
| [`historico_produto`](file:///c:/sistemaestoque/estoque/views.py#L705-L742) | L705-742 | `/produtos/historico/<int:pk>/` | GET | `@login_required` | Gráficos Chart.js de compras vs vendas do produto |
| [`api_detalhes_produto`](file:///c:/sistemaestoque/estoque/views.py#L745-L756) | L745-756 | `/api/produto/<int:pk>/` | GET | `@login_required` | JSON: `controla_lote`, `unidade` |
| [`api_lotes_produto`](file:///c:/sistemaestoque/estoque/views.py#L759-L781) | L759-781 | `/api/lotes/<int:pk>/` | GET | `@login_required` | JSON: lista de lotes ativos com saldo e validade |
| [`criar_categoria_api`](file:///c:/sistemaestoque/estoque/views.py#L784-L797) | L784-797 | `/api/criar_categoria/` | POST | `@login_required` | Criação rápida de categoria via modal AJAX |
| [`criar_localizacao_api`](file:///c:/sistemaestoque/estoque/views.py#L800-L822) | L800-822 | `/api/criar_localizacao/` | POST | `@login_required` | Criação rápida de localização/endereço via modal AJAX |
| [`editar_lote`](file:///c:/sistemaestoque/estoque/views.py#L826-L859) | L826-859 | `/estoque/editar/<int:pk>/` | GET, POST | `@login_required`, `@transaction.atomic`, dono | Edição de lote com recálculo seguro de saldo atual |
| [`relatorios_gerais`](file:///c:/sistemaestoque/estoque/views.py#L862-L864) | L862-864 | `/relatorios/` | GET | `@login_required` | Menu central de navegação de relatórios |
| [`relatorio_estoque_saldo`](file:///c:/sistemaestoque/estoque/views.py#L867-L887) | L867-887 | `/relatorios/estoque/` | GET | `@login_required` | Relatório impresso de saldos físicos e valor contábil |
| [`editar_lote`](file:///c:/sistemaestoque/estoque/views.py#L840-L874) | L840-874 | `/estoque/editar/<int:pk>/` | GET, POST | `@login_required`, dono | Edição de lote com recálculo automático de estoque, preservação de datas (fabricação/validade em ISO) e layout responsivo móvel |
| [`excluir_entrada`](file:///c:/sistemaestoque/estoque/views.py#L890-L920) | L890-920 | `/entradas/excluir/<int:pk>/` | POST | `@login_required`, dono | Exclusão segura de lote com proteção contra Foreign Key |
| [`excluir_saida`](file:///c:/sistemaestoque/estoque/views.py#L930-L985) | L930-985 | `/saidas/excluir/<int:pk>/` | POST | `@login_required`, `@transaction.atomic`, dono/super | Cancelamento de saída manual e estorno; bloqueia cancelamento se for originada de Venda comercial |
| [`relatorio_movimentacoes`](file:///c:/sistemaestoque/estoque/views.py#L964-L1032) | L964-1032 | `/relatorios/movimentacoes/` | GET | `@login_required` | Extrato cronológico unificado (Entradas + Saídas + Empréstimos) |
| [`_is_serverless`](file:///c:/sistemaestoque/estoque/views.py#L1036-L1038) | L1036-1038 | *Interna (Helper)* | Python | - | Checa variável de ambiente `VERCEL` |
| [`painel_backups`](file:///c:/sistemaestoque/estoque/views.py#L1041-L1077) | L1041-1077 | `/backups/` | GET | `@login_required`, superuser | Listagem de backups `.json` em disco ou aviso serverless |
| [`criar_backup`](file:///c:/sistemaestoque/estoque/views.py#L1080-L1126) | L1080-1126 | `/backups/criar/` | POST | `@login_required`, superuser | Executa `dumpdata` (em disco ou stream memória Vercel) |
| [`baixar_backup`](file:///c:/sistemaestoque/estoque/views.py#L1129-L1146) | L1129-1146 | `/backups/baixar/<filename>/` | GET | `@login_required`, superuser, anti-path-traversal | Download de arquivo de backup sanitizado |
| [`excluir_backup`](file:///c:/sistemaestoque/estoque/views.py#L1149-L1161) | L1149-1161 | `/backups/excluir/<filename>/` | POST | `@login_required`, superuser, anti-path-traversal | Remoção física do arquivo de backup do disco |
| [`restaurar_backup`](file:///c:/sistemaestoque/estoque/views.py#L1164-L1181) | L1164-1181 | `/backups/restaurar/<filename>/`| POST | `@login_required`, superuser, anti-path-traversal | Executa `loaddata` para restauração do banco |
| [`simulador_preco`](file:///c:/sistemaestoque/estoque/views.py#L1185-L1198) | L1185-1198 | `/simulador/` | GET | `@login_required` | Interface completa do simulador de formação de preços com seletor modal de produto |
| [`criar_aliquota_api`](file:///c:/sistemaestoque/estoque/views.py#L1202-L1223) | L1202-1223 | `/api/aliquotas/criar/` | POST | `@login_required` | Criação de regime de imposto via modal AJAX |
| [`api_produto_preco`](file:///c:/sistemaestoque/estoque/views.py#L1227-L1247) | L1227-1247 | `/api/produto-preco/<int:pk>/`| GET | `@login_required` | JSON: preço médio, preço último lote, saldo e unidade |
| [`lista_simulacoes`](file:///c:/sistemaestoque/estoque/views.py#L1251-L1269) | L1251-1269 | `/simulacoes/` | GET | `@login_required` | Tabela paginada com cenários de preços salvos |
| [`salvar_simulacao_api`](file:///c:/sistemaestoque/estoque/views.py#L1273-L1330) | L1273-1330 | `/api/simulacoes/salvar/` | POST | `@login_required`, JSON Body | Grava simulação de preço com parsing seguro de decimais |
| [`excluir_simulacao`](file:///c:/sistemaestoque/estoque/views.py#L1334-L1341) | L1334-1341 | `/simulacoes/excluir/<int:pk>/`| POST | `@login_required` | Exclui cenário salvo da empresa |
| [`excluir_aliquota_api`](file:///c:/sistemaestoque/estoque/views.py#L1345-L1356) | L1345-1356 | `/api/aliquotas/excluir/<int:pk>/`| POST | `@login_required` | Exclui alíquota de imposto via chamada AJAX |
| [`simulador_pdf`](file:///c:/sistemaestoque/estoque/views.py#L1360-L1486) | L1360-1486 | `/simulador/pdf/` | GET | `@login_required` | Renderiza relatório analítico em HTML pronto para impressão/PDF |
| [`lista_simulacoes_pdf`](file:///c:/sistemaestoque/estoque/views.py#L1490-L1523) | L1490-1523 | `/simulacoes/pdf/` | GET | `@login_required` | Relatório consolidado em PDF de todas as simulações |
| [`lista_clientes`](file:///c:/sistemaestoque/estoque/views.py#L1543-L1590) | L1543-1590 | `/clientes/` | GET | `@login_required` | Listagem de clientes com filtros de inadimplência e status |
| [`criar_cliente`](file:///c:/sistemaestoque/estoque/views.py#L1594-L1614) | L1594-1614 | `/clientes/novo/` | GET, POST | `@login_required` | Cadastro completo de clientes com limite de crediário |
| [`editar_cliente`](file:///c:/sistemaestoque/estoque/views.py#L1617-L1639) | L1617-1639 | `/clientes/editar/<int:pk>/` | GET, POST | `@login_required` | Edição dos dados cadastrais do cliente |
| [`detalhe_cliente`](file:///c:/sistemaestoque/estoque/views.py#L1642-L1657) | L1642-1657 | `/clientes/ficha/<int:pk>/` | GET | `@login_required` | Ficha do cliente com extrato de crediário e histórico de compras |
| [`api_buscar_clientes`](file:///c:/sistemaestoque/estoque/views.py#L1660-L1705) | L1660-1705 | `/api/clientes/` | GET | `@login_required` | JSON: busca completa de clientes por Nome, CPF/CNPJ, Telefone, Email, Cidade, Endereço |
| [`api_buscar_produtos`](file:///c:/sistemaestoque/estoque/views.py#L1708-L1746) | L1708-1746 | `/api/produtos/` | GET | `@login_required` | JSON: busca completa de produtos por Nome, SKU, EAN/Código de barras, Categoria, Localização |
| [`registrar_venda`](file:///c:/sistemaestoque/estoque/views.py#L1750-L1973) | L1750-1973 | `/vendas/nova/` | GET, POST | `@login_required`, `@transaction.atomic` | PDV de vendas com modais pop-up para busca instantânea de produtos e clientes |
| [`lista_vendas`](file:///c:/sistemaestoque/estoque/views.py#L1916-L1960) | L1916-1960 | `/vendas/` | GET | `@login_required` | Histórico analítico de vendas com filtros e faturamento |
| [`detalhe_venda`](file:///c:/sistemaestoque/estoque/views.py#L1963-L1975) | L1963-1975 | `/vendas/<int:pk>/` | GET | `@login_required` | Recibo/comprovante de venda imprimível e detalhes de parcelas |
| [`cancelar_venda`](file:///c:/sistemaestoque/estoque/views.py#L1978-L2027) | L1978-2027 | `/vendas/<int:pk>/cancelar/` | POST | `@login_required`, `@transaction.atomic`, dono/super | Cancelamento de venda com estorno ao estoque e anulação de contas |
| [`painel_crediario`](file:///c:/sistemaestoque/estoque/views.py#L2034-L2114) | L2034-2114 | `/crediario/` | GET | `@login_required` | Painel financeiro de contas a receber, atrasos e recebimentos |
| [`baixar_parcela`](file:///c:/sistemaestoque/estoque/views.py#L2117-L2183) | L2117-2183 | `/crediario/baixar/<int:pk>/` | POST | `@login_required`, `@transaction.atomic` | Registro de quitação/amortização de parcelas no crediário |
| [`minha_assinatura`](file:///c:/sistemaestoque/estoque/views.py) | L2450+ | `/minha-assinatura/` | GET | `@login_required` | Painel do lojista: status da assinatura, dias restantes de trial/vigência e checkout |
| [`iniciar_checkout_mercadopago`](file:///c:/sistemaestoque/estoque/views.py) | L2480+ | `/assinatura/pagar/` | GET | `@login_required` | Gera preferência no Mercado Pago e redireciona para Pix/Cartão |
| [`simular_pagamento_mp`](file:///c:/sistemaestoque/estoque/views.py) | L2500+ | `/assinatura/simular-pagamento/` | GET | `@login_required` | Simulação rápida em ambiente de testes para validação sem cartão real |
| [`webhook_mercadopago`](file:///c:/sistemaestoque/estoque/views.py) | L2520+ | `/api/mercadopago/webhook/` | POST | `@csrf_exempt` | Notificação IPN do Mercado Pago que ativa +30 dias de assinatura automaticamente |
| [`painel_superadmin_assinaturas`](file:///c:/sistemaestoque/estoque/views.py) | L2560+ | `/superadmin/assinaturas/` | GET | `@login_required`, superuser | Painel Superadmin para gerenciar todas as empresas, vigências e pagamentos |
| [`prorrogar_trial_superadmin`](file:///c:/sistemaestoque/estoque/views.py) | L2610+ | `/superadmin/empresa/<pk>/prorrogar/` | POST | `@login_required`, superuser | Concede dias adicionais de degustação grátis (+3, +7, +15, +30 dias) |
| [`ativar_assinatura_superadmin`](file:///c:/sistemaestoque/estoque/views.py) | L2630+ | `/superadmin/empresa/<pk>/ativar/` | POST | `@login_required`, superuser | Ativação manual de vigência de assinatura (+30 dias) |
| [`toggle_bloqueio_empresa_superadmin`](file:///c:/sistemaestoque/estoque/views.py) | L2650+ | `/superadmin/empresa/<pk>/bloquear/` | POST | `@login_required`, superuser | Bloqueia ou desbloqueia o acesso de uma empresa ao sistema |



---

## 🔍 Detalhamento de Views por Módulo

### 2.1 SaaS, Autenticação & Onboarding
- **`get_empresa_usuario(user)`** [`L37-41`](file:///c:/sistemaestoque/estoque/views.py#L37-L41):
  - *Função auxiliar:* Tenta capturar `user.userprofile.empresa`. Retorna `None` se for superusuário Django puro ou usuário sem perfil.
- **`landing_page(request)`** [`L44-45`](file:///c:/sistemaestoque/estoque/views.py#L44-L45):
  - *Template:* [`estoque/landing.html`](file:///c:/sistemaestoque/estoque/templates/estoque/landing.html)
- **`cadastro_saas(request)`** [`L47-114`](file:///c:/sistemaestoque/estoque/views.py#L47-L114):
  - *Segurança:* Rate limiting baseado em IP usando cache Django (máximo 5 cadastros por hora).
  - *Form:* [`CadastroSaaSForm`](file:///c:/sistemaestoque/estoque/forms.py#L197-L234).
  - *Opção de Início:* O usuário pode escolher entre **3 Dias Grátis** (`trial`) ou **Pagar Agora** (`pagar_agora` - R$ 50,00 via Pix ou Cartão no Mercado Pago).
  - *Fluxo:* Cria `Empresa` -> Cria `User` -> Cria `UserProfile(e_dono=True)` -> Autentica com `login()` e redireciona para `dashboard` (se trial) ou `iniciar_checkout_mercadopago` (se pagar agora).
  - *Checkout Mercado Pago:* Exclui boletos bancários (`excluded_payment_types: [{'id': 'ticket'}]`), aceitando unicamente **Pix** e **Cartões**.

### 2.2 Dashboard & Métricas
- **`dashboard(request)`** [`L84-149`](file:///c:/sistemaestoque/estoque/views.py#L84-L149):
  - *Métricas calculadas no banco:*
    1. Total de produtos cadastrados da empresa.
    2. Total de categorias.
    3. Valor financeiro total em estoque: `Sum(quantidade_atual * preco_compra)` em lotes `ATIVO`.
    4. Produtos em nível crítico: `qtd_real < estoque_minimo`.
    5. Quantidade de empréstimos pendentes de devolução (`devolvido=False`).
    6. Últimas 5 saídas registradas (`SaidaEstoque`).
    7. Alerta de vencimentos: lotes ativos com validade entre hoje e 180 dias.
  - *Template:* [`estoque/dashboard.html`](file:///c:/sistemaestoque/estoque/templates/estoque/dashboard.html).

### 2.3 Catálogo de Produtos & Histórico
- **`lista_produtos(request)`** [`L152-200`](file:///c:/sistemaestoque/estoque/views.py#L152-L200):
  - *Filtros:* `q` (busca por nome, SKU ou EAN), `categoria`, `filtro=critico`.
  - *Anotação ORM:* `qtd_real = Coalesce(Sum('lotes__quantidade_atual', filter=Q(lotes__status='ATIVO')), 0)`.
  - *Paginação:* 10 itens por página.
  - *Template:* [`estoque/lista_produtos.html`](file:///c:/sistemaestoque/estoque/templates/estoque/lista_produtos.html).
- **`criar_produto(request)`** [`L202-217`](file:///c:/sistemaestoque/estoque/views.py#L202-L217):
  - *Form:* [`ProdutoForm`](file:///c:/sistemaestoque/estoque/forms.py#L28-L52).
  - *Template:* [`estoque/criar_produto.html`](file:///c:/sistemaestoque/estoque/templates/estoque/criar_produto.html).
- **`editar_produto(request, pk)`** [`L219-234`](file:///c:/sistemaestoque/estoque/views.py#L219-L234):
  - *Segurança:* Filtro obrigatório por `empresa` via `get_object_or_404`.
  - *Template:* [`estoque/criar_produto.html`](file:///c:/sistemaestoque/estoque/templates/estoque/criar_produto.html).
- **`excluir_produto(request, pk)`** [`L236-244`](file:///c:/sistemaestoque/estoque/views.py#L236-L244):
  - *Template:* [`estoque/confirmar_exclusao.html`](file:///c:/sistemaestoque/estoque/templates/estoque/confirmar_exclusao.html).
- **`historico_produto(request, pk)`** [`L525-563`](file:///c:/sistemaestoque/estoque/views.py#L525-L563):
  - *Gráficos:* Gera séries temporais em JSON (`dados_compra_json`, `dados_venda_json`) para renderizar curvas de preço de custo vs preço de venda com Chart.js.
  - *Template:* [`estoque/historico_produto.html`](file:///c:/sistemaestoque/estoque/templates/estoque/historico_produto.html).

### 2.4 Lotes & Entradas de Estoque
- **`lista_lotes(request)`** [`L247-251`](file:///c:/sistemaestoque/estoque/views.py#L247-L251):
  - *Template:* [`estoque/lista_lotes.html`](file:///c:/sistemaestoque/estoque/templates/estoque/lista_lotes.html).
- **`entrada_estoque(request)`** [`L253-269`](file:///c:/sistemaestoque/estoque/views.py#L253-L269):
  - *Upload:* Suporta arquivo de Nota Fiscal (`request.FILES`).
  - *Lógica de Inicialização:* Define `quantidade_atual = quantidade_inicial`.
  - *Form:* [`LoteForm`](file:///c:/sistemaestoque/estoque/forms.py#L55-L109).
  - *Template:* [`estoque/entrada_estoque.html`](file:///c:/sistemaestoque/estoque/templates/estoque/entrada_estoque.html).
- **`editar_lote(request, pk)`** [`L645-680`](file:///c:/sistemaestoque/estoque/views.py#L645-L680):
  - *Permissão:* Apenas dono (`e_dono`).
  - *Algoritmo de Recálculo:* Calcula a diferença entre a nova e a antiga `quantidade_inicial`, ajustando a `quantidade_atual` e impedindo valores negativos caso já tenha ocorrido saída.
  - *Template:* [`estoque/editar_lote.html`](file:///c:/sistemaestoque/estoque/templates/estoque/editar_lote.html).
- **`excluir_entrada(request, pk)`** [`L710-741`](file:///c:/sistemaestoque/estoque/views.py#L710-L741):
  - *Tratamento de Exceção:* Captura `django.db.models.ProtectedError` caso o lote possua saídas ou empréstimos ativos vinculados.

### 2.5 Saídas de Estoque (Baixas Múltiplas, FIFO/FEFO & Manual)
- **`registrar_saida(request)`** [`L273-473`](file:///c:/sistemaestoque/estoque/views.py#L273-L473):
  - *Concorrência & Atomicidade:* Protegido por `@transaction.atomic`, `with transaction.atomic():` e `.select_for_update()`.
  - **Fluxo 1 (Baixa Múltipla / Carrinho):** Recebe payload `itens_json` com múltiplos produtos, lotes e quantidades. Agrupa os itens sob o identificador único `codigo_grupo` (ex: `BX-YYMMDD-HEX`). Se qualquer item falhar por saldo insuficiente, reverte atomicamente toda a baixa.
  - **Fluxo 2 (Retrocompatibilidade):** Mantém fallback funcional para submissões individuais legadas via `SaidaEstoqueForm`.
  - **Dedução de Estoque:** Suporta tanto dedução por lote específico quanto automática por FEFO/FIFO.
  - *Template:* [`estoque/form_saida.html`](file:///c:/sistemaestoque/estoque/templates/estoque/form_saida.html).
- **`lista_saidas(request)`** [`L475-481`](file:///c:/sistemaestoque/estoque/views.py#L475-L481):
  - *Template:* [`estoque/lista_saidas.html`](file:///c:/sistemaestoque/estoque/templates/estoque/lista_saidas.html).
- **`excluir_saida(request, pk)`** [`L930-985`](file:///c:/sistemaestoque/estoque/views.py#L930-L985):
  - *Estorno Seguro:* Devolve a quantidade retirada de volta ao lote original (`saida.lote.quantidade_atual += qtd`). Se for saída legado sem lote, faz fallback para o lote mais recente do produto.
  - *Trava Anti-Duplicação de Vendas:* Bloqueia estorno de saídas vinculadas a Vendas comerciais (`codigo_grupo` iniciando com `VD-` ou via `ItemVenda`). O estorno físico deve ser feito obrigatoriamente através do cancelamento da venda para não duplicar saldo em estoque.



### 2.6 Empréstimos & Devoluções
- **`registrar_emprestimo(request)`** [`L371-436`](file:///c:/sistemaestoque/estoque/views.py#L371-L436):
  - *Algoritmo:* FIFO automático com trava `select_for_update()`. Divide o empréstimo em múltiplos registros caso a quantidade envolva mais de um lote ativo.
  - *Form:* [`EmprestimoForm`](file:///c:/sistemaestoque/estoque/forms.py#L113-L137).
  - *Template:* [`estoque/registrar_emprestimo.html`](file:///c:/sistemaestoque/estoque/templates/estoque/registrar_emprestimo.html).
- **`lista_emprestimos(request)`** [`L438-444`](file:///c:/sistemaestoque/estoque/views.py#L438-L444):
  - *Template:* [`estoque/lista_emprestimos.html`](file:///c:/sistemaestoque/estoque/templates/estoque/lista_emprestimos.html).
- **`devolver_item(request, pk)`** [`L446-473`](file:///c:/sistemaestoque/estoque/views.py#L446-L473):
  - *Estorno:* Incrementa a `quantidade_atual` do lote, reativa lote se estiver com status `ESGOTADO`, preenche `data_devolucao` e marca `devolvido = True`.

### 2.7 Gestão de Equipe & Usuários Multi-tenant
- **`lista_funcionarios(request)`** [`L476-484`](file:///c:/sistemaestoque/estoque/views.py#L476-L484):
  - *Permissão:* Restrito a donos de empresa (`request.user.userprofile.e_dono`).
  - *Template:* [`estoque/lista_funcionarios.html`](file:///c:/sistemaestoque/estoque/templates/estoque/lista_funcionarios.html).
- **`criar_funcionario(request)`** [`L486-523`](file:///c:/sistemaestoque/estoque/views.py#L486-L523):
  - *Padrão de Login:* Cria o login padronizado `{prefixo_empresa}.{sufixo_usuario}` para isolamento multi-tenant.
  - *Form:* [`FuncionarioForm`](file:///c:/sistemaestoque/estoque/forms.py#L193-L234).
  - *Template:* [`estoque/criar_funcionario.html`](file:///c:/sistemaestoque/estoque/templates/estoque/criar_funcionario.html).
- **`editar_funcionario(request, pk)`** [`L527-587`](file:///c:/sistemaestoque/estoque/views.py#L527-L587):
  - *Preservação de Histórico:* Atualiza a instância existente de `User` e `UserProfile` mantendo a chave primária `User.id` inalterada, o que preserva 100% dos vínculos de auditoria com `SaidaEstoque` e `Emprestimo`.
  - *Desativação Segura:* Permite alterar `is_active` para desativar ex-colaboradores em vez de excluí-los (mantendo o nome no extrato de movimentações).
  - *Anti-Lockout:* Impede que o único administrador ativo desative a própria conta ou revogue seu status de dono.
  - *Form:* [`EditarFuncionarioForm`](file:///c:/sistemaestoque/estoque/forms.py#L246-L308).
  - *Template:* [`estoque/editar_funcionario.html`](file:///c:/sistemaestoque/estoque/templates/estoque/editar_funcionario.html).

### 2.8 Relatórios Gerenciais
- **`relatorios_gerais(request)`** [`L682-685`](file:///c:/sistemaestoque/estoque/views.py#L682-L685):
  - *Template:* [`estoque/relatorios_index.html`](file:///c:/sistemaestoque/estoque/templates/estoque/relatorios_index.html).
- **`relatorio_estoque_saldo(request)`** [`L687-708`](file:///c:/sistemaestoque/estoque/views.py#L687-L708):
  - *Agregações:* Saldo total físico e valor monetário total (`Sum(quantidade_atual * preco_compra)`).
  - *Template:* [`estoque/relatorio_saldo.html`](file:///c:/sistemaestoque/estoque/templates/estoque/relatorio_saldo.html).
- **`relatorio_movimentacoes(request)`** [`L784-853`](file:///c:/sistemaestoque/estoque/views.py#L784-L853):
  - *Extrato Unificado:* Junta `Lote` (entradas), `SaidaEstoque` (saídas) e `Emprestimo` (empréstimos), ordena por data decrescente e filtra por período (`data_inicio`, `data_fim`) e tipo.
  - *Template:* [`estoque/relatorio_movimentacoes.html`](file:///c:/sistemaestoque/estoque/templates/estoque/relatorio_movimentacoes.html).

### 2.9 Módulo de Backups
- **`_is_serverless()`** [`L857-859`](file:///c:/sistemaestoque/estoque/views.py#L857-L859):
  - Detecta se a execução ocorre em container serverless (Vercel).
- **`painel_backups(request)`** [`L861-898`](file:///c:/sistemaestoque/estoque/views.py#L861-L898):
  - Lista arquivos `.json` na pasta `/backups/` com tamanho e data de modificação.
  - *Template:* [`estoque/painel_backups.html`](file:///c:/sistemaestoque/estoque/templates/estoque/painel_backups.html).
- **`criar_backup(request)`** [`L900-947`](file:///c:/sistemaestoque/estoque/views.py#L900-L947):
  - Executa `call_command('dumpdata')`. Em ambiente serverless, envia diretamente como stream HTTP para download; em local/Docker grava no disco.
- **`baixar_backup(request, filename)`** [`L949-967`](file:///c:/sistemaestoque/estoque/views.py#L949-L967):
  - Protegido contra Path Traversal (`os.path.realpath` e checagem de prefixo de diretório).
- **`excluir_backup(request, filename)`** [`L969-982`](file:///c:/sistemaestoque/estoque/views.py#L969-L982):
  - Exclui arquivo físico sanitizado.
- **`restaurar_backup(request, filename)`** [`L984-1002`](file:///c:/sistemaestoque/estoque/views.py#L984-L1002):
  - Executa `call_command('loaddata')` para reinjetar a massa de dados.

### 2.10 Simulador de Preços (Pricing & PDF)
- **`simulador_preco(request)`** [`L1005-1019`](file:///c:/sistemaestoque/estoque/views.py#L1005-L1019):
  - Interface SPA de precificação avançada com cálculo client-side dinâmico de Margem Realizada, Custo Efetivo, Markup por Dentro/Fora, Frete ponderado e Rateio de Outros Custos.
  - *Template:* [`estoque/simulador_preco.html`](file:///c:/sistemaestoque/estoque/templates/estoque/simulador_preco.html).
- **`lista_simulacoes(request)`** [`L1071-1090`](file:///c:/sistemaestoque/estoque/views.py#L1071-L1090):
  - *Template:* [`estoque/lista_simulacoes.html`](file:///c:/sistemaestoque/estoque/templates/estoque/lista_simulacoes.html).
- **`excluir_simulacao(request, pk)`** [`L1154-1162`](file:///c:/sistemaestoque/estoque/views.py#L1154-L1162):
  - Exclusão do registro de simulação.
- **`simulador_pdf(request)`** [`L1180-1307`](file:///c:/sistemaestoque/estoque/views.py#L1180-L1307):
  - Recalcula todas as fórmulas analíticas no Python e renderiza template estruturado para impressão / geração de PDF (proposta comercial / formação de preço).
  - *Template:* [`estoque/simulador_pdf.html`](file:///c:/sistemaestoque/estoque/templates/estoque/simulador_pdf.html).
- **`lista_simulacoes_pdf(request)`** [`L1310-1344`](file:///c:/sistemaestoque/estoque/views.py#L1310-L1344):
  - Exportação em formato de relatório consolidado para impressão.
  - *Template:* [`estoque/lista_simulacoes_pdf.html`](file:///c:/sistemaestoque/estoque/templates/estoque/lista_simulacoes_pdf.html).

### 2.11 Endpoints de API Assíncrona (JSON)
- **`api_detalhes_produto(request, pk)`** [`L565-577`](file:///c:/sistemaestoque/estoque/views.py#L565-L577):
  - Retorna `{ "controla_lote": bool, "unidade": str }`.
- **`api_lotes_produto(request, pk)`** [`L579-602`](file:///c:/sistemaestoque/estoque/views.py#L579-L602):
  - Retorna `[ { "id": int, "texto": str, "qtd_disponivel": int } ]`.
- **`criar_categoria_api(request)`** [`L604-618`](file:///c:/sistemaestoque/estoque/views.py#L604-L618):
  - Recebe `POST` com `nome`, persiste e responde `{ "id": int, "nome": str, "status": "success" }`.
- **`criar_localizacao_api(request)`** [`L620-643`](file:///c:/sistemaestoque/estoque/views.py#L620-L643):
  - Recebe `POST` com `nome`, persiste e responde `{ "id": int, "nome": str, "status": "success" }`.
- **`criar_aliquota_api(request)`** [`L1022-1044`](file:///c:/sistemaestoque/estoque/views.py#L1022-L1044):
  - Salva alíquota via form com retorno JSON `{ "id": int, "nome": str, "percentual": float }`.
- **`excluir_aliquota_api(request, pk)`** [`L1165-1177`](file:///c:/sistemaestoque/estoque/views.py#L1165-L1177):
  - Deleta registro e retorna confirmação JSON.
- **`api_produto_preco(request, pk)`** [`L1047-1068`](file:///c:/sistemaestoque/estoque/views.py#L1047-L1068):
  - Alimenta o simulador com `{ "id", "nome", "preco_medio", "preco_custo_lote", "saldo_total", "unidade", "qtd_ultimo_lote" }`.
- **`salvar_simulacao_api(request)`** [`L1093-1151`](file:///c:/sistemaestoque/estoque/views.py#L1093-L1151):
  - Recebe JSON via `request.body`, faz conversão e sanitização de tipos e salva instância de `SimulacaoPreco`.

---

## 🗄️ Mapa de Modelos de Dados (`estoque/models.py`)

Arquivo: [`estoque/models.py`](file:///c:/sistemaestoque/estoque/models.py)

| Modelo | Linhas | Campos Principais | Relações Chave | Métodos e `@property` |
| :--- | :--- | :--- | :--- | :--- |
| **`Empresa`** | L7-13 | `nome`, `cnpj`, `ativo` | Entidade raiz do Multi-tenant | `__str__` |
| **`UserProfile`** | L16-22 | `e_dono` | `user` (1:1 `User`), `empresa` (FK `Empresa`) | `__str__` |
| **`Categoria`** | L25-30 | `nome` | `empresa` (FK `Empresa`) | `__str__` |
| **`Localizacao`** | L33-38 | `nome` (Endereço/Prateleira) | `empresa` (FK `Empresa`) | `__str__` |
| **`UnidadeMedida`** | L41-50 | `UN`, `M`, `KG`, `L`, `CX`, `RL`, `PCT`, `GL`, `BG` | TextChoices enum | - |
| **`Produto`** | L52-87 | `nome`, `sku`, `ean`, `unidade`, `estoque_minimo`, `controla_lote` | `empresa` (FK), `categoria` (FK Null), `localizacao` (FK Null) | `@property saldo_total`<br>`@property preco_medio` |
| **`Lote`** | L89-121 | `numero_lote`, `preco_compra`, `fornecedor`, `data_fabricacao`, `data_validade`, `quantidade_inicial`, `quantidade_atual`, `numero_nota_fiscal`, `nota_fiscal`, `status` (`ATIVO`, `ESGOTADO`, `VENCIDO`) | `produto` (FK `Produto`, `related_name='lotes'`) | Sobrescrita de `save()` para atualizar status automaticamente para `ESGOTADO`/`ATIVO` |
| **`SaidaEstoque`** | L124-135| `quantidade`, `motivo`, `data`, `valor_venda`, `codigo_grupo` | `produto` (FK), `lote` (FK Null), `usuario` (FK Null `User`) | Identificador opcional `codigo_grupo` para agrupar saídas múltiplas na mesma transação |

| **`Emprestimo`** | L137-149| `quantidade`, `solicitante`, `data_saida`, `data_devolucao`, `devolvido`, `observacao` | `produto` (FK), `lote` (FK Null), `responsavel_saida` (FK `User`) | `__str__` |
| **`AliquotaImposto`**| L152-158| `nome`, `percentual` | `empresa` (FK `Empresa`) | `__str__` |
| **`SimulacaoPreco`** | L161-231| `preco_custo`, `quantidade_estoque`, `preco_custo_futuro`, `quantidade_futura`, `frete_valor`, `tipo_frete`, `outros_valor`, `tipo_outros`, `aliquota_nome`, `aliquota_percentual`, `margem_desejada`, `metodo`, `preco_sugerido`, `preco_praticado`, `lucro_liquido`, `margem_realizada` | `empresa` (FK), `produto` (FK) | `@property quantidade_total`<br>`@property lucro_total_lote`<br>`@property custo_efetivo` |
| **`Cliente`** | L238-285 | `nome`, `tipo_pessoa`, `cpf_cnpj`, `telefone`, `email`, `endereco`, `cidade`, `limite_credito`, `ativo`, `observacoes` | `empresa` (FK `Empresa`) | `@property saldo_devedor`<br>`@property limite_disponivel`<br>`@property tem_debitos_vencidos` |
| **`Venda`** | L288-340 | `codigo_venda`, `valor_subtotal`, `desconto`, `valor_total`, `forma_pagamento`, `status`, `status_pagamento`, `observacoes` | `empresa` (FK), `cliente` (FK Null), `usuario` (FK Null `User`) | `__str__` |
| **`ItemVenda`** | L343-356 | `quantidade`, `preco_unitario`, `subtotal` | `venda` (FK `Venda`), `produto` (FK), `lote` (FK Null), `saida_estoque` (FK Null) | `__str__` |
| **`ContaReceber`** | L359-402 | `numero_parcela`, `total_parcelas`, `valor_parcela`, `valor_pago`, `data_vencimento`, `data_pagamento`, `status` | `empresa` (FK), `cliente` (FK), `venda` (FK) | `@property saldo_restante`<br>`@property esta_vencida`<br>`@property dias_atraso` |
| **`PagamentoCrediario`**| L405-430 | `valor_recebido`, `forma_pagamento`, `data_recebimento`, `observacoes` | `empresa` (FK), `conta` (FK `ContaReceber`), `usuario` (FK Null) | `__str__` |

---

## 📝 Mapa de Formulários (`estoque/forms.py`)

Arquivo: [`estoque/forms.py`](file:///c:/sistemaestoque/estoque/forms.py)

| Formulário | Linhas | Modelo / Tipo | Campos | Lógicas Especiais e Validações |
| :--- | :--- | :--- | :--- | :--- |
| **`CategoriaForm`** | L10-16 | `Categoria` | `nome` | Estilização Bootstrap com placeholder |
| **`LocalizacaoForm`** | L18-24 | `Localizacao` | `nome` | Estilização Bootstrap com placeholder |
| **`ProdutoForm`** | L28-52 | `Produto` | `nome`, `sku`, `ean`, `categoria`, `unidade`, `estoque_minimo`, `localizacao`, `controla_lote` | Filtra no `__init__` apenas categorias e localizações pertencentes à empresa do usuário autenticado |
| **`LoteForm`** | L55-109 | `Lote` | `produto`, `numero_lote`, `preco_compra`, `fornecedor`, `data_fabricacao`, `data_validade`, `quantidade_inicial`, `numero_nota_fiscal`, `nota_fiscal` | Desabilita alteração de produto ao editar lote (`instance.pk`); No `clean()`, torna lote e validade obrigatórios se `produto.controla_lote == True` |
| **`EmprestimoForm`** | L113-137 | `Emprestimo` | `categoria_filtro`, `produto`, `quantidade`, `solicitante`, `observacao` | Campo auxiliar `categoria_filtro` para filtrar dropdown de produtos via JS |
| **`SaidaEstoqueForm`** | L139-173 | `SaidaEstoque` | `produto`, `lote_especifico`, `quantidade`, `valor_venda`, `motivo` | No `clean()`, valida consistência entre o lote específico selecionado e o produto informado |
| **`CadastroSaaSForm`** | L175-191 | Form padrão | `nome_completo`, `email`, `senha`, `nome_empresa` | `clean_email()` verifica duplicidade; `clean_senha()` valida força de senha via regras Django |
| **`FuncionarioForm`** | L193-234 | `User` | `first_name`, `last_name`, `username`, `email`, `password` | `clean_username()` sanitiza caracteres alfanuméricos com regex; valida força de senha |
| **`AliquotaImpostoForm`** | L236-243 | `AliquotaImposto` | `nome`, `percentual` | Inputs numéricos com casas decimais configuradas |
| **`EditarFuncionarioForm`** | L246-308 | Form padrão | `first_name`, `last_name`, `email`, `e_dono`, `is_active`, `nova_senha` | Valida colisão de e-mail com outros usuários, validação opcional de senha, preservação de integridade |
| **`ClienteForm`** | L318-348 | `Cliente` | `nome`, `tipo_pessoa`, `cpf_cnpj`, `telefone`, `email`, `endereco`, `cidade`, `limite_credito`, `ativo`, `observacoes` | Validação de limite de crédito não negativo; formatação de campos Bootstrap 5 |
| **`ReceberPagamentoForm`** | L351-372 | Form padrão | `valor_recebido`, `forma_pagamento`, `data_recebimento`, `observacoes` | Input destacado para valor recebido, data padrão hoje e seleção de forma de pagamento |


---

## 🌐 Mapa de Rotas e URLs

- Arquivo Raiz: [`setup/urls.py`](file:///c:/sistemaestoque/setup/urls.py)
  - `/gerencia-segura/` -> Django Admin Seguro (URL não padrão para proteção contra bots)
  - `/accounts/` -> Sistema de Autenticação padrão do Django (`login`, `logout`, etc.)
  - `/` -> Include de [`estoque/urls.py`](file:///c:/sistemaestoque/estoque/urls.py)
- Arquivo do App: [`estoque/urls.py`](file:///c:/sistemaestoque/estoque/urls.py)
  - Mapeia 34 rotas distribuídas em 11 módulos (conforme tabela rápida acima).

---

## 🎨 Catálogo de Templates HTML

Diretório: [`estoque/templates/estoque/`](file:///c:/sistemaestoque/estoque/templates/estoque/)

| Template | Finalidade Principal | Componentes / Bibliotecas |
| :--- | :--- | :--- |
| [`base.html`](file:///c:/sistemaestoque/estoque/templates/estoque/base.html) | Layout principal mestre, navbar, mensagens flash e footer | Bootstrap 5.3, Bootstrap Icons, TomSelect, Google Fonts Inter |
| [`landing.html`](file:///c:/sistemaestoque/estoque/templates/estoque/landing.html) | Página de apresentação pública para conversão SaaS | Hero section, benefícios, cards de planos |
| [`cadastro_saas.html`](file:///c:/sistemaestoque/estoque/templates/estoque/cadastro_saas.html) | Formulário de autocadastro da nova empresa | Card de formulário centralizado |
| [`dashboard.html`](file:///c:/sistemaestoque/estoque/templates/estoque/dashboard.html) | Painel de controle com KPIs, alertas de validade e atalhos | Cards estatísticos, badges de status, tabelas |
| [`lista_produtos.html`](file:///c:/sistemaestoque/estoque/templates/estoque/lista_produtos.html) | Catálogo de mercadorias e insumos | Barra de busca, badge de estoque crítico, paginação |
| [`criar_produto.html`](file:///c:/sistemaestoque/estoque/templates/estoque/criar_produto.html) | Cadastro/Edição de produto | Modais para cadastro rápido de Categoria e Localização |
| [`historico_produto.html`](file:///c:/sistemaestoque/estoque/templates/estoque/historico_produto.html) | Análise gráfica temporal de preços de compra e venda | Chart.js com curvas comparativas e tabelas |
| [`entrada_estoque.html`](file:///c:/sistemaestoque/estoque/templates/estoque/entrada_estoque.html) | Lançamento de lote / nota fiscal | JS dinâmico para alternar campos de lote/validade |
| [`lista_lotes.html`](file:///c:/sistemaestoque/estoque/templates/estoque/lista_lotes.html) | Listagem histórica de entradas de mercadorias | Badges de status (Ativo, Esgotado, Vencido) |
| [`editar_lote.html`](file:///c:/sistemaestoque/estoque/templates/estoque/editar_lote.html) | Correção administrativa de lote já cadastrado | Formulário com aviso de impacto no estoque |
| [`form_saida.html`](file:///c:/sistemaestoque/estoque/templates/estoque/form_saida.html) | Registro de baixas múltiplas ou individuais no estoque | Layout em 2 colunas, carrinho dinâmico com tabela em tempo real, validação de saldo e atalhos |
| [`lista_saidas.html`](file:///c:/sistemaestoque/estoque/templates/estoque/lista_saidas.html) | Histórico de todas as saídas efetuadas | Exibe usuário, motivo, badge de código de baixa agrupada e botão de cancelamento |
| [`registrar_emprestimo.html`](file:///c:/sistemaestoque/estoque/templates/estoque/registrar_emprestimo.html) | Saída consignada de itens/ferramentas | Filtro de produtos por categoria em tempo real (JS) |
| [`lista_emprestimos.html`](file:///c:/sistemaestoque/estoque/templates/estoque/lista_emprestimos.html) | Controle de itens emprestados e devolução | Badge "Pendente" vs "Devolvido", ação de devolver |
| [`lista_funcionarios.html`](file:///c:/sistemaestoque/estoque/templates/estoque/lista_funcionarios.html) | Listagem da equipe da empresa | Badge de Administrador vs Funcionário, botão de ação para Editar |
| [`criar_funcionario.html`](file:///c:/sistemaestoque/estoque/templates/estoque/criar_funcionario.html) | Criação de novo usuário para a empresa | Exibe prefixo fixo da empresa no input do login |
| [`editar_funcionario.html`](file:///c:/sistemaestoque/estoque/templates/estoque/editar_funcionario.html) | Edição de cadastro de usuário/colaborador | Formulário seguro com alerta de preservação de histórico, bloqueio de login e redefinição opcional de senha |
| [`relatorios_index.html`](file:///c:/sistemaestoque/estoque/templates/estoque/relatorios_index.html) | Hub central de relatórios | Cards de navegação para saldos e movimentações |
| [`relatorio_saldo.html`](file:///c:/sistemaestoque/estoque/templates/estoque/relatorio_saldo.html) | Posição física e financeira de estoque | Totalizadores contábeis e layout pronto para impressão |
| [`relatorio_movimentacoes.html`](file:///c:/sistemaestoque/estoque/templates/estoque/relatorio_movimentacoes.html) | Extrato analítico de movimentações | Filtros por data e tipo (Entrada, Saída, Empréstimo) |
| [`simulador_preco.html`](file:///c:/sistemaestoque/estoque/templates/estoque/simulador_preco.html) | Simulador completo de formação de preços | Motor de cálculo JS, rateios de frete, impostos e modais |
| [`simulador_pdf.html`](file:///c:/sistemaestoque/estoque/templates/estoque/simulador_pdf.html) | Relatório analítico de precificação | Layout formal com breakdown de custos para impressão/PDF |
| [`lista_simulacoes.html`](file:///c:/sistemaestoque/estoque/templates/estoque/lista_simulacoes.html) | Histórico de cenários de preços salvos | Paginação, filtros e visualização de margens |
| [`lista_simulacoes_pdf.html`](file:///c:/sistemaestoque/estoque/templates/estoque/lista_simulacoes_pdf.html) | Relatório geral de simulações salvas | Visão corporativa em PDF |
| [`painel_backups.html`](file:///c:/sistemaestoque/estoque/templates/estoque/painel_backups.html) | Painel administrativo de dumps de banco | Gerenciamento de arquivos `.json` e restauração |
| [`confirmar_exclusao.html`](file:///c:/sistemaestoque/estoque/templates/estoque/confirmar_exclusao.html) | Modal/Página de confirmação de deleção | Prevenção contra exclusões acidentais |
| [`registration/login.html`](file:///c:/sistemaestoque/estoque/templates/registration/login.html) | Tela de Login do sistema | Formulário com autenticação Django e rate limiting |
| [`lista_clientes.html`](file:///c:/sistemaestoque/estoque/templates/estoque/lista_clientes.html) | Listagem e filtros de clientes cadastrados | Cards de inadimplência, filtros de débito e busca instantânea |
| [`form_cliente.html`](file:///c:/sistemaestoque/estoque/templates/estoque/form_cliente.html) | Formulário de criação e edição de cliente | Abas de dados pessoais, endereço e limites de crediário |
| [`detalhe_cliente.html`](file:///c:/sistemaestoque/estoque/templates/estoque/detalhe_cliente.html) | Ficha financeira e cadastral do cliente | Extrato de crediário, modal de baixa de parcelas e histórico de vendas |
| [`form_venda.html`](file:///c:/sistemaestoque/estoque/templates/estoque/form_venda.html) | Terminal de Vendas e Checkout (PDV) | Layout 2 colunas, seleção de cliente/crédito, troco em dinheiro e crediário |
| [`lista_vendas.html`](file:///c:/sistemaestoque/estoque/templates/estoque/lista_vendas.html) | Histórico geral de vendas faturadas | Filtros por forma de pagamento, status, faturamento total |
| [`detalhe_venda.html`](file:///c:/sistemaestoque/estoque/templates/estoque/detalhe_venda.html) | Comprovante/recibo formal da venda | Impressão térmica/A4 (`window.print`), cancelamento de venda |
| [`painel_crediario.html`](file:///c:/sistemaestoque/estoque/templates/estoque/painel_crediario.html) | Gestão financeira de contas a receber | KPIs de atraso/recebimento, modal de quitação de parcela |


---

## 🔌 Mapa de Scripts Frontend & AJAX

| Template | Função / Listener JS | Linha Aprox. | Endpoint Chamado | Finalidade |
| :--- | :--- | :--- | :--- | :--- |
| `criar_produto.html` | `salvarAuxiliar(tipo)` | L123 | `/api/criar_categoria/` ou `/api/criar_localizacao/` | Salva nova categoria/localização no modal e já seleciona no dropdown sem recarregar a tela |
| `entrada_estoque.html` | `verificarProduto()` | L81 | `/api/produto/<pk>/` | Checa se o produto exige lote/validade e exibe/oculta os campos no formulário |
| `form_saida.html` | `carregarLotes()` | L58 | `/api/lotes/<pk>/` | Popula dropdown de lotes específicos do produto selecionado |
| `form_saida.html` | `atualizarLimiteQuantidade()` | L102 | - | Define o atributo `max` do input de quantidade baseado no saldo do lote selecionado |
| `registrar_emprestimo.html` | `filtrarProdutos()` | L67 | - | Filtra os produtos exibidos de acordo com a categoria selecionada |
| `simulador_preco.html` | `carregarInfoProduto(id)` | L467 | `/api/produto-preco/<pk>/` | Preenche automaticamente preço médio, saldo e unidade ao escolher produto |
| `simulador_preco.html` | `calcularPreco()` | L527 | - | Motor matemático client-side de Markup Inside/Outside, Frete, Outros e Ponto de Equilíbrio |
| `simulador_preco.html` | Form Alíquota (`submit`) | L818 | `/api/aliquotas/criar/` | Cadastra novo imposto via modal e atualiza lista de opções |
| `simulador_preco.html` | Botão Excluir Alíquota | L911 | `/api/aliquotas/excluir/<pk>/` | Remove imposto e recalcula simulador |
| `simulador_preco.html` | Botão Salvar Simulação | L1068 | `/api/simulacoes/salvar/` | Envia payload com parâmetros do cenário de precificação |

---

## 🔒 Configurações e Segurança

Arquivo: [`setup/settings.py`](file:///c:/sistemaestoque/setup/settings.py)

- **Rate Limiting de Login:** Integrado com `django-axes` ([`L78, L91, L100`](file:///c:/sistemaestoque/setup/settings.py#L78-L102)).
- **Autenticação Segura:** Backend `axes.backends.AxesBackend` seguido por `ModelBackend`.
- **URL Admin Oculta:** `/gerencia-segura/` em vez de `/admin/` (proteção contra varredura automatizada).
- **Isolamento de Tenants:** Toda query em `views.py` e `forms.py` é estritamente filtrada por `empresa=request.user.userprofile.empresa`.
- **Transações Concorrentes:** Uso sistemático de `@transaction.atomic` e `.select_for_update()` em baixas de estoque, empréstimos e devoluções para evitar *race conditions*.
- **Proteção de Arquivos:** `os.path.realpath` contra *path traversal* em downloads e restaurações de backups.

---

## 💡 Guia de Economia de Tokens para Agentes IA

Quando for implementar ou debugar funcionalidades neste repositório, **SIGA ESTE PROTOCOLO**:

1. **Localize a linha exata neste mapa:** Identifique o intervalo no sumário acima (ex: `registrar_saida` está entre `L272` e `L362`).
2. **Leia apenas o trecho necessário com `view_file`:**
   - Exemplo: `view_file(AbsolutePath='c:/sistemaestoque/estoque/views.py', StartLine=270, EndLine=365)`.
   - **NÃO leia o arquivo inteiro** (1344 linhas consom mais de 15.000 tokens desnecessariamente).
3. **Para edições cirúrgicas:**
   - Use `replace_file_content` especificando `StartLine` e `EndLine` precisos para garantir substituição atômica sem falhas.
4. **Para entender formulários ou validações:**
   - Consulte diretamente o intervalo em `estoque/forms.py` (tabela da Seção 4).
5. **Para novos endpoints ou views:**
   - Adicione a rota em [`estoque/urls.py`](file:///c:/sistemaestoque/estoque/urls.py), a view em [`estoque/views.py`](file:///c:/sistemaestoque/estoque/views.py) e atualize este mapa.
