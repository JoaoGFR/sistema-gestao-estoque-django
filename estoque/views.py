import logging
import re
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout
from django.contrib.auth.models import User 
from django.contrib import messages
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Sum, F, Q, Case, When, IntegerField
from django.db.models.functions import Coalesce
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from django.db import transaction
from django.http import JsonResponse
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)
from .models import (
    Produto, Emprestimo, SaidaEstoque, Empresa, UserProfile, Lote, Categoria,
    Localizacao, AliquotaImposto, SimulacaoPreco, Cliente, Venda, ItemVenda,
    ContaReceber, PagamentoCrediario, PagamentoAssinatura, HistoricoPreco
)
from .mercadopago_service import (
    criar_preferencia_assinatura, consultar_pagamento_mp,
    consultar_order_mp, verificar_assinatura_webhook,
    processar_aprovacao_assinatura, is_mercadopago_configured,
    sincronizar_pagamentos_pendentes,
    VALOR_ASSINATURA_PADRAO
)
from django.core.paginator import Paginator
from django.db.models.functions import Coalesce
from django.db import transaction
import json
from django.core.serializers.json import DjangoJSONEncoder
from datetime import timedelta, datetime
from itertools import chain
from operator import attrgetter
from django.db.models import ProtectedError
from .forms import (
    ProdutoForm, EmprestimoForm, SaidaEstoqueForm, CadastroSaaSForm,
    FuncionarioForm, LoteForm, AliquotaImpostoForm, EditarFuncionarioForm,
    ClienteForm, ReceberPagamentoForm
)
import os
from django.conf import settings
from django.core.management import call_command
from django.http import FileResponse, Http404, HttpResponse
import io
from django.contrib import messages
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required


def get_empresa_usuario(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    try:
        return user.userprofile.empresa
    except (ObjectDoesNotExist, AttributeError):
        return None


def landing_page(request):
    empresa = None
    if request.user.is_authenticated:
        empresa = get_empresa_usuario(request.user)
    return render(request, 'estoque/landing.html', {'empresa': empresa})

@transaction.atomic
def cadastro_saas(request):
    if request.user.is_authenticated:
        messages.info(request, "Você já está conectado ao sistema.")
        return redirect('dashboard')

    if request.method == 'POST':
        # [SEGURANÇA] Rate limiting por IP: máximo de 5 cadastros por hora para evitar flooding/DoS
        ip_cliente = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR')
        chave_cache = f"rate_limit_cadastro_{ip_cliente}"
        tentativas = cache.get(chave_cache, 0)
        if tentativas >= 5:
            messages.error(request, "Muitas tentativas de cadastro a partir deste endereço IP. Aguarde uma hora antes de tentar novamente.")
            return render(request, 'estoque/cadastro_saas.html', {'form': CadastroSaaSForm()})

        form = CadastroSaaSForm(request.POST)
        opcao_pagamento = request.POST.get('opcao_pagamento', 'trial')
        if form.is_valid():
            cache.set(chave_cache, tentativas + 1, timeout=3600)
            agora = timezone.now()
            nova_empresa = Empresa.objects.create(
                nome=form.cleaned_data['nome_empresa'],
                cnpj=None,   
                ativo=True,
                status_assinatura='TRIAL',
                trial_fim=agora + timedelta(days=3),
                data_criacao=agora
            )
            email_limpo = form.cleaned_data['email']
            novo_usuario = User.objects.create_user(
                username=email_limpo,
                email=email_limpo,
                password=form.cleaned_data['senha'],
                first_name=form.cleaned_data['nome_completo']
            )
            UserProfile.objects.create(
                user=novo_usuario,
                empresa=nova_empresa,
                e_dono=True
            )
            login(request, novo_usuario, backend='django.contrib.auth.backends.ModelBackend')

            if opcao_pagamento == 'pagar_agora':
                messages.success(request, f"Bem-vindo, {novo_usuario.first_name}! Conclua o pagamento via Pix ou Cartão para ativar sua assinatura.")
                return redirect('iniciar_checkout_mercadopago')

            messages.success(request, f"Bem-vindo, {novo_usuario.first_name}! Sua conta foi criada com 3 dias de acesso grátis completo ao sistema.")
            return redirect('dashboard')
    else:
        form = CadastroSaaSForm()
    return render(request, 'estoque/cadastro_saas.html', {'form': form})

# --- DASHBOARD 
@login_required
def dashboard(request):
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        return render(request, 'estoque/dashboard.html', {
            'total_produtos': 0, 
            'total_categorias': 0, 
            'estoque_baixo': 0, 
            'emprestimos_pendentes': 0, 
            'ultimas_saidas': [],
            'valor_total_estoque': Decimal('0.00'), 
            'total_itens_estoque': 0,
            'lotes_vencendo': [],
            'qtd_lotes_vencendo': 0,
            'faturamento_mes': Decimal('0.00'),
            'vendas_hoje_total': Decimal('0.00'),
            'qtd_vendas_hoje': 0,
            'qtd_vendas_mes': 0,
            'ticket_medio': Decimal('0.00'),
            'total_crediario_aberto': Decimal('0.00'),
            'total_crediario_vencido': Decimal('0.00'),
            'qtd_contas_vencidas': 0,
            'total_recebido_mes': Decimal('0.00'),
            'ultimas_vendas': [],
            'produtos_criticos': [],
            'dias_labels_json': '[]',
            'dias_valores_json': '[]',
            'formas_labels_json': '[]',
            'formas_valores_json': '[]',
            'cat_labels_json': '[]',
            'cat_valores_json': '[]',
        })
    
    hoje = timezone.now().date()
    mes_atual = hoje.month
    ano_atual = hoje.year
    daqui_90_dias = hoje + timedelta(days=90)

    # 1. FINANCEIRO DE VENDAS (PDV)
    vendas_mes_qs = Venda.objects.filter(empresa=empresa, data_venda__year=ano_atual, data_venda__month=mes_atual, status='CONCLUIDA')
    faturamento_mes = vendas_mes_qs.aggregate(total=Sum('valor_total'))['total'] or Decimal('0.00')
    qtd_vendas_mes = vendas_mes_qs.count()
    ticket_medio = (faturamento_mes / qtd_vendas_mes) if qtd_vendas_mes > 0 else Decimal('0.00')

    vendas_hoje_qs = Venda.objects.filter(empresa=empresa, data_venda__date=hoje, status='CONCLUIDA')
    vendas_hoje_total = vendas_hoje_qs.aggregate(total=Sum('valor_total'))['total'] or Decimal('0.00')
    qtd_vendas_hoje = vendas_hoje_qs.count()

    # 2. ESTOQUE & PATRIMÔNIO
    total_produtos = Produto.objects.filter(empresa=empresa).count()
    total_categorias = Categoria.objects.filter(empresa=empresa).count()
    
    lotes_ativos = Lote.objects.filter(produto__empresa=empresa, status='ATIVO')
    valor_total_estoque = lotes_ativos.aggregate(
        total=Sum(F('quantidade_atual') * F('preco_compra'))
    )['total'] or Decimal('0.00')
    total_itens_estoque = lotes_ativos.aggregate(total=Sum('quantidade_atual'))['total'] or 0

    # 3. ALERTAS DE ESTOQUE BAIXO
    produtos_anotados = Produto.objects.filter(empresa=empresa).annotate(
        qtd_real=Coalesce(Sum('lotes__quantidade_atual', filter=Q(lotes__status='ATIVO')), 0)
    )
    produtos_criticos_qs = produtos_anotados.filter(qtd_real__lt=F('estoque_minimo'))
    estoque_baixo = produtos_criticos_qs.count()
    produtos_criticos = produtos_criticos_qs.select_related('categoria')[:5]

    # 4. CREDIÁRIO & CONTAS A RECEBER
    contas_abertas = ContaReceber.objects.filter(empresa=empresa, status__in=['PENDENTE', 'ATRASADO'])
    total_crediario_aberto = contas_abertas.aggregate(
        total=Sum(F('valor_parcela') - F('valor_pago'))
    )['total'] or Decimal('0.00')

    contas_vencidas = ContaReceber.objects.filter(
        empresa=empresa, 
        status='ATRASADO'
    ).select_related('cliente', 'venda').order_by('data_vencimento')
    total_crediario_vencido = contas_vencidas.aggregate(
        total=Sum(F('valor_parcela') - F('valor_pago'))
    )['total'] or Decimal('0.00')
    qtd_contas_vencidas = contas_vencidas.count()

    total_recebido_mes = PagamentoCrediario.objects.filter(
        empresa=empresa,
        data_recebimento__date__gte=hoje.replace(day=1)
    ).aggregate(total=Sum('valor_recebido'))['total'] or Decimal('0.00')

    # 5. EMPRÉSTIMOS PENDENTES
    emprestimos_pendentes = Emprestimo.objects.filter(
        produto__empresa=empresa, 
        devolvido=False
    ).count()

    # 6. VENCIMENTOS PRÓXIMOS (PRÓXIMOS 90 DIAS)
    lotes_vencendo = lotes_ativos.filter(
        quantidade_atual__gt=0,
        data_validade__range=[hoje, daqui_90_dias]
    ).select_related('produto').order_by('data_validade')[:5]
    qtd_lotes_vencendo = lotes_ativos.filter(
        quantidade_atual__gt=0,
        data_validade__range=[hoje, daqui_90_dias]
    ).count()

    # 7. ÚLTIMAS VENDAS E SAÍDAS
    ultimas_vendas = Venda.objects.filter(empresa=empresa).select_related('cliente', 'usuario').order_by('-data_venda')[:6]
    ultimas_saidas = SaidaEstoque.objects.filter(
        produto__empresa=empresa
    ).select_related('produto').order_by('-data')[:6]

    # 8. DADOS PARA GRÁFICOS (Chart.js)
    # Gráfico 1: Vendas dos Últimos 7 Dias
    dias_labels = []
    dias_valores = []
    for i in range(6, -1, -1):
        dia = hoje - timedelta(days=i)
        dias_labels.append(dia.strftime('%d/%m'))
        soma_dia = Venda.objects.filter(
            empresa=empresa, 
            data_venda__date=dia, 
            status='CONCLUIDA'
        ).aggregate(total=Sum('valor_total'))['total'] or Decimal('0.00')
        dias_valores.append(float(soma_dia))

    # Gráfico 2: Formas de Pagamento no Mês
    mapa_formas = {
        'DINHEIRO': 'Dinheiro',
        'PIX': 'PIX',
        'DEBITO': 'Débito',
        'CREDITO': 'Crédito',
        'CREDIARIO': 'Crediário'
    }
    formas_qs = Venda.objects.filter(
        empresa=empresa,
        data_venda__year=ano_atual,
        data_venda__month=mes_atual,
        status='CONCLUIDA'
    ).values('forma_pagamento').annotate(total=Sum('valor_total')).order_by('-total')

    formas_labels = []
    formas_valores = []
    for item in formas_qs:
        formas_labels.append(mapa_formas.get(item['forma_pagamento'], item['forma_pagamento']))
        formas_valores.append(float(item['total'] or 0))

    # Gráfico 3: Saldo por Categoria
    categorias_qs = (
        Produto.objects.filter(empresa=empresa, categoria__isnull=False, lotes__status='ATIVO')
        .values('categoria__nome')
        .annotate(qtd_total=Sum('lotes__quantidade_atual'))
        .filter(qtd_total__gt=0)
        .order_by('-qtd_total')[:5]
    )

    cat_labels = [c['categoria__nome'] for c in categorias_qs]
    cat_valores = [c['qtd_total'] for c in categorias_qs]

    contexto = {
        'total_produtos': total_produtos,
        'total_categorias': total_categorias,
        'valor_total_estoque': valor_total_estoque,
        'total_itens_estoque': total_itens_estoque,
        'estoque_baixo': estoque_baixo,
        'produtos_criticos': produtos_criticos,
        'emprestimos_pendentes': emprestimos_pendentes,
        'faturamento_mes': faturamento_mes,
        'vendas_hoje_total': vendas_hoje_total,
        'qtd_vendas_hoje': qtd_vendas_hoje,
        'qtd_vendas_mes': qtd_vendas_mes,
        'ticket_medio': ticket_medio,
        'total_crediario_aberto': total_crediario_aberto,
        'total_crediario_vencido': total_crediario_vencido,
        'qtd_contas_vencidas': qtd_contas_vencidas,
        'total_recebido_mes': total_recebido_mes,
        'lotes_vencendo': lotes_vencendo,
        'qtd_lotes_vencendo': qtd_lotes_vencendo,
        'ultimas_vendas': ultimas_vendas,
        'ultimas_saidas': ultimas_saidas,
        'dias_labels_json': json.dumps(dias_labels),
        'dias_valores_json': json.dumps(dias_valores),
        'formas_labels_json': json.dumps(formas_labels),
        'formas_valores_json': json.dumps(formas_valores),
        'cat_labels_json': json.dumps(cat_labels),
        'cat_valores_json': json.dumps(cat_valores),
    }
    return render(request, 'estoque/dashboard.html', contexto)

# --- PRODUTOS ---
@login_required
def lista_produtos(request):
    empresa = get_empresa_usuario(request.user)
    
    # Parâmetros da URL 
    query = request.GET.get('q', '').strip()
    filtro_critico = request.GET.get('filtro', '')
    categoria_id = request.GET.get('categoria', '')
    filtro_status = request.GET.get('status', 'ativos')
    filtro_tipo = request.GET.get('tipo', '')  # 'venda', 'insumo'

    produtos = Produto.objects.filter(empresa=empresa)

    total_ativos = Produto.objects.filter(empresa=empresa, ativo=True).count()
    total_inativos = Produto.objects.filter(empresa=empresa, ativo=False).count()
    total_produtos = total_ativos + total_inativos
    total_venda = Produto.objects.filter(empresa=empresa, ativo=True, disponivel_venda=True).count()
    total_insumo = Produto.objects.filter(empresa=empresa, ativo=True, disponivel_venda=False).count()

    total_critico = Produto.objects.filter(empresa=empresa, ativo=True).annotate(
        qtd_real=Coalesce(Sum('lotes__quantidade_atual', filter=Q(lotes__status='ATIVO')), 0)
    ).filter(qtd_real__lte=F('estoque_minimo')).count()

    if filtro_status == 'inativos':
        produtos = produtos.filter(ativo=False)
    elif filtro_status == 'todos':
        pass
    else:  # padrão 'ativos'
        produtos = produtos.filter(ativo=True)

    if filtro_tipo == 'venda':
        produtos = produtos.filter(disponivel_venda=True)
    elif filtro_tipo == 'insumo':
        produtos = produtos.filter(disponivel_venda=False)

    produtos = produtos.annotate(
        qtd_real=Coalesce(Sum('lotes__quantidade_atual', filter=Q(lotes__status='ATIVO')), 0)
    )

    # 3. Aplica Filtros
    if query:
        produtos = produtos.filter(
            Q(nome__icontains=query) |
            Q(sku__icontains=query) |
            Q(ean__icontains=query)
        )
    
    if categoria_id:
        produtos = produtos.filter(categoria_id=categoria_id)

    if filtro_critico == 'critico':
        produtos = produtos.filter(qtd_real__lte=F('estoque_minimo'))

    # 4. Ordenação
    produtos = produtos.order_by('nome')

    # 5. Paginação (20 itens por página)
    paginator = Paginator(produtos, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    categorias = Categoria.objects.filter(empresa=empresa).order_by('nome')

    return render(request, 'estoque/lista_produtos.html', {
        'page_obj': page_obj,
        'query': query,
        'filtro_critico': filtro_critico,
        'filtro_status': filtro_status,
        'filtro_tipo': filtro_tipo,
        'total_ativos': total_ativos,
        'total_inativos': total_inativos,
        'total_produtos': total_produtos,
        'total_venda': total_venda,
        'total_insumo': total_insumo,
        'total_critico': total_critico,
        'categorias': categorias,
        'categoria_selecionada': int(categoria_id) if categoria_id else None
    })

@login_required
def criar_produto(request):
    empresa = get_empresa_usuario(request.user)
    
    if request.method == 'POST':
        form = ProdutoForm(request.user, request.POST)
        if form.is_valid():
            produto = form.save(commit=False)
            produto.empresa = empresa
            produto.save()
            
            # Registra histórico inicial de preço se houver preço de venda definido
            if produto.preco_venda and produto.preco_venda > 0:
                HistoricoPreco.objects.create(
                    empresa=empresa,
                    produto=produto,
                    preco_anterior=Decimal('0.00'),
                    preco_novo=produto.preco_venda,
                    usuario=request.user,
                    motivo="Definição de preço no cadastro do produto"
                )
                
            messages.success(request, 'Produto cadastrado com sucesso! Agora adicione um Lote para incluir estoque.')
            return redirect('lista_produtos')
    else:
        form = ProdutoForm(request.user)
        
    return render(request, 'estoque/criar_produto.html', {'form': form, 'produto': None})

@login_required
def editar_produto(request, pk):
    empresa = get_empresa_usuario(request.user)
    produto = get_object_or_404(Produto, pk=pk, empresa=empresa)
    preco_anterior = produto.preco_venda
    disponivel_anterior = produto.disponivel_venda
    
    if request.method == 'POST':
        form = ProdutoForm(request.user, request.POST, instance=produto)
        if form.is_valid():
            produto_atualizado = form.save()
            
            # Verifica se o preço mudou ou se o produto passou a ser para venda com preço
            if produto_atualizado.preco_venda != preco_anterior:
                motivo = "Ajuste de preço no cadastro"
                if not disponivel_anterior and produto_atualizado.disponivel_venda:
                    motivo = "Ativação de produto para venda no PDV"
                elif disponivel_anterior and not produto_atualizado.disponivel_venda:
                    motivo = "Desativação de produto para venda"
                    
                HistoricoPreco.objects.create(
                    empresa=empresa,
                    produto=produto_atualizado,
                    preco_anterior=preco_anterior or Decimal('0.00'),
                    preco_novo=produto_atualizado.preco_venda,
                    usuario=request.user,
                    motivo=motivo
                )
                
            messages.success(request, 'Produto atualizado com sucesso!')
            return redirect('lista_produtos')
    else:
        form = ProdutoForm(request.user, instance=produto)
        
    return render(request, 'estoque/criar_produto.html', {'form': form, 'produto': produto})

@login_required
def excluir_produto(request, pk):
    empresa = get_empresa_usuario(request.user)
    produto = get_object_or_404(Produto, pk=pk, empresa=empresa)
    
    # Métricas para orientar o usuário na decisão
    qtd_vendas = ItemVenda.objects.filter(produto=produto).count()
    saldo_estoque = produto.saldo_total
    emprestimos_pendentes = Emprestimo.objects.filter(produto=produto, devolvido=False).count()
    
    if request.method == 'POST':
        acao = request.POST.get('acao', 'excluir')
        
        # Opção 1: Inativar (Preserva histórico perfeitamente e oculta do PDV/Entradas)
        if acao == 'inativar':
            produto.ativo = False
            produto.save(update_fields=['ativo'])
            messages.success(request, f"O produto '{produto.nome}' foi inativado com sucesso. Ele não aparecerá mais no PDV nem nas opções de entrada.")
            return redirect('lista_produtos')
            
        # Opção 2: Excluir definitivamente
        try:
            nome_produto = produto.nome
            with transaction.atomic():
                # Garante que todo histórico de vendas preserve o nome do produto mesmo após a exclusão física
                ItemVenda.objects.filter(produto=produto).update(nome_produto=nome_produto)
                produto.delete()
            messages.success(request, f"Produto '{nome_produto}' excluído com sucesso.")
            return redirect('lista_produtos')
        except ProtectedError:
            messages.error(request, f"Não foi possível excluir o produto '{produto.nome}' diretamente devido a vínculos com outros registros protegidos. Recomendamos inativá-lo.")
            return redirect('lista_produtos')
        except Exception as e:
            messages.error(request, f"Erro ao tentar excluir o produto: {str(e)}")
            return redirect('lista_produtos')
            
    return render(request, 'estoque/confirmar_exclusao.html', {
        'produto': produto,
        'item': produto,
        'qtd_vendas': qtd_vendas,
        'saldo_estoque': saldo_estoque,
        'emprestimos_pendentes': emprestimos_pendentes,
    })

@login_required
def alternar_status_produto(request, pk):
    empresa = get_empresa_usuario(request.user)
    produto = get_object_or_404(Produto, pk=pk, empresa=empresa)
    if request.method == 'POST':
        produto.ativo = not produto.ativo
        produto.save(update_fields=['ativo'])
        status_txt = "ativado" if produto.ativo else "inativado"
        messages.success(request, f"Produto '{produto.nome}' foi {status_txt} com sucesso.")
    return redirect('lista_produtos')

# --- LOTES (ENTRADAS) ---
@login_required
def lista_lotes(request):
    empresa = get_empresa_usuario(request.user)
    lotes = Lote.objects.filter(produto__empresa=empresa).order_by('-data_entrada')
    return render(request, 'estoque/lista_lotes.html', {'lotes': lotes})

@login_required
def entrada_estoque(request):
    empresa = get_empresa_usuario(request.user)
    if request.method == 'POST':
        form = LoteForm(request.user, request.POST, request.FILES)
        if form.is_valid():
            lote = form.save(commit=False)
            if lote.produto.empresa != empresa:
                return redirect('lista_produtos')
            
            lote.quantidade_atual = lote.quantidade_inicial
            lote.save()
            messages.success(request, 'Lote registrado com sucesso!')
            return redirect('lista_lotes')
    else:
        form = LoteForm(user=request.user)
    produtos = Produto.objects.filter(empresa=empresa, ativo=True).select_related('categoria', 'localizacao').order_by('nome')
    return render(request, 'estoque/entrada_estoque.html', {'form': form, 'produtos': produtos})


# --- SAÍDAS (FEFO & BAIXA MÚLTIPLA) ---
@login_required
@transaction.atomic
def registrar_saida(request):
    import json
    import uuid
    empresa = get_empresa_usuario(request.user)
    error_message = None

    if request.method == 'POST':
        itens_json = request.POST.get('itens_json')

        # -----------------------------------------------------------------
        # FLUXO 1: BAIXA MÚLTIPLA (NOVO MOTOR MULTI-ITEM)
        # -----------------------------------------------------------------
        if itens_json:
            try:
                itens = json.loads(itens_json)
                motivo_geral = request.POST.get('motivo', '').strip()
                if not motivo_geral:
                    error_message = "Por favor, informe o motivo ou destino geral da baixa."
                elif not itens or not isinstance(itens, list):
                    error_message = "Adicione ao menos um item à lista de baixa antes de confirmar."
                else:
                    codigo_grupo = f"BX-{timezone.now().strftime('%y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
                    total_pecas = 0
                    total_itens_processados = 0

                    with transaction.atomic():
                        for idx, item in enumerate(itens, 1):
                            prod_id = item.get('produto_id')
                            qtd_solicitada = int(item.get('quantidade', 0))
                            lote_id = item.get('lote_id')
                            valor_venda = item.get('valor_venda')
                            if valor_venda is not None and valor_venda != '':
                                try:
                                    valor_venda = float(valor_venda)
                                except (ValueError, TypeError):
                                    valor_venda = None
                            else:
                                valor_venda = None

                            if qtd_solicitada <= 0:
                                raise ValueError(f"Quantidade inválida informada para o item #{idx}.")

                            produto = Produto.objects.select_for_update().get(id=prod_id, empresa=empresa)

                            # FLUXO 1.A: Lote Específico Manual
                            if lote_id:
                                lote = Lote.objects.select_for_update().get(id=lote_id, produto=produto)
                                if lote.quantidade_atual < qtd_solicitada:
                                    raise ValueError(f"Saldo insuficiente no Lote '{lote.numero_lote}' do produto '{produto.nome}'. Disponível: {lote.quantidade_atual}, solicitado: {qtd_solicitada}.")

                                lote.quantidade_atual -= qtd_solicitada
                                lote.save()

                                SaidaEstoque.objects.create(
                                    produto=produto,
                                    lote=lote,
                                    quantidade=qtd_solicitada,
                                    motivo=f"{motivo_geral} (Lote: {lote.numero_lote})",
                                    usuario=request.user,
                                    valor_venda=valor_venda,
                                    codigo_grupo=codigo_grupo
                                )
                            # FLUXO 1.B: Baixa Automática (FEFO / FIFO)
                            else:
                                if produto.saldo_total < qtd_solicitada:
                                    raise ValueError(f"Saldo insuficiente para o produto '{produto.nome}'. Total em estoque: {produto.saldo_total}, solicitado: {qtd_solicitada}.")

                                lotes_ativos = Lote.objects.select_for_update().filter(
                                    produto=produto,
                                    status='ATIVO',
                                    quantidade_atual__gt=0
                                ).order_by('data_validade', 'data_entrada')

                                qtd_restante = qtd_solicitada
                                lotes_afetados = []

                                for l in lotes_ativos:
                                    if qtd_restante <= 0:
                                        break
                                    qtd_retirar = min(qtd_restante, l.quantidade_atual)
                                    l.quantidade_atual -= qtd_retirar
                                    l.save()

                                    SaidaEstoque.objects.create(
                                        produto=produto,
                                        lote=l,
                                        quantidade=qtd_retirar,
                                        motivo=f"{motivo_geral} (Auto: Lote {l.numero_lote})",
                                        usuario=request.user,
                                        valor_venda=valor_venda,
                                        codigo_grupo=codigo_grupo
                                    )
                                    qtd_restante -= qtd_retirar
                                    lotes_afetados.append(l.numero_lote)

                            total_pecas += qtd_solicitada
                            total_itens_processados += 1


                    messages.success(request, f"Baixa múltipla confirmada com sucesso! Código #{codigo_grupo} ({total_itens_processados} produto(s) baixados, totalizando {total_pecas} unidade(s)).")
                    return redirect('lista_saidas')

            except (ValueError, Produto.DoesNotExist, Lote.DoesNotExist) as e:
                error_message = str(e)
            except Exception as e:
                error_message = f"Erro técnico ao processar baixa: {str(e)}"

        # -----------------------------------------------------------------
        # FLUXO 2: RETROCOMPATIBILIDADE (BAIXA INDIVIDUAL LEGADO VIA FORM)
        # -----------------------------------------------------------------
        else:
            form = SaidaEstoqueForm(user=request.user, data=request.POST)
            if form.is_valid():
                produto = form.cleaned_data['produto']
                qtd_solicitada = form.cleaned_data['quantidade']
                motivo = form.cleaned_data['motivo']
                lote_escolhido = form.cleaned_data['lote_especifico']
                valor_venda = form.cleaned_data.get('valor_venda')
                
                if produto.empresa != empresa:
                    return redirect('lista_produtos')

                if lote_escolhido:
                    lote_escolhido = Lote.objects.select_for_update().get(id=lote_escolhido.id)
                    if lote_escolhido.produto != produto:
                        error_message = "O lote selecionado não pertence ao produto informado."
                    elif lote_escolhido.quantidade_atual < qtd_solicitada:
                        error_message = f"O Lote {lote_escolhido.numero_lote} só tem {lote_escolhido.quantidade_atual} unidades. Você pediu {qtd_solicitada}."
                    else:
                        lote_escolhido.quantidade_atual -= qtd_solicitada
                        lote_escolhido.save() 
                        
                        SaidaEstoque.objects.create(
                            produto=produto,
                            lote=lote_escolhido,
                            quantidade=qtd_solicitada,
                            motivo=f"{motivo} (Lote Manual: {lote_escolhido.numero_lote})",
                            usuario=request.user,
                            valor_venda=valor_venda 
                        )
                        messages.success(request, f"Saída manual do lote {lote_escolhido.numero_lote} realizada!")
                        return redirect('lista_saidas')
                else: 
                    if produto.saldo_total < qtd_solicitada:
                        error_message = f"Saldo Insuficiente! Total disponível: {produto.saldo_total}"
                    else:
                        lotes = Lote.objects.select_for_update().filter(
                            produto=produto, 
                            status='ATIVO', 
                            quantidade_atual__gt=0
                        ).order_by('data_validade', 'data_entrada')

                        qtd_restante = qtd_solicitada
                        lotes_afetados = []

                        for lote in lotes:
                            if qtd_restante <= 0: 
                                break
                            qtd_retirar = min(qtd_restante, lote.quantidade_atual)
                            lote.quantidade_atual -= qtd_retirar
                            lote.save()
                            
                            SaidaEstoque.objects.create(
                                produto=produto,
                                lote=lote,
                                quantidade=qtd_retirar,
                                motivo=f"{motivo} (Auto: Lote {lote.numero_lote})",
                                usuario=request.user,
                                valor_venda=valor_venda
                            )
                            qtd_restante -= qtd_retirar
                            lotes_afetados.append(lote.numero_lote)

                        messages.success(request, f"Saída automática realizada com sucesso (Lotes: {', '.join(lotes_afetados)}).")
                        return redirect('lista_saidas')

    # Dados para alimentar o seletor rápido no frontend
    produtos_qs = Produto.objects.filter(empresa=empresa).annotate(
        saldo_ativo=Coalesce(Sum('lotes__quantidade_atual', filter=Q(lotes__status='ATIVO')), 0)
    ).order_by('nome')

    produtos_lista = [
        {
            'id': p.id,
            'nome': p.nome,
            'sku': p.sku or '',
            'unidade': p.get_unidade_display(),
            'saldo': p.saldo_ativo
        }
        for p in produtos_qs
    ]

    form = SaidaEstoqueForm(user=request.user)

    return render(request, 'estoque/form_saida.html', {
        'form': form,
        'produtos': produtos_qs,
        'produtos_json': json.dumps(produtos_lista, default=str),
        'error_message': error_message
    })

@login_required
def lista_saidas(request):
    empresa = get_empresa_usuario(request.user)
    saidas = SaidaEstoque.objects.filter(
        produto__empresa=empresa
    ).select_related('produto', 'lote', 'usuario').order_by('-data')
    return render(request, 'estoque/lista_saidas.html', {'saidas': saidas})


# --- EMPRÉSTIMOS ---
@login_required
@transaction.atomic
def registrar_emprestimo(request):
    empresa = get_empresa_usuario(request.user)
    
    if request.method == 'POST':
        form = EmprestimoForm(request.user, request.POST)
        if form.is_valid():
            dados_emprestimo = form.save(commit=False)
            produto = dados_emprestimo.produto
            qtd_solicitada = dados_emprestimo.quantidade 
            
            # 1. VALIDAÇÃO TOTAL
            estoque_total = Lote.objects.filter(
                produto=produto, 
                status='ATIVO', 
                produto__empresa=empresa 
            ).aggregate(total=Sum('quantidade_atual'))['total'] or 0
            
            if estoque_total < qtd_solicitada:
                messages.error(request, f"Estoque insuficiente! Disponível: {estoque_total}. Solicitado: {qtd_solicitada}.")
            else:
                # 2. ALGORITMO FIFO (COM SELECT_FOR_UPDATE PARA CONCORRÊNCIA)
                lotes_disponiveis = Lote.objects.select_for_update().filter(
                    produto=produto, 
                    status='ATIVO', 
                    quantidade_atual__gt=0,
                    produto__empresa=empresa 
                ).order_by('data_entrada')

                qtd_restante_para_emprestar = qtd_solicitada

                for lote in lotes_disponiveis:
                    if qtd_restante_para_emprestar <= 0:
                        break

                    quantidade_a_retirar = min(lote.quantidade_atual, qtd_restante_para_emprestar)
                    
                    lote.quantidade_atual -= quantidade_a_retirar
                    lote.save()

                    Emprestimo.objects.create(
                        produto=produto,
                        lote=lote,
                        quantidade=quantidade_a_retirar,
                        solicitante=dados_emprestimo.solicitante,
                        observacao=dados_emprestimo.observacao,
                        responsavel_saida=request.user,
                        data_saida=timezone.now() 
                    )

                    qtd_restante_para_emprestar -= quantidade_a_retirar

                messages.success(request, f"Empréstimo de {qtd_solicitada} itens registrado com sucesso!")
                return redirect('lista_emprestimos')
    else:
        form = EmprestimoForm(request.user)

    produtos = Produto.objects.filter(empresa=empresa).select_related('categoria', 'localizacao').annotate(
        saldo_ativo=Coalesce(Sum('lotes__quantidade_atual', filter=Q(lotes__status='ATIVO')), 0)
    ).order_by('nome')
    produtos_data = list(Produto.objects.filter(empresa=empresa).values('id', 'nome', 'categoria_id'))
    import json
    produtos_json = json.dumps(produtos_data, default=str)

    return render(request, 'estoque/registrar_emprestimo.html', {
        'form': form, 
        'produtos': produtos,
        'produtos_json': produtos_json
    })

@login_required
def lista_emprestimos(request):
    empresa = get_empresa_usuario(request.user)
    emprestimos = Emprestimo.objects.filter(
        produto__empresa=empresa
    ).select_related('produto', 'lote', 'responsavel_saida').order_by('-data_saida')
    return render(request, 'estoque/lista_emprestimos.html', {'emprestimos': emprestimos})

@login_required
@transaction.atomic
def devolver_item(request, pk):
    # [SEGURANÇA M4] Filtra pelo empresa do usuário para prevenir IDOR —
    # impede que um usuário de outra empresa devolva empréstimos que não são seus.
    empresa = get_empresa_usuario(request.user)
    emprestimo = get_object_or_404(Emprestimo, pk=pk, produto__empresa=empresa)
    
    if request.method == 'POST':
        if not emprestimo.devolvido:
            if emprestimo.lote:
                lote = emprestimo.lote
                lote.quantidade_atual += emprestimo.quantidade
                if lote.status == 'ESGOTADO' and lote.quantidade_atual > 0:
                    lote.status = 'ATIVO'
                
                lote.save()
            
            emprestimo.devolvido = True
            emprestimo.data_devolucao = timezone.now()
            emprestimo.responsavel_devolucao = request.user
            emprestimo.save()
            
            messages.success(request, f"Devolução de {emprestimo.quantidade} itens confirmada com sucesso!")
        else:
            messages.warning(request, "Este item já foi devolvido.")
            
    return redirect('lista_emprestimos')

# --- EQUIPE ---
@login_required
def lista_funcionarios(request):
    empresa = get_empresa_usuario(request.user)
    if not request.user.userprofile.e_dono:
        messages.error(request, "Acesso restrito.")
        return redirect('dashboard')
        
    funcionarios = UserProfile.objects.filter(empresa=empresa)
    return render(request, 'estoque/lista_funcionarios.html', {'funcionarios': funcionarios})

@login_required
def criar_funcionario(request):
    empresa = get_empresa_usuario(request.user)
    if not request.user.userprofile.e_dono:
        return redirect('dashboard')


    prefixo_empresa = slugify(empresa.nome).replace('-', '')

    if request.method == 'POST':
        form = FuncionarioForm(request.POST)
        if form.is_valid():
          
            user = form.save(commit=False)
            
            sufixo = form.cleaned_data['username'].lower()
            
            
            login_final = f"{prefixo_empresa}.{sufixo}"
            
            
            if User.objects.filter(username=login_final).exists():
                form.add_error('username', f"O usuário '{login_final}' já existe nesta empresa.")
            else:
                user.username = login_final
                user.set_password(form.cleaned_data['password'])
                user.save()
                UserProfile.objects.create(user=user, empresa=empresa, e_dono=False)
                
                messages.success(request, f"Funcionário criado! Login de acesso: {login_final}")
                return redirect('lista_funcionarios')
    else:
        form = FuncionarioForm()

    return render(request, 'estoque/criar_funcionario.html', {
        'form': form,
        'prefixo': prefixo_empresa 
    })


@login_required
@transaction.atomic
def editar_funcionario(request, pk):
    empresa = get_empresa_usuario(request.user)
    if not (hasattr(request.user, 'userprofile') and request.user.userprofile.e_dono):
        messages.error(request, "Acesso restrito a administradores.")
        return redirect('dashboard')

    funcionario_profile = get_object_or_404(UserProfile, user_id=pk, empresa=empresa)
    funcionario_user = funcionario_profile.user

    if request.method == 'POST':
        form = EditarFuncionarioForm(request.POST, user_instance=funcionario_user)
        if form.is_valid():
            novo_e_dono = form.cleaned_data['e_dono']
            novo_is_active = form.cleaned_data['is_active']

            # Trava de segurança anti-lockout: se for o próprio usuário e ele for o único dono ativo
            if funcionario_user == request.user:
                outros_donos_ativos = UserProfile.objects.filter(
                    empresa=empresa,
                    e_dono=True,
                    user__is_active=True
                ).exclude(user=request.user).exists()

                if not outros_donos_ativos:
                    if not novo_e_dono:
                        form.add_error('e_dono', 'Você é o único administrador ativo e não pode revogar seu próprio acesso de administrador.')
                    if not novo_is_active:
                        form.add_error('is_active', 'Você é o único administrador ativo e não pode desativar a sua própria conta.')

            if not form.errors:
                funcionario_user.first_name = form.cleaned_data['first_name']
                funcionario_user.last_name = form.cleaned_data['last_name']
                funcionario_user.email = form.cleaned_data['email']
                funcionario_user.is_active = novo_is_active

                nova_senha = form.cleaned_data.get('nova_senha')
                if nova_senha:
                    funcionario_user.set_password(nova_senha)

                funcionario_user.save()

                funcionario_profile.e_dono = novo_e_dono
                funcionario_profile.save()

                messages.success(request, f"Cadastro do usuário '{funcionario_user.get_full_name() or funcionario_user.username}' atualizado com sucesso! O histórico de ações permanece 100% preservado.")
                return redirect('lista_funcionarios')
    else:
        initial_data = {
            'first_name': funcionario_user.first_name,
            'last_name': funcionario_user.last_name,
            'email': funcionario_user.email,
            'e_dono': funcionario_profile.e_dono,
            'is_active': funcionario_user.is_active,
        }
        form = EditarFuncionarioForm(initial=initial_data, user_instance=funcionario_user)

    return render(request, 'estoque/editar_funcionario.html', {
        'form': form,
        'funcionario_user': funcionario_user,
        'funcionario_profile': funcionario_profile,
    })


@login_required
def historico_produto(request, pk):
    empresa = get_empresa_usuario(request.user)
    produto = get_object_or_404(Produto, pk=pk, empresa=empresa)
    
    # 1. Entradas (Lotes)
    lotes = Lote.objects.filter(produto=produto).order_by('data_entrada')
    
    # 2. Saídas (Baixas e Vendas)
    saidas = SaidaEstoque.objects.filter(produto=produto).select_related('lote', 'usuario').order_by('-data')
    
    # 3. Auditoria de Alterações da Tabela de Preços
    historico_precos = produto.historico_precos.select_related('usuario').order_by('-data_alteracao')
    
    # 4. Métricas Financeiras e Operacionais
    total_entradas_qtd = sum(l.quantidade_inicial for l in lotes)
    total_saidas_qtd = sum(s.quantidade for s in saidas)
    total_investido = sum(float(l.quantidade_inicial) * float(l.preco_compra) for l in lotes)
    
    saidas_com_valor = [s for s in saidas if s.valor_venda is not None]
    total_faturado = sum(float(s.quantidade) * float(s.valor_venda) for s in saidas_com_valor)
    
    custo_medio = float(produto.preco_medio)
    if custo_medio == 0 and total_entradas_qtd > 0:
        custo_medio = round(total_investido / total_entradas_qtd, 2)
        
    margem_atual = None
    markup_atual = None
    lucro_unitario = None
    preco_venda_float = float(produto.preco_venda) if produto.preco_venda else 0.0
    if produto.disponivel_venda and preco_venda_float > 0 and custo_medio > 0:
        lucro_unit = preco_venda_float - custo_medio
        lucro_unitario = round(lucro_unit, 2)
        margem_atual = round((lucro_unit / preco_venda_float) * 100, 1)
        markup_atual = round((lucro_unit / custo_medio) * 100, 1)

    # 5. Construção da Timeline Unificada para os Gráficos
    timeline_dict = {}
    
    for lote in lotes:
        d_str = lote.data_entrada.strftime("%Y-%m-%d")
        if d_str not in timeline_dict:
            timeline_dict[d_str] = {
                'display': lote.data_entrada.strftime("%d/%m/%Y"),
                'custo_sum': float(lote.preco_compra) * float(lote.quantidade_inicial),
                'custo_qtd': float(lote.quantidade_inicial),
                'custo': float(lote.preco_compra),
                'venda_sum': 0.0,
                'venda_qtd': 0.0,
                'venda': None,
                'tabela': None,
                'qtd_entrada': lote.quantidade_inicial,
                'qtd_saida': 0
            }
        else:
            timeline_dict[d_str]['custo_sum'] += float(lote.preco_compra) * float(lote.quantidade_inicial)
            timeline_dict[d_str]['custo_qtd'] += float(lote.quantidade_inicial)
            timeline_dict[d_str]['qtd_entrada'] += lote.quantidade_inicial
            if timeline_dict[d_str]['custo_qtd'] > 0:
                timeline_dict[d_str]['custo'] = round(timeline_dict[d_str]['custo_sum'] / timeline_dict[d_str]['custo_qtd'], 2)
            else:
                timeline_dict[d_str]['custo'] = float(lote.preco_compra)
            
    for s in saidas.order_by('data'):
        d_str = s.data.strftime("%Y-%m-%d")
        val_venda = float(s.valor_venda) if s.valor_venda is not None else None
        if d_str not in timeline_dict:
            timeline_dict[d_str] = {
                'display': s.data.strftime("%d/%m/%Y"),
                'custo_sum': 0.0,
                'custo_qtd': 0.0,
                'custo': None,
                'venda_sum': (val_venda * float(s.quantidade)) if val_venda is not None else 0.0,
                'venda_qtd': float(s.quantidade) if val_venda is not None else 0.0,
                'venda': val_venda,
                'tabela': None,
                'qtd_entrada': 0,
                'qtd_saida': s.quantidade
            }
        else:
            timeline_dict[d_str]['qtd_saida'] += s.quantidade
            if val_venda is not None:
                timeline_dict[d_str]['venda_sum'] += val_venda * float(s.quantidade)
                timeline_dict[d_str]['venda_qtd'] += float(s.quantidade)
                if timeline_dict[d_str]['venda_qtd'] > 0:
                    timeline_dict[d_str]['venda'] = round(timeline_dict[d_str]['venda_sum'] / timeline_dict[d_str]['venda_qtd'], 2)
            
    for hp in produto.historico_precos.order_by('data_alteracao'):
        d_str = hp.data_alteracao.strftime("%Y-%m-%d")
        if d_str not in timeline_dict:
            timeline_dict[d_str] = {
                'display': hp.data_alteracao.strftime("%d/%m/%Y"),
                'custo_sum': 0.0,
                'custo_qtd': 0.0,
                'custo': None,
                'venda_sum': 0.0,
                'venda_qtd': 0.0,
                'venda': None,
                'tabela': float(hp.preco_novo),
                'qtd_entrada': 0,
                'qtd_saida': 0
            }
        else:
            timeline_dict[d_str]['tabela'] = float(hp.preco_novo)
            
    sorted_dates = sorted(timeline_dict.keys())
    chart_labels = [timeline_dict[k]['display'] for k in sorted_dates]
    chart_custo = [timeline_dict[k]['custo'] for k in sorted_dates]
    chart_venda = [timeline_dict[k]['venda'] for k in sorted_dates]
    chart_tabela = [timeline_dict[k]['tabela'] for k in sorted_dates]
    chart_qtd_entrada = [timeline_dict[k]['qtd_entrada'] for k in sorted_dates]
    chart_qtd_saida = [timeline_dict[k]['qtd_saida'] for k in sorted_dates]
    
    # Retrocompatibilidade
    dados_compra = [
        {'x': lote.data_entrada.strftime("%Y-%m-%d"), 'x_display': lote.data_entrada.strftime("%d/%m/%Y"), 'y': float(lote.preco_compra)}
        for lote in lotes
    ]
    dados_venda = [
        {'x': s.data.strftime("%Y-%m-%d"), 'x_display': s.data.strftime("%d/%m/%Y"), 'y': float(s.valor_venda)}
        for s in saidas_com_valor
    ]

    context = {
        'produto': produto,
        'lotes': lotes.order_by('-data_entrada'),
        'saidas': saidas,
        'historico_precos': historico_precos,
        'total_entradas_qtd': total_entradas_qtd,
        'total_saidas_qtd': total_saidas_qtd,
        'total_investido': total_investido,
        'total_faturado': total_faturado,
        'custo_medio': custo_medio,
        'margem_atual': margem_atual,
        'markup_atual': markup_atual,
        'lucro_unitario': lucro_unitario,
        'chart_labels_json': json.dumps(chart_labels),
        'chart_custo_json': json.dumps(chart_custo),
        'chart_venda_json': json.dumps(chart_venda),
        'chart_tabela_json': json.dumps(chart_tabela),
        'chart_qtd_entrada_json': json.dumps(chart_qtd_entrada),
        'chart_qtd_saida_json': json.dumps(chart_qtd_saida),
        'dados_compra_json': json.dumps(dados_compra, cls=DjangoJSONEncoder),
        'dados_venda_json': json.dumps(dados_venda, cls=DjangoJSONEncoder),
    }
    
    return render(request, 'estoque/historico_produto.html', context)

@login_required
def api_detalhes_produto(request, pk):
    """Retorna JSON com configurações do produto para o Frontend"""
    try:
        empresa = get_empresa_usuario(request.user)
        produto = Produto.objects.get(pk=pk, empresa=empresa)
        return JsonResponse({
            'controla_lote': produto.controla_lote,
            'unidade': produto.unidade,
            'disponivel_venda': produto.disponivel_venda,
            'preco_venda': f"{produto.preco_venda:.2f}",
            'preco_medio': f"{produto.preco_medio:.2f}",
        })
    except Produto.DoesNotExist:
        return JsonResponse({'error': 'Produto não encontrado'}, status=404)
    

@login_required
def api_lotes_produto(request, pk):
    """Retorna os lotes ativos de um produto para o dropdown"""
    empresa = get_empresa_usuario(request.user)
    lotes = Lote.objects.filter(
        produto_id=pk, 
        produto__empresa=empresa, 
        status='ATIVO', 
        quantidade_atual__gt=0
    ).order_by('data_validade', 'data_entrada') 
    
    data = []
    for l in lotes:
        texto = f"Lote: {l.numero_lote} | Qtd: {l.quantidade_atual}"
        if l.data_validade:
            texto += f" | Val: {l.data_validade.strftime('%d/%m/%Y')}"
        
        data.append({
            'id': l.id,
            'texto': texto,
            'qtd_disponivel': l.quantidade_atual
        })
    
    return JsonResponse(data, safe=False)

@login_required
def criar_categoria_api(request):
    if request.method == 'POST':
        empresa = get_empresa_usuario(request.user)
        nome = request.POST.get('nome')
        
        if nome:
            nova_cat = Categoria.objects.create(empresa=empresa, nome=nome)
            return JsonResponse({
                'id': nova_cat.id, 
                'nome': nova_cat.nome,
                'status': 'success'
            })
            
    return JsonResponse({'status': 'error'}, status=400)

@login_required
def criar_localizacao_api(request):
    try:
        if request.method == 'POST':
            empresa = get_empresa_usuario(request.user)
            if not empresa:
                return JsonResponse({'status': 'error', 'message': 'Empresa não encontrada.'}, status=400)

            nome = request.POST.get('nome')
            
            if nome:
                nova_loc = Localizacao.objects.create(empresa=empresa, nome=nome)
                return JsonResponse({
                    'id': nova_loc.id, 
                    'nome': nova_loc.nome,
                    'status': 'success'
                })
            else:
                return JsonResponse({'status': 'error', 'message': 'Nome obrigatório.'}, status=400)
                
        return JsonResponse({'status': 'error', 'message': 'Método inválido.'}, status=400)

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
@login_required
@transaction.atomic
def editar_lote(request, pk):
    if not request.user.userprofile.e_dono:
        messages.error(request, "Apenas administradores podem editar lançamentos passados.")
        return redirect('lista_lotes')
    empresa = get_empresa_usuario(request.user)
    lote = get_object_or_404(Lote, pk=pk, produto__empresa=empresa)

    qtd_inicial_antiga = lote.quantidade_inicial

    if request.method == 'POST':
        form = LoteForm(request.user, request.POST, request.FILES, instance=lote)
        
        if form.is_valid():
            lote_editado = form.save(commit=False)
            
            
            diferenca = lote_editado.quantidade_inicial - qtd_inicial_antiga
            
            
            nova_qtd_atual = lote_editado.quantidade_atual + diferenca
            
        
            if nova_qtd_atual < 0:
                messages.error(request, f"Não é possível reduzir tanto a quantidade. Já foram vendidos itens deste lote. O mínimo aceitável seria {qtd_inicial_antiga - lote_editado.quantidade_atual}.")
            else:
                lote_editado.quantidade_atual = nova_qtd_atual
                lote_editado.save()
                messages.success(request, "Lote atualizado com sucesso! O estoque foi recalculado.")
                return redirect('lista_lotes')
                
    else:
        form = LoteForm(request.user, instance=lote)

    return render(request, 'estoque/editar_lote.html', {'form': form, 'lote': lote})

@login_required
def relatorios_gerais(request):
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        return redirect('cadastro_saas')
    return render(request, 'estoque/relatorios_index.html', {'empresa': empresa})

@login_required
def relatorio_estoque_saldo(request):
    empresa = get_empresa_usuario(request.user)
    lotes = Lote.objects.filter(
        quantidade_atual__gt=0, 
        produto__empresa=empresa
    ).select_related('produto').order_by('produto__nome')

    
    total_itens = lotes.aggregate(soma=Sum('quantidade_atual'))['soma'] or 0
    
    valor_total_estoque = lotes.annotate(
        valor_lote=F('quantidade_atual') * F('preco_compra')
    ).aggregate(soma=Sum('valor_lote'))['soma'] or 0

    return render(request, 'estoque/relatorio_saldo.html', {
        'lotes': lotes,
        'total_itens': total_itens,
        'valor_total_estoque': valor_total_estoque,
        'data_atual': timezone.now(),
        'empresa': empresa 
    })

@login_required
def excluir_entrada(request, pk):
    try:
        # 1. Trava de Segurança
        if not hasattr(request.user, 'userprofile') or not request.user.userprofile.e_dono:
            messages.error(request, "Acesso negado. Apenas o administrador pode excluir registros.")
            return redirect('dashboard')

        empresa = get_empresa_usuario(request.user)
        
        # 2. A CORREÇÃO ESTÁ AQUI: produto__empresa em vez de empresa
        lote = get_object_or_404(Lote, pk=pk, produto__empresa=empresa)
        
        if request.method == 'POST':
            nome_produto = lote.produto.nome
            lote.delete()
            
            messages.success(request, f"A entrada do produto '{nome_produto}' foi excluída permanentemente.")
            url_anterior = request.META.get('HTTP_REFERER', 'dashboard')
            return redirect(url_anterior)

    except ProtectedError:
        url_anterior = request.META.get('HTTP_REFERER', 'dashboard')
        messages.error(request, "Bloqueado: Você não pode excluir este lote porque existem saídas ou empréstimos vinculados a ele.")
        return redirect(url_anterior)
        
    except Exception as e:
        url_anterior = request.META.get('HTTP_REFERER', 'dashboard')
        messages.error(request, f"Erro técnico ao excluir: {str(e)}")
        return redirect(url_anterior)
        
    return redirect('dashboard')

@login_required
@transaction.atomic
def excluir_saida(request, pk):
    try:
        if not (request.user.is_superuser or (hasattr(request.user, 'userprofile') and request.user.userprofile.e_dono)):
            messages.error(request, "Acesso negado. Apenas o administrador ou o dono podem excluir registros.")
            return redirect('dashboard')

        empresa = get_empresa_usuario(request.user)
        saida = get_object_or_404(SaidaEstoque, pk=pk, produto__empresa=empresa)

        # --- BLOQUEIO DE SEGURANÇA: VENDAS COMERCIAIS ---
        item_venda = saida.itens_venda.first() if hasattr(saida, 'itens_venda') else None
        codigo_venda = None
        if item_venda and item_venda.venda:
            codigo_venda = item_venda.venda.codigo_venda
        elif saida.codigo_grupo and saida.codigo_grupo.startswith('VD-'):
            codigo_venda = saida.codigo_grupo

        if codigo_venda:
            messages.error(
                request,
                f"Bloqueio de Segurança: Esta baixa de estoque pertence à Venda comercial '{codigo_venda}'. "
                f"Para devolver os produtos ao estoque sem duplicar dados, cancele a venda diretamente pelo menu de Vendas."
            )
            url_anterior = request.META.get('HTTP_REFERER', 'lista_saidas')
            return redirect(url_anterior)
        
        if request.method == 'POST':
            nome_produto = saida.produto.nome
            qtd_devolver = saida.quantidade
            
            # --- DEVOLUÇÃO EXATA PARA O LOTE DE ORIGEM ---
            if saida.lote:
                saida.lote.quantidade_atual += qtd_devolver
                saida.lote.save()
                mensagem_lote = f"ao Lote {saida.lote.numero_lote}"
            else:
                # Fallback de segurança: Caso seja uma saída antiga (antes dessa atualização),
                # devolve para o lote mais recente para não perder o produto.
                lote_recente = Lote.objects.filter(produto=saida.produto).order_by('-data_entrada').first()
                if lote_recente:
                    lote_recente.quantidade_atual += qtd_devolver
                    lote_recente.save()
                    mensagem_lote = f"ao Lote {lote_recente.numero_lote} (Saída antiga sem vínculo)"
                else:
                    mensagem_lote = "(O produto ficou sem lote associado)"
            
            saida.delete()
            messages.success(request, f"A saída foi cancelada! {qtd_devolver}x '{nome_produto}' retornaram {mensagem_lote}.")
            
            url_anterior = request.META.get('HTTP_REFERER', 'dashboard')
            return redirect(url_anterior)

    except Exception as e:
        messages.error(request, f"Erro técnico ao excluir saída: {str(e)}")
        return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required
def relatorio_movimentacoes(request):
    empresa = get_empresa_usuario(request.user)
    
    # 1. Captura os parâmetros do filtro
    data_inicio = request.GET.get('data_inicio', '')
    data_fim = request.GET.get('data_fim', '')
    tipo_filtro = request.GET.get('tipo', '')  # NOVO: Filtro de Tipo
    
    movimentacoes = []

    # 2. Busca ENTRADAS (Se o filtro for vazio ou 'ENTRADA')
    if tipo_filtro in ['', 'ENTRADA']:
        lotes = Lote.objects.filter(produto__empresa=empresa)
        if data_inicio: lotes = lotes.filter(data_entrada__date__gte=data_inicio)
        if data_fim: lotes = lotes.filter(data_entrada__date__lte=data_fim)
        
        for lote in lotes:
            movimentacoes.append({
                'data_evento': lote.data_entrada,
                'tipo_movimento': 'ENTRADA',
                'produto': lote.produto,
                'responsavel': lote.fornecedor or 'Sistema',
                'quantidade_inicial': lote.quantidade_inicial,
                'numero_lote': lote.numero_lote,
            })

    # 3. Busca SAÍDAS (Se o filtro for vazio ou 'SAIDA')
    if tipo_filtro in ['', 'SAIDA']:
        saidas = SaidaEstoque.objects.filter(produto__empresa=empresa)
        if data_inicio: saidas = saidas.filter(data__date__gte=data_inicio)
        if data_fim: saidas = saidas.filter(data__date__lte=data_fim)
        
        for saida in saidas:
            movimentacoes.append({
                'data_evento': saida.data,
                'tipo_movimento': 'SAIDA',
                'produto': saida.produto,
                'responsavel': saida.usuario.get_full_name() if saida.usuario else 'Sistema',
                'quantidade': saida.quantidade,
                'motivo': saida.motivo,
                'valor_venda': saida.valor_venda,
            })

    # 4. Busca EMPRÉSTIMOS (Se o filtro for vazio ou 'EMPRESTIMO')
    if tipo_filtro in ['', 'EMPRESTIMO']:
        emprestimos = Emprestimo.objects.filter(produto__empresa=empresa)
        if data_inicio: emprestimos = emprestimos.filter(data_saida__date__gte=data_inicio)
        if data_fim: emprestimos = emprestimos.filter(data_saida__date__lte=data_fim)
        
        for emp in emprestimos:
            movimentacoes.append({
                'data_evento': emp.data_saida,
                'tipo_movimento': 'EMPRESTIMO',
                'produto': emp.produto,
                'responsavel': emp.responsavel_saida.get_full_name() if emp.responsavel_saida else 'Sistema',
                'quantidade': emp.quantidade,
                'solicitante': emp.solicitante,
            })

    # 5. Ordena TUDO misturado pela data (Mais recente no topo)
    movimentacoes.sort(key=lambda x: x['data_evento'], reverse=True)

    return render(request, 'estoque/relatorio_movimentacoes.html', {
        'movimentacoes': movimentacoes,
        'data_inicio': data_inicio,
        'data_fim': data_fim,
        'tipo_filtro': tipo_filtro, # Enviando o filtro atual para o HTML lembrar da escolha
        'empresa': empresa
    })

# -> MÓDULO DE BACKUPS
import io
import os
import tempfile
from django.db import connection
from django.core.management import call_command
from django.http import HttpResponse, FileResponse, Http404

TABELAS_EXCLUIDAS_BACKUP = [
    'contenttypes', 
    'auth.Permission', 
    'sessions.Session', 
    'axes.AccessAttempt', 
    'axes.AccessLog'
]

def _is_serverless():
    """Detecta se o sistema está rodando em um ambiente serverless (ex: Vercel)."""
    return bool(os.environ.get('VERCEL'))

@login_required
def painel_backups(request):
    
    if not request.user.is_superuser:
        messages.error(request, "Acesso restrito ao administrador do sistema.")
        return redirect('dashboard')

    # No ambiente serverless o disco é somente-leitura — não há lista de arquivos.
    if _is_serverless():
        return render(request, 'estoque/painel_backups.html', {
            'arquivos': [],
            'modo_serverless': True,
        })

    pasta_backups = os.path.join(settings.BASE_DIR, 'backups')
    try:
        os.makedirs(pasta_backups, exist_ok=True)
    except OSError:
        pass

    # Lista todos os arquivos .json na pasta
    arquivos = []
    if os.path.exists(pasta_backups):
        for filename in os.listdir(pasta_backups):
            if filename.endswith('.json'):
                filepath = os.path.join(pasta_backups, filename)
                tamanho_mb = os.path.getsize(filepath) / (1024 * 1024)
                data_modificacao = datetime.fromtimestamp(os.path.getmtime(filepath))
                arquivos.append({
                    'nome': filename,
                    'tamanho': f"{tamanho_mb:.2f} MB",
                    'data': data_modificacao
                })
    
    # Ordena do mais recente para o mais antigo
    arquivos.sort(key=lambda x: x['data'], reverse=True)

    return render(request, 'estoque/painel_backups.html', {'arquivos': arquivos, 'modo_serverless': False})

@login_required
def criar_backup(request):
    if not request.user.is_superuser:
        messages.error(request, "Acesso restrito ao administrador do sistema.")
        return redirect('dashboard')

    # [SEGURANÇA] Apenas aceita POST para evitar disparo acidental via link GET
    if request.method != 'POST':
        return redirect('painel_backups')

    data_atual = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    nome_arquivo = f"backup_jgtech_{data_atual}.json"

    # ------------------------------------------------------------------
    # MODO SERVERLESS (ex: Vercel): gera o backup em memória e entrega
    # diretamente como download, sem tentar gravar nada no disco.
    # ------------------------------------------------------------------
    if _is_serverless():
        try:
            buffer = io.StringIO()
            call_command('dumpdata', exclude=TABELAS_EXCLUIDAS_BACKUP, format='json', indent=4, stdout=buffer)
            conteudo = buffer.getvalue()
            response = HttpResponse(conteudo, content_type='application/json')
            response['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
            return response
        except Exception as e:
            messages.error(request, f"Erro ao gerar backup: {str(e)}")
            return redirect('painel_backups')

    # ------------------------------------------------------------------
    # MODO LOCAL (ex: servidor Portainer/Docker): salva no disco como antes.
    # ------------------------------------------------------------------
    pasta_backups = os.path.join(settings.BASE_DIR, 'backups')
    caminho_arquivo = os.path.join(pasta_backups, nome_arquivo)

    try:
        os.makedirs(pasta_backups, exist_ok=True)
        # Extrai os dados do banco excluindo tabelas transitórias que causam conflito
        with open(caminho_arquivo, 'w', encoding='utf-8') as f:
            call_command('dumpdata', exclude=TABELAS_EXCLUIDAS_BACKUP, format='json', indent=4, stdout=f)
        
        messages.success(request, f"Backup '{nome_arquivo}' criado com sucesso!")
    except OSError as e:
        messages.error(request, f"Erro ao gravar arquivo no disco: {str(e)}")
    except Exception as e:
        messages.error(request, f"Erro ao criar backup: {str(e)}")

    return redirect('painel_backups')

@login_required
def baixar_backup(request, filename):
    if not request.user.is_superuser:
        messages.error(request, "Acesso restrito ao administrador do sistema.")
        return redirect('dashboard')

    # [SEGURANÇA C1] Sanitização de Path Traversal: resolve o caminho real e
    # garante que o arquivo está estritamente dentro da pasta de backups.
    pasta_backups = os.path.realpath(os.path.join(settings.BASE_DIR, 'backups'))
    filepath = os.path.realpath(os.path.join(pasta_backups, filename))

    if not filepath.startswith(pasta_backups + os.sep):
        raise Http404("Arquivo inválido ou acesso negado.")

    if os.path.exists(filepath):
        response = FileResponse(open(filepath, 'rb'), as_attachment=True, filename=os.path.basename(filepath))
        return response
    else:
        raise Http404("Arquivo de backup não encontrado.")

@login_required
def excluir_backup(request, filename):
    if request.method == 'POST' and request.user.is_superuser:
        # [SEGURANÇA C1] Sanitização de Path Traversal
        pasta_backups = os.path.realpath(os.path.join(settings.BASE_DIR, 'backups'))
        filepath = os.path.realpath(os.path.join(pasta_backups, filename))

        if not filepath.startswith(pasta_backups + os.sep):
            raise Http404("Arquivo inválido ou acesso negado.")

        if os.path.exists(filepath):
            os.remove(filepath)
            messages.success(request, f"Backup '{os.path.basename(filepath)}' excluído permanentemente.")
    return redirect('painel_backups')

@login_required
def restaurar_backup(request, filename):
    if request.method == 'POST' and request.user.is_superuser:
        # [SEGURANÇA C1] Sanitização de Path Traversal
        pasta_backups = os.path.realpath(os.path.join(settings.BASE_DIR, 'backups'))
        filepath = os.path.realpath(os.path.join(pasta_backups, filename))

        if not filepath.startswith(pasta_backups + os.sep):
            raise Http404("Arquivo inválido ou acesso negado.")

        if os.path.exists(filepath):
            try:
                # Injeta os dados do arquivo de volta no banco
                call_command('loaddata', filepath)
                if connection.vendor == 'postgresql':
                    try:
                        from django.core.management.color import no_style
                        from django.apps import apps
                        app_config = apps.get_app_config('estoque')
                        sequence_sql = connection.ops.sequence_reset_sql(no_style(), app_config.get_models())
                        with connection.cursor() as cursor:
                            for sql in sequence_sql:
                                cursor.execute(sql)
                    except Exception as seq_err:
                        logger.warning(f"Aviso ao sincronizar sequências do PostgreSQL após restore: {seq_err}")
                messages.success(request, f"O sistema foi restaurado com sucesso usando o arquivo '{os.path.basename(filepath)}'.")
            except Exception as e:
                messages.error(request, f"Erro crítico ao restaurar banco de dados: {str(e)}")
        
    return redirect('painel_backups')

@login_required
def restaurar_backup_upload(request):
    """
    Restaura o banco de dados a partir de um arquivo .json enviado diretamente
    do computador do superadministrador. Funciona tanto em Docker/Local quanto
    no ambiente Serverless da Vercel (utilizando /tmp como armazenamento efêmero).
    """
    if not request.user.is_superuser:
        messages.error(request, "Acesso restrito ao administrador do sistema.")
        return redirect('dashboard')

    if request.method != 'POST':
        return redirect('painel_backups')

    arquivo = request.FILES.get('arquivo_backup')
    if not arquivo:
        messages.error(request, "Nenhum arquivo de backup foi selecionado.")
        return redirect('painel_backups')

    nome_original = arquivo.name or ''
    if not nome_original.lower().endswith('.json'):
        messages.error(request, "Formato inválido. Por favor, envie um arquivo de backup com extensão .json.")
        return redirect('painel_backups')

    limite_mb = 50
    if arquivo.size > limite_mb * 1024 * 1024:
        messages.error(request, f"Arquivo muito grande. O limite máximo permitido para restauração é de {limite_mb} MB.")
        return redirect('painel_backups')

    temp_dir = '/tmp' if _is_serverless() else None
    temp_path = None

    try:
        conteudo_bytes = arquivo.read()
        try:
            dados = json.loads(conteudo_bytes.decode('utf-8'))
            if not isinstance(dados, list):
                messages.error(request, "O arquivo enviado não possui o formato de dados válido do sistema (lista de registros).")
                return redirect('painel_backups')
        except (json.JSONDecodeError, UnicodeDecodeError) as json_err:
            messages.error(request, f"O arquivo de backup está corrompido ou em formato inválido: {str(json_err)}")
            return redirect('painel_backups')

        with tempfile.NamedTemporaryFile(suffix='.json', delete=False, dir=temp_dir, mode='wb') as tmp:
            tmp.write(conteudo_bytes)
            temp_path = tmp.name

        # Injeta os dados do arquivo temporário no banco de dados
        call_command('loaddata', temp_path)

        # Sincronização de sequências (PostgreSQL) para evitar colisão de IDs após o restore
        if connection.vendor == 'postgresql':
            try:
                from django.core.management.color import no_style
                from django.apps import apps
                app_config = apps.get_app_config('estoque')
                sequence_sql = connection.ops.sequence_reset_sql(no_style(), app_config.get_models())
                with connection.cursor() as cursor:
                    for sql in sequence_sql:
                        cursor.execute(sql)
            except Exception as seq_err:
                logger.warning(f"Aviso ao sincronizar sequências do PostgreSQL após restore: {seq_err}")

        total_objetos = len(dados) if isinstance(dados, list) else 0
        messages.success(
            request, 
            f"Backup '{nome_original}' restaurado com sucesso! ({total_objetos} registros carregados no banco de dados)."
        )
    except Exception as e:
        logger.error(f"Erro crítico ao restaurar backup via upload: {str(e)}", exc_info=True)
        messages.error(request, f"Erro crítico ao restaurar banco de dados: {str(e)}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

    return redirect('painel_backups')


# =============================================================================
# TABELA DE PREÇOS DE VENDA & HISTÓRICO
# =============================================================================

@login_required
def tabela_precos(request):
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        return redirect('dashboard')

    query = request.GET.get('q', '').strip()
    categoria_id = request.GET.get('categoria', '')

    # APENAS itens que estão com a opção de venda marcada
    produtos = Produto.objects.filter(
        empresa=empresa, 
        ativo=True, 
        disponivel_venda=True
    ).select_related('categoria', 'localizacao').prefetch_related('lotes')

    if query:
        produtos = produtos.filter(
            Q(nome__icontains=query) | Q(sku__icontains=query) | Q(ean__icontains=query)
        )
    if categoria_id:
        produtos = produtos.filter(categoria_id=categoria_id)

    categorias = Categoria.objects.filter(empresa=empresa).order_by('nome')

    total_para_venda = Produto.objects.filter(empresa=empresa, ativo=True, disponivel_venda=True).count()
    total_geral = Produto.objects.filter(empresa=empresa, ativo=True).count()
    total_sem_venda = total_geral - total_para_venda

    # Produtos que ainda não estão marcados para venda (para o botão/modal "Adicionar à Tabela")
    produtos_insumo = Produto.objects.filter(empresa=empresa, ativo=True, disponivel_venda=False).order_by('nome')

    paginator = Paginator(produtos.order_by('nome'), 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'estoque/tabela_precos.html', {
        'page_obj': page_obj,
        'query': query,
        'categoria_selecionada': int(categoria_id) if categoria_id else None,
        'categorias': categorias,
        'total_para_venda': total_para_venda,
        'total_sem_venda': total_sem_venda,
        'total_geral': total_geral,
        'produtos_insumo': produtos_insumo,
    })


@login_required
def atualizar_preco_produto_api(request, pk):
    """API para atualização rápida de preço e status de venda a partir da tabela de preços"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Método não permitido.'}, status=405)

    empresa = get_empresa_usuario(request.user)
    produto = get_object_or_404(Produto, pk=pk, empresa=empresa)

    try:
        novo_preco_raw = request.POST.get('preco_venda', '').replace(',', '.').strip()
        novo_preco = Decimal(novo_preco_raw) if novo_preco_raw else Decimal('0.00')
        if novo_preco < 0:
            return JsonResponse({'status': 'error', 'message': 'O preço de venda não pode ser negativo.'}, status=400)

        disponivel_venda = request.POST.get('disponivel_venda') in ['true', '1', 'on', True]
        motivo = request.POST.get('motivo', '').strip() or 'Ajuste rápido na tabela de preços'

        preco_anterior = produto.preco_venda
        disponivel_anterior = produto.disponivel_venda

        produto.preco_venda = novo_preco
        produto.disponivel_venda = disponivel_venda
        produto.save(update_fields=['preco_venda', 'disponivel_venda'])

        if novo_preco != preco_anterior or disponivel_anterior != disponivel_venda:
            HistoricoPreco.objects.create(
                empresa=empresa,
                produto=produto,
                preco_anterior=preco_anterior or Decimal('0.00'),
                preco_novo=novo_preco,
                usuario=request.user,
                motivo=motivo
            )

        return JsonResponse({
            'status': 'success',
            'message': f'Preço do produto "{produto.nome}" atualizado com sucesso!',
            'preco_venda': f"{produto.preco_venda:.2f}",
            'disponivel_venda': produto.disponivel_venda,
            'margem_lucro': f"{produto.margem_lucro:.1f}",
            'markup': f"{produto.markup:.1f}",
            'lucro_unitario': f"{produto.lucro_unitario:.2f}"
        })
    except (ValueError, TypeError) as e:
        return JsonResponse({'status': 'error', 'message': 'Valor de preço inválido.'}, status=400)


@login_required
def api_historico_precos(request, pk):
    """Retorna os registros de alterações de preços de um determinado produto"""
    empresa = get_empresa_usuario(request.user)
    produto = get_object_or_404(Produto, pk=pk, empresa=empresa)
    historico = produto.historico_precos.select_related('usuario').order_by('-data_alteracao')[:50]

    dados = [
        {
            'id': h.id,
            'preco_anterior': f"{h.preco_anterior:.2f}",
            'preco_novo': f"{h.preco_novo:.2f}",
            'usuario': h.usuario.get_full_name() or h.usuario.username if h.usuario else "Sistema",
            'data': h.data_alteracao.strftime("%d/%m/%Y %H:%M"),
            'motivo': h.motivo or "Ajuste de preço"
        }
        for h in historico
    ]

    return JsonResponse({
        'status': 'success',
        'produto': {
            'id': produto.id,
            'nome': produto.nome,
            'preco_atual': f"{produto.preco_venda:.2f}",
            'custo_medio': f"{produto.preco_medio:.2f}",
            'disponivel_venda': produto.disponivel_venda
        },
        'historico': dados
    })


@login_required
def simulador_preco(request):
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        return redirect('dashboard')
    
    produtos = Produto.objects.filter(empresa=empresa).order_by('nome')
    aliquotas = AliquotaImposto.objects.filter(empresa=empresa).order_by('nome')
    form_aliquota = AliquotaImpostoForm()
    
    return render(request, 'estoque/simulador_preco.html', {
        'produtos': produtos,
        'aliquotas': aliquotas,
        'form_aliquota': form_aliquota
    })


@login_required
def criar_aliquota_api(request):
    if request.method == 'POST':
        empresa = get_empresa_usuario(request.user)
        if not empresa:
            return JsonResponse({'status': 'error', 'message': 'Empresa não encontrada.'}, status=400)
            
        form = AliquotaImpostoForm(request.POST)
        if form.is_valid():
            aliquota = form.save(commit=False)
            aliquota.empresa = empresa
            aliquota.save()
            return JsonResponse({
                'id': aliquota.id,
                'nome': aliquota.nome,
                'percentual': float(aliquota.percentual),
                'status': 'success'
            })
        else:
            errors = form.errors.as_json()
            return JsonResponse({'status': 'error', 'message': 'Dados inválidos.', 'errors': errors}, status=400)
            
    return JsonResponse({'status': 'error', 'message': 'Método inválido.'}, status=400)


@login_required
def api_produto_preco(request, pk):
    try:
        empresa = get_empresa_usuario(request.user)
        produto = Produto.objects.get(pk=pk, empresa=empresa)
        
        # Get last purchase price as helper parameter
        ultimo_lote = Lote.objects.filter(produto=produto, status='ATIVO').order_by('-data_entrada').first()
        preco_custo_lote = float(ultimo_lote.preco_compra) if ultimo_lote else 0.0
        qtd_ultimo_lote = ultimo_lote.quantidade_inicial if ultimo_lote else 0
        
        return JsonResponse({
            'id': produto.id,
            'nome': produto.nome,
            'preco_medio': float(produto.preco_medio),
            'preco_custo_lote': preco_custo_lote,
            'saldo_total': float(produto.saldo_total),
            'unidade': produto.get_unidade_display(),
            'qtd_ultimo_lote': qtd_ultimo_lote
        })
    except Produto.DoesNotExist:
        return JsonResponse({'error': 'Produto não encontrado'}, status=404)


@login_required
def lista_simulacoes(request):
    empresa = get_empresa_usuario(request.user)
    query = request.GET.get('q', '')
    
    simulacoes = SimulacaoPreco.objects.filter(empresa=empresa)
    if query:
        simulacoes = simulacoes.filter(produto__nome__icontains=query)
        
    simulacoes = simulacoes.select_related('produto').order_by('-data_criacao')
    
    # Paginação (15 itens por página)
    paginator = Paginator(simulacoes, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'estoque/lista_simulacoes.html', {
        'page_obj': page_obj,
        'query': query
    })


@login_required
def salvar_simulacao_api(request):
    if request.method == 'POST':
        empresa = get_empresa_usuario(request.user)
        if not empresa:
            return JsonResponse({'status': 'error', 'message': 'Empresa não encontrada.'}, status=400)

        try:
            data = json.loads(request.body)
            produto_id = data.get('produto_id')
            if not produto_id:
                return JsonResponse({'status': 'error', 'message': 'Selecione um produto.'}, status=400)

            produto = get_object_or_404(Produto, id=produto_id, empresa=empresa)

            # [SEGURANÇA B4] Conversão segura de valores numéricos.
            # Evita que strings malformadas causem exceções com detalhes técnicos expostos.
            def _parse_decimal(val, default=0):
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return default

            def _parse_optional_decimal(val):
                if val is None or val == '':
                    return None
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return None

            simulacao = SimulacaoPreco.objects.create(
                empresa=empresa,
                produto=produto,
                preco_custo=_parse_decimal(data.get('preco_custo')),
                quantidade_estoque=_parse_decimal(data.get('quantidade_estoque')),
                preco_custo_futuro=_parse_optional_decimal(data.get('preco_custo_futuro')),
                quantidade_futura=_parse_optional_decimal(data.get('quantidade_futura')),
                frete_valor=_parse_decimal(data.get('frete_valor')),
                tipo_frete=data.get('tipo_frete', 'valor'),
                outros_valor=_parse_decimal(data.get('outros_valor')),
                tipo_outros=data.get('tipo_outros', 'valor'),
                aliquota_nome=data.get('aliquota_nome', 'Sem Imposto'),
                aliquota_percentual=_parse_decimal(data.get('aliquota_percentual')),
                margem_desejada=_parse_decimal(data.get('margem_desejada')),
                metodo=data.get('metodo', 'inside'),
                preco_sugerido=_parse_decimal(data.get('preco_sugerido')),
                preco_praticado=_parse_decimal(data.get('preco_praticado')),
                lucro_liquido=_parse_decimal(data.get('lucro_liquido')),
                margem_realizada=_parse_decimal(data.get('margem_realizada')),
            )

            return JsonResponse({'status': 'success', 'message': 'Simulação salva com sucesso!', 'id': simulacao.id})
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Payload JSON inválido.'}, status=400)
        except Exception:
            return JsonResponse({'status': 'error', 'message': 'Erro interno ao salvar a simulação.'}, status=500)

    return JsonResponse({'status': 'error', 'message': 'Método inválido.'}, status=400)


@login_required
def excluir_simulacao(request, pk):
    empresa = get_empresa_usuario(request.user)
    simulacao = get_object_or_404(SimulacaoPreco, pk=pk, empresa=empresa)
    if request.method == 'POST':
        nome_produto = simulacao.produto.nome
        simulacao.delete()
        messages.success(request, f"Simulação do produto '{nome_produto}' excluída.")
    return redirect('lista_simulacoes')


@login_required
def excluir_aliquota_api(request, pk):
    if request.method == 'POST':
        empresa = get_empresa_usuario(request.user)
        if not empresa:
            return JsonResponse({'status': 'error', 'message': 'Empresa não encontrada.'}, status=400)
        
        aliquota = get_object_or_404(AliquotaImposto, pk=pk, empresa=empresa)
        nome_aliquota = aliquota.nome
        aliquota.delete()
        return JsonResponse({'status': 'success', 'message': f"Alíquota '{nome_aliquota}' excluída com sucesso!"})
        
    return JsonResponse({'status': 'error', 'message': 'Método inválido.'}, status=400)


@login_required
def simulador_pdf(request):
    empresa = get_empresa_usuario(request.user)
    
    # 1. Recuperar parâmetros
    produto_id = request.GET.get('produto_id')
    preco_custo = float(request.GET.get('preco_custo', 0) or 0)
    quantidade_estoque = float(request.GET.get('quantidade_estoque', 0) or 0)
    
    preco_custo_futuro = request.GET.get('preco_custo_futuro')
    preco_custo_futuro = float(preco_custo_futuro) if (preco_custo_futuro and preco_custo_futuro != '') else None
    
    quantidade_futura = request.GET.get('quantidade_futura')
    quantidade_futura = float(quantidade_futura) if (quantidade_futura and quantidade_futura != '') else None
    
    frete_valor = float(request.GET.get('frete_valor', 0) or 0)
    tipo_frete = request.GET.get('tipo_frete', 'valor')
    outros_valor = float(request.GET.get('outros_valor', 0) or 0)
    tipo_outros = request.GET.get('tipo_outros', 'valor')
    
    aliquotas_ids = request.GET.get('aliquotas_ids', '')
    aliquota_id = request.GET.get('aliquota_id', '')
    margem_desejada = float(request.GET.get('margem_desejada', 0) or 0)
    metodo = request.GET.get('metodo', 'inside')
    preco_praticado = float(request.GET.get('preco_praticado', 0) or 0)

    # 2. Buscar Produto
    produto = get_object_or_404(Produto, id=produto_id, empresa=empresa) if produto_id else None

    # 3. Cálculos da Simulação (Python)
    # Custo ponderado
    custo_base = preco_custo
    qtd_total_lote = quantidade_estoque
    is_compra_futura = False
    if preco_custo_futuro and quantidade_futura and quantidade_futura > 0:
        qtd_total_lote = quantidade_estoque + quantidade_futura
        if qtd_total_lote > 0:
            custo_base = ((preco_custo * quantidade_estoque) + (preco_custo_futuro * quantidade_futura)) / qtd_total_lote
            is_compra_futura = True
            
    # Rateio Frete
    frete_unit = 0.0
    if tipo_frete == 'valor':
        frete_unit = frete_valor
    elif tipo_frete == 'percentual':
        frete_unit = custo_base * (frete_valor / 100.0)
    elif tipo_frete == 'total':
        frete_unit = frete_valor / (qtd_total_lote if qtd_total_lote > 0 else 1.0)

    # Rateio Outros
    outros_unit = 0.0
    if tipo_outros == 'valor':
        outros_unit = outros_valor
    elif tipo_outros == 'percentual':
        outros_unit = custo_base * (outros_valor / 100.0)
    elif tipo_outros == 'total':
        outros_unit = outros_valor / (qtd_total_lote if qtd_total_lote > 0 else 1.0)

    custo_efetivo = custo_base + frete_unit + outros_unit

    # Alíquotas de imposto (suporte a múltiplos impostos)
    imposto_pct = 0.0
    aliquota_nome = "Sem Impostos"
    aliquotas_detalhe = []

    if aliquotas_ids:
        ids_list = [int(i.strip()) for i in aliquotas_ids.split(',') if i.strip().isdigit()]
        if ids_list:
            aliqs = AliquotaImposto.objects.filter(id__in=ids_list, empresa=empresa)
            nomes_list = []
            for a in aliqs:
                p = float(a.percentual)
                imposto_pct += p
                nomes_list.append(f"{a.nome} ({p:.2f}%)")
                aliquotas_detalhe.append({
                    'nome': a.nome,
                    'percentual': p,
                    'valor': round(preco_praticado * (p / 100.0), 2) if preco_praticado > 0 else 0.0
                })
            if nomes_list:
                aliquota_nome = " + ".join(nomes_list)
    elif aliquota_id and aliquota_id != '0':
        aliq = AliquotaImposto.objects.filter(id=aliquota_id, empresa=empresa).first()
        if aliq:
            p = float(aliq.percentual)
            imposto_pct = p
            aliquota_nome = f"{aliq.nome} ({p:.2f}%)"
            aliquotas_detalhe.append({
                'nome': aliq.nome,
                'percentual': p,
                'valor': round(preco_praticado * (p / 100.0), 2) if preco_praticado > 0 else 0.0
            })
    else:
        try:
            param_pct = float(request.GET.get('aliquota_percentual', 0) or 0)
            if param_pct > 0:
                imposto_pct = param_pct
                aliquota_nome = request.GET.get('aliquota_nome', f'Impostos ({param_pct:.2f}%)')
        except ValueError:
            pass

    # Preço Sugerido
    preco_sugerido = 0.0
    if metodo == 'inside':
        divisor = (100.0 - (imposto_pct + margem_desejada)) / 100.0
        if divisor > 0:
            preco_sugerido = custo_efetivo / divisor
    else:
        divisor_venda = (100.0 - imposto_pct) / 100.0
        if divisor_venda > 0:
            preco_sugerido = (custo_efetivo * (1.0 + margem_desejada / 100.0)) / divisor_venda
    preco_sugerido = round(preco_sugerido, 2)

    # Preço praticado cálculos
    divisor_imposto = (100.0 - imposto_pct) / 100.0
    valor_produto_sem_imposto = 0.0
    valor_imposto = 0.0
    if divisor_imposto == 0:
        valor_imposto = preco_praticado
    else:
        valor_produto_sem_imposto = round(preco_praticado * divisor_imposto, 2)
        valor_imposto = round(preco_praticado - valor_produto_sem_imposto, 2)

    lucro_liquido = round(valor_produto_sem_imposto - custo_efetivo, 2)
    margem_realizada = (lucro_liquido / preco_praticado * 100.0) if preco_praticado > 0 else 0.0
    markup_realizado = (lucro_liquido / custo_efetivo * 100.0) if custo_efetivo > 0 else 0.0
    
    # Prospecção de lucro total do lote
    lucro_total_lote = lucro_liquido * qtd_total_lote
    
    # Ponto de Equilíbrio
    preco_minimo = (custo_efetivo / divisor_imposto) if divisor_imposto > 0 else 0.0
    preco_minimo = round(preco_minimo, 2)

    return render(request, 'estoque/simulador_pdf.html', {
        'empresa': empresa,
        'produto': produto,
        'preco_custo': preco_custo,
        'quantidade_estoque': quantidade_estoque,
        'preco_custo_futuro': preco_custo_futuro,
        'quantidade_futura': quantidade_futura,
        'frete_valor': frete_valor,
        'tipo_frete': tipo_frete,
        'outros_valor': outros_valor,
        'tipo_outros': tipo_outros,
        'aliquota_nome': aliquota_nome,
        'aliquota_percentual': imposto_pct,
        'aliquotas_detalhe': aliquotas_detalhe,
        'margem_desejada': margem_desejada,
        'metodo': metodo,
        'custo_base': custo_base,
        'frete_unit': frete_unit,
        'outros_unit': outros_unit,
        'custo_efetivo': custo_efetivo,
        'preco_sugerido': preco_sugerido,
        'preco_praticado': preco_praticado,
        'valor_imposto': valor_imposto,
        'lucro_liquido': lucro_liquido,
        'margem_realizada': margem_realizada,
        'markup_realizado': markup_realizado,
        'lucro_total_lote': lucro_total_lote,
        'qtd_total_lote': qtd_total_lote,
        'preco_minimo': preco_minimo,
        'data_emissao': timezone.now()
    })


@login_required
def lista_simulacoes_pdf(request):
    empresa = get_empresa_usuario(request.user)
    query = request.GET.get('q', '')
    
    simulacoes = SimulacaoPreco.objects.filter(empresa=empresa)
    if query:
        simulacoes = simulacoes.filter(produto__nome__icontains=query)
        
    simulacoes = simulacoes.select_related('produto').order_by('-data_criacao')
    
    # Calcular estatísticas básicas para o resumo do relatório
    total_simulacoes = simulacoes.count()
    total_itens = sum(s.quantidade_total for s in simulacoes)
    
    margens = [float(s.margem_realizada) for s in simulacoes]
    media_margem = sum(margens) / len(margens) if margens else 0.0
    
    lucros = [float(s.lucro_liquido) for s in simulacoes]
    total_lucro_potencial = sum(lucros)
    
    lucros_lote = [s.lucro_total_lote for s in simulacoes]
    total_lucro_lote = sum(lucros_lote)
    
    return render(request, 'estoque/lista_simulacoes_pdf.html', {
        'empresa': empresa,
        'simulacoes': simulacoes,
        'query': query,
        'total_simulacoes': total_simulacoes,
        'total_itens': total_itens,
        'media_margem': media_margem,
        'total_lucro_potencial': total_lucro_potencial,
        'total_lucro_lote': total_lucro_lote,
        'data_emissao': timezone.now()
    })


# =============================================================================
# 14. MÓDULO COMERCIAL: CLIENTES, VENDAS E CREDIÁRIO
# =============================================================================

# -----------------------------------------------------------------------------
# 14.1 GESTÃO DE CLIENTES
# -----------------------------------------------------------------------------

@login_required
def lista_clientes(request):
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        return redirect('cadastro_saas')

    clientes = Cliente.objects.filter(empresa=empresa)
    
    # Filtro de texto
    q = request.GET.get('q', '').strip()
    if q:
        clientes = clientes.filter(
            Q(nome__icontains=q) |
            Q(cpf_cnpj__icontains=q) |
            Q(telefone__icontains=q) |
            Q(cidade__icontains=q)
        )

    # Filtro de status
    filtro = request.GET.get('filtro', 'todos')
    hoje = timezone.now().date()
    if filtro == 'ativos':
        clientes = clientes.filter(ativo=True)
    elif filtro == 'inativos':
        clientes = clientes.filter(ativo=False)
    elif filtro == 'com_debito':
        clientes = clientes.filter(
            contas__status__in=['PENDENTE', 'ATRASADO']
        ).distinct()

    # Estatísticas
    total_cadastrados = Cliente.objects.filter(empresa=empresa).count()
    clientes_inadimplentes = Cliente.objects.filter(
        empresa=empresa,
        contas__status='PENDENTE',
        contas__data_vencimento__lt=hoje
    ).distinct().count()

    paginator = Paginator(clientes, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'estoque/lista_clientes.html', {
        'page_obj': page_obj,
        'q': q,
        'filtro': filtro,
        'total_cadastrados': total_cadastrados,
        'clientes_inadimplentes': clientes_inadimplentes,
    })


@login_required
def criar_cliente(request):
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        return redirect('cadastro_saas')

    if request.method == 'POST':
        form = ClienteForm(request.POST)
        if form.is_valid():
            cliente = form.save(commit=False)
            cliente.empresa = empresa
            cliente.save()
            messages.success(request, f"Cliente '{cliente.nome}' cadastrado com sucesso!")
            return redirect('detalhe_cliente', pk=cliente.pk)
    else:
        form = ClienteForm()

    return render(request, 'estoque/form_cliente.html', {
        'form': form,
        'titulo': "Novo Cliente"
    })


@login_required
def editar_cliente(request, pk):
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        return redirect('cadastro_saas')

    cliente = get_object_or_404(Cliente, pk=pk, empresa=empresa)

    if request.method == 'POST':
        form = ClienteForm(request.POST, instance=cliente)
        if form.is_valid():
            form.save()
            messages.success(request, f"Cadastro de '{cliente.nome}' atualizado com sucesso!")
            return redirect('detalhe_cliente', pk=cliente.pk)
    else:
        form = ClienteForm(instance=cliente)

    return render(request, 'estoque/form_cliente.html', {
        'form': form,
        'cliente': cliente,
        'titulo': f"Editar Cliente: {cliente.nome}"
    })


@login_required
def detalhe_cliente(request, pk):
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        return redirect('cadastro_saas')

    cliente = get_object_or_404(Cliente, pk=pk, empresa=empresa)
    vendas = cliente.vendas.filter(empresa=empresa).order_by('-data_venda')[:15]
    contas = cliente.contas.filter(empresa=empresa).select_related('venda').order_by('data_vencimento')
    form_receber = ReceberPagamentoForm()

    return render(request, 'estoque/detalhe_cliente.html', {
        'cliente': cliente,
        'vendas': vendas,
        'contas': contas,
        'form_receber': form_receber,
    })


@login_required
def api_buscar_clientes(request):
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        return JsonResponse([], safe=False)

    q = request.GET.get('q', '').strip()
    clientes = Cliente.objects.filter(empresa=empresa, ativo=True)
    if q:
        clientes = clientes.filter(
            Q(nome__icontains=q) |
            Q(cpf_cnpj__icontains=q) |
            Q(telefone__icontains=q) |
            Q(email__icontains=q) |
            Q(cidade__icontains=q) |
            Q(endereco__icontains=q)
        )

    data = []
    for c in clientes[:50]:
        data.append({
            'id': c.id,
            'nome': c.nome,
            'cpf_cnpj': c.cpf_cnpj or '',
            'telefone': c.telefone or '',
            'email': c.email or '',
            'cidade': c.cidade or '',
            'endereco': c.endereco or '',
            'limite_credito': float(c.limite_credito or 0),
            'saldo_devedor': float(c.saldo_devedor),
            'limite_disponivel': float(c.limite_disponivel),
            'tem_debitos_vencidos': c.tem_debitos_vencidos,
        })

    return JsonResponse(data, safe=False)


@login_required
def api_buscar_produtos(request):
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        return JsonResponse([], safe=False)

    q = request.GET.get('q', '').strip()
    produtos = Produto.objects.filter(empresa=empresa, ativo=True).select_related('categoria', 'localizacao').annotate(
        qtd_real=Coalesce(Sum('lotes__quantidade_atual', filter=Q(lotes__status='ATIVO')), 0)
    ).order_by('nome')

    if q:
        produtos = produtos.filter(
            Q(nome__icontains=q) |
            Q(sku__icontains=q) |
            Q(ean__icontains=q) |
            Q(categoria__nome__icontains=q) |
            Q(localizacao__nome__icontains=q)
        ).distinct()

    data = []
    for p in produtos[:50]:
        data.append({
            'id': p.id,
            'nome': p.nome,
            'sku': p.sku or '',
            'ean': p.ean or '',
            'categoria': p.categoria.nome if p.categoria else '',
            'localizacao': p.localizacao.nome if p.localizacao else '',
            'unidade': p.unidade,
            'unidade_display': p.get_unidade_display(),
            'saldo': p.qtd_real,
            'preco_medio': float(p.preco_medio or 0),
        })

    return JsonResponse(data, safe=False)


# -----------------------------------------------------------------------------
# 14.2 TERMINAL DE VENDAS (PDV & CHECKOUT)
# -----------------------------------------------------------------------------

@login_required
def registrar_venda(request):
    import uuid
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        return redirect('cadastro_saas')

    error_message = None

    if request.method == 'POST':
        itens_json = request.POST.get('itens_json')
        forma_pagamento = request.POST.get('forma_pagamento', 'DINHEIRO')
        cliente_id = request.POST.get('cliente_id')
        desconto_str = request.POST.get('desconto', '0').replace(',', '.')
        observacoes = request.POST.get('observacoes', '').strip()

        # Parâmetros de Crediário
        num_parcelas = int(request.POST.get('num_parcelas', 1) or 1)
        primeiro_vencimento_str = request.POST.get('primeiro_vencimento')
        intervalo_dias = int(request.POST.get('intervalo_dias', 30) or 30)

        try:
            desconto = float(desconto_str) if desconto_str else 0.0
            if desconto < 0:
                desconto = 0.0
        except ValueError:
            desconto = 0.0

        if not itens_json:
            error_message = "Adicione ao menos um produto à venda antes de finalizar."
        else:
            try:
                itens = json.loads(itens_json)
                if not itens or not isinstance(itens, list):
                    raise ValueError("Lista de itens vazia ou inválida.")

                cliente = None
                if cliente_id:
                    cliente = Cliente.objects.filter(id=cliente_id, empresa=empresa).first()

                if forma_pagamento == 'CREDIARIO' and not cliente:
                    raise ValueError("Para realizar vendas no Crediário / A Prazo, é obrigatório selecionar um cliente cadastrado.")

                if forma_pagamento == 'CREDIARIO' and cliente and not cliente.ativo:
                    raise ValueError(f"O cliente '{cliente.nome}' está inativo no sistema.")

                # Processamento com transação atômica
                with transaction.atomic():
                    codigo_venda = f"VD-{timezone.now().strftime('%y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
                    
                    subtotal_geral = 0.0
                    itens_para_criar = []

                    for idx, item in enumerate(itens, 1):
                        prod_id = item.get('produto_id')
                        qtd = int(item.get('quantidade', 0))
                        preco_unit = float(item.get('preco_unitario', 0.0))
                        lote_id = item.get('lote_id')

                        if qtd <= 0:
                            raise ValueError(f"Quantidade inválida para o produto #{idx}.")
                        if preco_unit < 0:
                            raise ValueError(f"Preço unitário inválido para o produto #{idx}.")

                        subtotal_item = round(qtd * preco_unit, 2)
                        subtotal_geral += subtotal_item

                        produto = Produto.objects.select_for_update().get(id=prod_id, empresa=empresa)

                        # Dedução no estoque: Lote específico ou FIFO
                        if lote_id:
                            lote = Lote.objects.select_for_update().get(id=lote_id, produto=produto)
                            if lote.quantidade_atual < qtd:
                                raise ValueError(f"Saldo insuficiente no Lote '{lote.numero_lote}' do produto '{produto.nome}'. Saldo atual: {lote.quantidade_atual}, solicitado: {qtd}.")
                            lote.quantidade_atual -= qtd
                            lote.save()

                            saida = SaidaEstoque.objects.create(
                                produto=produto,
                                lote=lote,
                                quantidade=qtd,
                                motivo=f"Venda {codigo_venda} - {cliente.nome if cliente else 'Consumidor Final'}",
                                usuario=request.user,
                                valor_venda=preco_unit,
                                codigo_grupo=codigo_venda
                            )
                            itens_para_criar.append({
                                'produto': produto,
                                'lote': lote,
                                'quantidade': qtd,
                                'preco_unitario': preco_unit,
                                'subtotal': subtotal_item,
                                'saida_estoque': saida
                            })
                        else:
                            if produto.saldo_total < qtd:
                                raise ValueError(f"Saldo insuficiente para o produto '{produto.nome}'. Estoque disponível: {produto.saldo_total}, solicitado: {qtd}.")

                            lotes_ativos = Lote.objects.select_for_update().filter(
                                produto=produto,
                                status='ATIVO',
                                quantidade_atual__gt=0
                            ).order_by(
                                Case(
                                    When(data_validade__isnull=False, then='data_validade'),
                                    default='data_fabricacao'
                                ),
                                'id'
                            )

                            restante = qtd
                            for l in lotes_ativos:
                                if restante <= 0:
                                    break
                                qtd_abater = min(l.quantidade_atual, restante)
                                l.quantidade_atual -= qtd_abater
                                l.save()
                                restante -= qtd_abater

                                saida = SaidaEstoque.objects.create(
                                    produto=produto,
                                    lote=l,
                                    quantidade=qtd_abater,
                                    motivo=f"Venda {codigo_venda} - {cliente.nome if cliente else 'Consumidor Final'}",
                                    usuario=request.user,
                                    valor_venda=preco_unit,
                                    codigo_grupo=codigo_venda
                                )
                                itens_para_criar.append({
                                    'produto': produto,
                                    'lote': l,
                                    'quantidade': qtd_abater,
                                    'preco_unitario': preco_unit,
                                    'subtotal': round(qtd_abater * preco_unit, 2),
                                    'saida_estoque': saida
                                })

                            if restante > 0:
                                raise ValueError(f"Inconsistência de saldo para o produto '{produto.nome}'. Restaram {restante} unidades sem lote.")

                    valor_total = max(0.0, round(subtotal_geral - desconto, 2))

                    # Validação de Limite de Crediário
                    if forma_pagamento == 'CREDIARIO' and cliente:
                        if cliente.limite_credito > 0 and (float(cliente.saldo_devedor) + valor_total) > float(cliente.limite_credito):
                            disponivel = max(0.0, float(cliente.limite_credito) - float(cliente.saldo_devedor))
                            raise ValueError(f"O valor total (R$ {valor_total:.2f}) ultrapassa o limite disponível do cliente '{cliente.nome}' (R$ {disponivel:.2f}).")

                    # Criação da Venda
                    status_pagamento = 'PENDENTE' if forma_pagamento == 'CREDIARIO' else 'PAGO'
                    venda = Venda.objects.create(
                        empresa=empresa,
                        codigo_venda=codigo_venda,
                        cliente=cliente,
                        usuario=request.user,
                        valor_subtotal=subtotal_geral,
                        desconto=desconto,
                        valor_total=valor_total,
                        forma_pagamento=forma_pagamento,
                        status='CONCLUIDA',
                        status_pagamento=status_pagamento,
                        observacoes=observacoes
                    )

                    # Persistência dos Itens
                    for item_data in itens_para_criar:
                        ItemVenda.objects.create(
                            venda=venda,
                            produto=item_data['produto'],
                            nome_produto=item_data['produto'].nome if item_data['produto'] else "Item de Venda",
                            lote=item_data['lote'],
                            quantidade=item_data['quantidade'],
                            preco_unitario=item_data['preco_unitario'],
                            subtotal=item_data['subtotal'],
                            saida_estoque=item_data['saida_estoque']
                        )

                    # Geração de Parcelas do Crediário
                    if forma_pagamento == 'CREDIARIO':
                        num_parcelas = max(1, min(num_parcelas, 36))
                        valor_parcela_base = round(valor_total / num_parcelas, 2)
                        diferenca = round(valor_total - (valor_parcela_base * num_parcelas), 2)

                        if primeiro_vencimento_str:
                            try:
                                dt_base = datetime.strptime(primeiro_vencimento_str, '%Y-%m-%d').date()
                            except ValueError:
                                dt_base = timezone.now().date() + timedelta(days=intervalo_dias)
                        else:
                            dt_base = timezone.now().date() + timedelta(days=intervalo_dias)

                        for i in range(num_parcelas):
                            venc = dt_base + timedelta(days=i * intervalo_dias)
                            valor_p = valor_parcela_base
                            if i == 0:
                                valor_p = round(valor_p + diferenca, 2)

                            ContaReceber.objects.create(
                                empresa=empresa,
                                cliente=cliente,
                                venda=venda,
                                numero_parcela=i + 1,
                                total_parcelas=num_parcelas,
                                valor_parcela=valor_p,
                                valor_pago=0.00,
                                data_vencimento=venc,
                                status='PENDENTE'
                            )

                    messages.success(request, f"Venda {codigo_venda} registrada com sucesso! Total: R$ {valor_total:.2f}")
                    return redirect('detalhe_venda', pk=venda.pk)

            except Exception as e:
                error_message = str(e)

    # Contexto para renderização do formulário
    produtos = Produto.objects.filter(empresa=empresa).annotate(
        qtd_real=Coalesce(Sum('lotes__quantidade_atual', filter=Q(lotes__status='ATIVO')), 0)
    ).order_by('nome')
    clientes = Cliente.objects.filter(empresa=empresa, ativo=True).order_by('nome')
    hoje = timezone.now().date()
    primeiro_venc_padrao = (hoje + timedelta(days=30)).strftime('%Y-%m-%d')

    return render(request, 'estoque/form_venda.html', {
        'produtos': produtos,
        'clientes': clientes,
        'error_message': error_message,
        'primeiro_venc_padrao': primeiro_venc_padrao,
    })


@login_required
def lista_vendas(request):
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        return redirect('cadastro_saas')

    vendas = Venda.objects.filter(empresa=empresa).select_related('cliente', 'usuario')

    q = request.GET.get('q', '').strip()
    if q:
        vendas = vendas.filter(
            Q(codigo_venda__icontains=q) |
            Q(cliente__nome__icontains=q)
        )

    forma_pagamento = request.GET.get('forma_pagamento')
    if forma_pagamento:
        vendas = vendas.filter(forma_pagamento=forma_pagamento)

    status_pagamento = request.GET.get('status_pagamento')
    if status_pagamento:
        vendas = vendas.filter(status_pagamento=status_pagamento)

    data_inicio = request.GET.get('data_inicio')
    data_fim = request.GET.get('data_fim')
    if data_inicio:
        vendas = vendas.filter(data_venda__date__gte=data_inicio)
    if data_fim:
        vendas = vendas.filter(data_venda__date__lte=data_fim)

    total_faturado = vendas.filter(status='CONCLUIDA').aggregate(total=Sum('valor_total'))['total'] or 0.00

    paginator = Paginator(vendas, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'estoque/lista_vendas.html', {
        'page_obj': page_obj,
        'q': q,
        'forma_pagamento': forma_pagamento,
        'status_pagamento': status_pagamento,
        'data_inicio': data_inicio,
        'data_fim': data_fim,
        'total_faturado': total_faturado,
    })


@login_required
def detalhe_venda(request, pk):
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        return redirect('cadastro_saas')

    venda = get_object_or_404(
        Venda.objects.select_related('cliente', 'usuario', 'empresa').prefetch_related('itens__produto', 'itens__lote', 'parcelas'),
        pk=pk,
        empresa=empresa
    )

    return render(request, 'estoque/detalhe_venda.html', {
        'venda': venda,
    })


@login_required
def imprimir_cupom_venda(request, pk):
    """
    Renderiza o cupom não fiscal otimizado especificamente para impressoras térmicas
    (bobinas de 80mm e 58mm), com tipografia condensada e comando de impressão automático.
    """
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        return redirect('cadastro_saas')

    venda = get_object_or_404(
        Venda.objects.select_related('cliente', 'usuario', 'empresa').prefetch_related('itens__produto', 'parcelas'),
        pk=pk,
        empresa=empresa
    )

    return render(request, 'estoque/cupom_venda.html', {
        'venda': venda,
        'empresa': empresa,
    })


@login_required
def cancelar_venda(request, pk):
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        return redirect('cadastro_saas')

    # Apenas dono ou superuser pode cancelar vendas
    is_dono = getattr(request.user.userprofile, 'e_dono', False) or request.user.is_superuser
    if not is_dono:
        messages.error(request, "Apenas administradores podem cancelar vendas.")
        return redirect('detalhe_venda', pk=pk)

    venda = get_object_or_404(Venda, pk=pk, empresa=empresa)

    if request.method == 'POST':
        if venda.status == 'CANCELADA':
            messages.warning(request, "Esta venda já está cancelada.")
            return redirect('detalhe_venda', pk=pk)

        # Checa se alguma parcela já foi paga
        if venda.parcelas.filter(valor_pago__gt=0).exists():
            messages.error(request, "Não é possível cancelar uma venda que já possui parcelas amortizadas ou pagas no crediário.")
            return redirect('detalhe_venda', pk=pk)

        with transaction.atomic():
            # 1. Estorna estoque de cada item
            for item in venda.itens.all():
                if item.lote:
                    lote = Lote.objects.select_for_update().get(id=item.lote.id)
                    lote.quantidade_atual += item.quantidade
                    lote.save()
                else:
                    ultimo_lote = Lote.objects.filter(produto=item.produto).order_by('-data_fabricacao', '-id').first()
                    if ultimo_lote:
                        ultimo_lote.quantidade_atual += item.quantidade
                        ultimo_lote.save()

                if item.saida_estoque:
                    item.saida_estoque.delete()

            # 2. Cancela parcelas do crediário
            venda.parcelas.update(status='CANCELADO')

            # 3. Marca venda como cancelada
            venda.status = 'CANCELADA'
            venda.status_pagamento = 'CANCELADO'
            venda.save()

            messages.success(request, f"Venda {venda.codigo_venda} cancelada e mercadorias estornadas ao estoque com sucesso.")

    return redirect('detalhe_venda', pk=pk)


# -----------------------------------------------------------------------------
# 14.3 GESTÃO DE CREDIÁRIO / CONTAS A RECEBER
# -----------------------------------------------------------------------------

@login_required
def painel_crediario(request):
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        return redirect('cadastro_saas')

    hoje = timezone.now().date()

    # Atualiza automaticamente parcelas vencidas para 'ATRASADO'
    ContaReceber.objects.filter(
        empresa=empresa,
        status='PENDENTE',
        data_vencimento__lt=hoje
    ).update(status='ATRASADO')

    contas = ContaReceber.objects.filter(empresa=empresa).select_related('cliente', 'venda')

    # Filtros
    status_filtro = request.GET.get('status', 'abertos')
    if status_filtro == 'abertos':
        contas = contas.filter(status__in=['PENDENTE', 'ATRASADO'])
    elif status_filtro == 'pendentes':
        contas = contas.filter(status='PENDENTE')
    elif status_filtro == 'atrasados':
        contas = contas.filter(status='ATRASADO')
    elif status_filtro == 'pagos':
        contas = contas.filter(status='PAGO')

    cliente_id = request.GET.get('cliente_id')
    if cliente_id:
        contas = contas.filter(cliente_id=cliente_id)

    q = request.GET.get('q', '').strip()
    if q:
        contas = contas.filter(
            Q(cliente__nome__icontains=q) |
            Q(venda__codigo_venda__icontains=q)
        )

    # Indicadores Globais
    contas_abertas = ContaReceber.objects.filter(empresa=empresa, status__in=['PENDENTE', 'ATRASADO'])
    total_a_receber = contas_abertas.aggregate(
        total=Sum(F('valor_parcela') - F('valor_pago'))
    )['total'] or 0.00

    total_vencido = ContaReceber.objects.filter(
        empresa=empresa,
        status='ATRASADO'
    ).aggregate(
        total=Sum(F('valor_parcela') - F('valor_pago'))
    )['total'] or 0.00

    # Total recebido neste mês corrente
    primeiro_dia_mes = hoje.replace(day=1)
    total_recebido_mes = PagamentoCrediario.objects.filter(
        empresa=empresa,
        data_recebimento__date__gte=primeiro_dia_mes
    ).aggregate(total=Sum('valor_recebido'))['total'] or 0.00

    clientes = Cliente.objects.filter(empresa=empresa).order_by('nome')

    paginator = Paginator(contas, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    form_receber = ReceberPagamentoForm()

    return render(request, 'estoque/painel_crediario.html', {
        'page_obj': page_obj,
        'status_filtro': status_filtro,
        'cliente_id': cliente_id,
        'q': q,
        'clientes': clientes,
        'total_a_receber': total_a_receber,
        'total_vencido': total_vencido,
        'total_recebido_mes': total_recebido_mes,
        'form_receber': form_receber,
        'hoje': hoje,
    })


@login_required
def baixar_parcela(request, pk):
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        return redirect('cadastro_saas')

    conta = get_object_or_404(
        ContaReceber.objects.select_related('cliente', 'venda'),
        pk=pk,
        empresa=empresa
    )

    if request.method == 'POST':
        form = ReceberPagamentoForm(request.POST)
        if form.is_valid():
            valor_recebido = form.cleaned_data['valor_recebido']
            forma_pagamento = form.cleaned_data['forma_pagamento']
            data_recebimento = form.cleaned_data['data_recebimento']
            observacoes = form.cleaned_data['observacoes']

            saldo_restante = round(float(conta.valor_parcela) - float(conta.valor_pago), 2)
            if float(valor_recebido) > saldo_restante + 0.01:
                messages.error(request, f"O valor informado (R$ {valor_recebido:.2f}) excede o saldo devedor da parcela (R$ {saldo_restante:.2f}).")
                next_url = request.POST.get('next')
                if next_url:
                    return redirect(next_url)
                return redirect('painel_crediario')

            with transaction.atomic():
                PagamentoCrediario.objects.create(
                    empresa=empresa,
                    conta=conta,
                    valor_recebido=valor_recebido,
                    forma_pagamento=forma_pagamento,
                    data_recebimento=timezone.now(),
                    usuario=request.user,
                    observacoes=observacoes
                )

                conta.valor_pago = round(float(conta.valor_pago) + float(valor_recebido), 2)
                if conta.valor_pago >= float(conta.valor_parcela) - 0.01:
                    conta.status = 'PAGO'
                    conta.data_pagamento = timezone.now()
                conta.save()

                # Atualiza status da Venda de origem
                venda = conta.venda
                parcelas_venda = venda.parcelas.all()
                if all(p.status == 'PAGO' for p in parcelas_venda):
                    venda.status_pagamento = 'PAGO'
                else:
                    venda.status_pagamento = 'PARCIAL'
                venda.save()

                messages.success(request, f"Recebimento de R$ {valor_recebido:.2f} registrado com sucesso para a parcela de {conta.cliente.nome}!")

    next_url = request.POST.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('painel_crediario')


# =============================================================================
# 15. GESTÃO DE ASSINATURAS SAAS & MERCADO PAGO
# =============================================================================

def _garantir_coluna_order_id():
    """
    Garante que a coluna mp_order_id exista no banco de dados (ex: PostgreSQL na Vercel).
    Executa DDL idempotente 'ADD COLUMN IF NOT EXISTS' para prevenir Server Error 500
    caso o comando 'python manage.py migrate' ainda não tenha sido rodado no banco remoto.
    """
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            if connection.vendor == 'postgresql':
                cursor.execute("ALTER TABLE estoque_pagamentoassinatura ADD COLUMN IF NOT EXISTS mp_order_id varchar(150);")
                cursor.execute("CREATE INDEX IF NOT EXISTS estoque_pagamentoassinatura_mp_order_id_idx ON estoque_pagamentoassinatura(mp_order_id);")
            elif connection.vendor == 'sqlite':
                cursor.execute("PRAGMA table_info(estoque_pagamentoassinatura);")
                cols = [row[1] for row in cursor.fetchall()]
                if 'mp_order_id' not in cols:
                    cursor.execute("ALTER TABLE estoque_pagamentoassinatura ADD COLUMN mp_order_id varchar(150);")
    except Exception as e:
        logger.warning(f"[Garantia Coluna] Aviso ao verificar/criar coluna mp_order_id: {e}")


@login_required
def minha_assinatura(request):
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        return redirect('cadastro_saas')

    _garantir_coluna_order_id()

    # Sincroniza pagamentos pendentes recentes desta empresa com a API do Mercado Pago
    try:
        sincronizar_pagamentos_pendentes(empresa=empresa)
    except Exception as e:
        logger.warning(f"[Minha Assinatura] Erro ao sincronizar pagamentos: {e}")

    # Status e histórico de pagamentos
    try:
        pagamentos = empresa.pagamentos_assinatura.all().order_by('-data_criacao')[:10]
    except Exception:
        _garantir_coluna_order_id()
        pagamentos = empresa.pagamentos_assinatura.all().order_by('-data_criacao')[:10]
    
    # Feedback e ativação de retorno oficial do Mercado Pago (Back URLs)
    status_mp = (request.GET.get('status_mp') or request.GET.get('status') or request.GET.get('collection_status') or '').lower()
    payment_id = request.GET.get('payment_id') or request.GET.get('collection_id')
    order_id = request.GET.get('order_id') or request.GET.get('preference_id')

    if status_mp in ('aprovado', 'approved'):
        pagamento_confirmado = False
        valor_aprovado = VALOR_ASSINATURA_PADRAO
        id_operacao_real = payment_id or order_id

        # [SEGURANÇA] Validação estrita: Nunca aprovar apenas por parâmetros GET na URL.
        # Devemos checar na API do Mercado Pago se a transação realmente existe,
        # se está com status 'approved'/'paid' e se pertence a esta empresa.
        if is_mercadopago_configured():
            identificador_order = order_id or payment_id
            if identificador_order and str(identificador_order).startswith('ORD'):
                dados_ord = consultar_order_mp(identificador_order)
                if dados_ord:
                    st = dados_ord.get('status')
                    ref = dados_ord.get('external_reference')
                    if st in ('closed', 'processed', 'paid', 'approved') and str(ref) == str(empresa.id):
                        pagamento_confirmado = True
                        if dados_ord.get('transactions', {}).get('payments'):
                            first_p = dados_ord['transactions']['payments'][0]
                            id_operacao_real = str(first_p.get('reference_id') or first_p.get('id') or identificador_order)

            if not pagamento_confirmado and payment_id:
                dados_pay = consultar_pagamento_mp(payment_id)
                if dados_pay:
                    st = dados_pay.get('status')
                    ref = dados_pay.get('external_reference')
                    if st == 'approved' and str(ref) == str(empresa.id):
                        pagamento_confirmado = True
                        id_operacao_real = str(dados_pay.get('id', payment_id))
                        valor_aprovado = Decimal(str(dados_pay.get('transaction_amount', VALOR_ASSINATURA_PADRAO)))
        elif settings.DEBUG:
            # Em modo puramente de desenvolvimento (sem chaves configuradas), só aprova se houver
            # registro PENDENTE legítimo já cadastrado no banco para esta empresa
            if order_id or payment_id:
                pag_pend = PagamentoAssinatura.objects.filter(
                    empresa=empresa,
                    status='PENDENTE'
                ).filter(
                    Q(mp_preference_id=order_id) | Q(mp_payment_id=payment_id)
                ).first()
                if pag_pend:
                    pagamento_confirmado = True
                    valor_aprovado = pag_pend.valor

        if pagamento_confirmado:
            order_param = order_id if (order_id and str(order_id).startswith('ORD')) else (payment_id if (payment_id and str(payment_id).startswith('ORD')) else None)
            processar_aprovacao_assinatura(
                empresa=empresa,
                payment_id=id_operacao_real,
                preference_id=order_id,
                order_id=order_param,
                metodo='MERCADO_PAGO',
                valor=valor_aprovado,
                dias=30,
                observacoes="Aprovado no retorno do checkout Mercado Pago (Verificado)"
            )
            messages.success(request, "Pagamento aprovado e verificado com sucesso! Sua assinatura de 30 dias está ativa.")
        else:
            logger.warning(
                f"[Segurança] Retorno com status '{status_mp}' não pôde ser verificado para empresa {empresa.id} (pay_id={payment_id}, ord_id={order_id})."
            )
            messages.info(request, "Seu pagamento foi recebido e está em processamento pelo Mercado Pago. A liberação será concluída automaticamente.")
    elif status_mp in ('pendente', 'pending', 'in_process'):
        messages.info(request, "Seu pagamento está em análise ou aguardando compensação do Pix.")
    elif status_mp in ('falha', 'rejected', 'cancelled'):
        messages.error(request, "O pagamento não foi concluído ou foi cancelado. Tente novamente ou use outra forma de pagamento.")

    mp_configurado = is_mercadopago_configured()

    contexto = {
        'empresa': empresa,
        'pagamentos': pagamentos,
        'valor_padrao': VALOR_ASSINATURA_PADRAO,
        'mp_configurado': mp_configurado,
        'bloqueado': request.GET.get('bloqueado') or request.GET.get('expirado'),
    }
    return render(request, 'estoque/minha_assinatura.html', contexto)


@login_required
def iniciar_checkout_mercadopago(request):
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        return redirect('cadastro_saas')

    if not is_mercadopago_configured():
        if request.user.is_superuser:
            return redirect('simular_pagamento_mp')
        messages.warning(request, "O pagamento online via Mercado Pago está em processo de configuração pela administração. Entre em contato com o suporte para ativar sua assinatura.")
        return redirect('minha_assinatura')

    resultado = criar_preferencia_assinatura(empresa, request)
    
    # Registra a intenção de pagamento pendente
    pref_id = resultado.get('id')
    PagamentoAssinatura.objects.create(
        empresa=empresa,
        valor=VALOR_ASSINATURA_PADRAO,
        metodo='MERCADO_PAGO' if not resultado.get('simulacao') else 'SIMULACAO',
        status='PENDENTE',
        mp_order_id=pref_id if (pref_id and str(pref_id).startswith('ORD')) else None,
        mp_preference_id=pref_id,
        mp_init_point=resultado.get('init_point'),
        observacoes="Iniciou checkout no Mercado Pago"
    )

    url_destino = resultado.get('init_point')
    return redirect(url_destino)


@login_required
def simular_pagamento_mp(request):
    """
    Simulação rápida para ambiente de desenvolvimento/testes
    sem necessidade de credenciais de produção do Mercado Pago.
    [SEGURANÇA] Bloqueado estritamente para usuários comuns.
    """
    if not request.user.is_superuser:
        raise Http404("Modo de simulação indisponível.")

    empresa_id = request.GET.get('empresa_id')
    if empresa_id:
        if not request.user.is_superuser:
            raise Http404("Apenas o Superadministrador pode simular pagamentos para outras empresas.")
        empresa = get_object_or_404(Empresa, id=empresa_id)
    else:
        empresa = get_empresa_usuario(request.user)

    if not empresa:
        return redirect('cadastro_saas')

    processar_aprovacao_assinatura(
        empresa=empresa,
        metodo='SIMULACAO',
        valor=Decimal('0.00'),
        dias=30,
        observacoes='Pagamento de demonstração / simulação aprovado'
    )
    messages.success(request, f"Pagamento simulado com sucesso! A empresa '{empresa.nome}' agora possui 30 dias de assinatura ativa.")
    return redirect('minha_assinatura')


@csrf_exempt
def webhook_mercadopago(request):
    """
    Webhook do Mercado Pago (Orders API e Payments API).
    Recebe eventos de aprovação em tempo real e ativa a assinatura automaticamente.
    Valida a assinatura criptográfica x-signature se MERCADO_PAGO_WEBHOOK_SECRET estiver configurado.
    Retorna sempre HTTP 200 OK dentro da tolerância exigida pelo Mercado Pago (22s).
    """
    if request.method not in ('POST', 'GET'):
        return HttpResponse(status=405)

    # [SEGURANÇA] Proteção contra DoS: limita tamanho máximo do payload a 64KB
    if len(request.body) > 65536:
        return HttpResponse("Payload too large", status=400)

    # [SEGURANÇA] Rate limiting por IP no webhook: máximo de 120 requisições por minuto por IP
    ip_cliente = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR')
    chave_cache = f"rl_webhook_{ip_cliente}"
    tentativas = cache.get(chave_cache, 0)
    if tentativas >= 120:
        logger.warning(f"[MercadoPago Webhook] Limite de requisições excedido pelo IP {ip_cliente}")
        return HttpResponse("Too Many Requests", status=429)
    cache.set(chave_cache, tentativas + 1, timeout=60)

    secret = getattr(settings, 'MERCADO_PAGO_WEBHOOK_SECRET', '').strip()
    if secret:
        if not verificar_assinatura_webhook(request, secret):
            logger.warning("[MercadoPago Webhook] Assinatura HMAC inválida recebida.")
            return HttpResponse("Assinatura inválida", status=401)

    topic = request.GET.get('topic') or request.GET.get('type')
    resource_id = request.GET.get('id') or request.GET.get('data.id')

    if not resource_id and request.body:
        try:
            body_data = json.loads(request.body.decode('utf-8'))
            topic = topic or body_data.get('type') or body_data.get('action')
            resource_id = body_data.get('data', {}).get('id') or body_data.get('id')
        except Exception:
            pass

    if resource_id:
        resource_id_str = str(resource_id).strip()
        # [SEGURANÇA] Sanitização do resource_id para prevenir injeção
        if not re.match(r'^[a-zA-Z0-9_\-\.]{1,80}$', resource_id_str):
            return HttpResponse("ID inválido", status=400)

        # 1. Notificação de Order (Orders API v1/orders)
        if (topic and 'order' in str(topic).lower()) or resource_id_str.startswith('ORD'):
            dados_order = consultar_order_mp(resource_id_str)
            if dados_order:
                order_status = dados_order.get('status')
                ref_externa = dados_order.get('external_reference')
                total = dados_order.get('total_amount', float(VALOR_ASSINATURA_PADRAO))
                if order_status in ('closed', 'processed', 'paid', 'approved') and ref_externa:
                    try:
                        empresa = Empresa.objects.get(id=int(ref_externa))
                        real_pay_id = resource_id_str
                        if dados_order.get('transactions', {}).get('payments'):
                            first_p = dados_order['transactions']['payments'][0]
                            real_pay_id = str(first_p.get('reference_id') or first_p.get('id') or resource_id_str)

                        processar_aprovacao_assinatura(
                            empresa=empresa,
                            payment_id=real_pay_id,
                            preference_id=resource_id_str,
                            order_id=resource_id_str,
                            metodo='MERCADO_PAGO',
                            valor=Decimal(str(total)),
                            dias=30,
                            observacoes=f"Aprovado via Webhook Orders MP (Status: {order_status})"
                        )
                    except (Empresa.DoesNotExist, ValueError, TypeError):
                        pass
        else:
            # 2. Notificação de Payment (v1/payments)
            dados_pagamento = consultar_pagamento_mp(resource_id_str)
            if dados_pagamento:
                status = dados_pagamento.get('status')
                ref_externa = dados_pagamento.get('external_reference')
                valor = dados_pagamento.get('transaction_amount', float(VALOR_ASSINATURA_PADRAO))

                if status == 'approved' and ref_externa:
                    try:
                        empresa = Empresa.objects.get(id=int(ref_externa))
                        order_id_found = dados_pagamento.get('order', {}).get('id')
                        processar_aprovacao_assinatura(
                            empresa=empresa,
                            payment_id=resource_id_str,
                            order_id=str(order_id_found) if order_id_found else None,
                            metodo='MERCADO_PAGO',
                            valor=Decimal(str(valor)),
                            dias=30,
                            observacoes=f"Aprovado via Webhook Mercado Pago (Status: {status})"
                        )
                    except (Empresa.DoesNotExist, ValueError, TypeError):
                        pass

    return HttpResponse("OK", status=200)


# =============================================================================
# 16. PAINEL SUPERADMIN DE ASSINATURAS & GESTÃO DE USUÁRIOS
# =============================================================================

@login_required
def painel_superadmin_assinaturas(request):
    if not request.user.is_superuser:
        raise Http404("Acesso restrito ao Superadministrador.")

    _garantir_coluna_order_id()

    # Sincroniza pagamentos pendentes recentes de todas as empresas com o Mercado Pago
    try:
        sincronizar_pagamentos_pendentes()
    except Exception as e:
        logger.warning(f"[Superadmin Assinaturas] Erro ao sincronizar pagamentos pendentes: {e}")

    query = request.GET.get('q', '').strip()
    filtro_status = request.GET.get('status', 'todos')

    empresas = Empresa.objects.all().order_by('-data_criacao')

    # Métricas Gerais
    total_empresas = Empresa.objects.count()
    total_ativas = Empresa.objects.filter(status_assinatura='ATIVA').count()
    total_trial = Empresa.objects.filter(status_assinatura='TRIAL').count()
    total_vencidas = Empresa.objects.filter(status_assinatura__in=['VENCIDA', 'CANCELADA']).count()
    
    try:
        receita_total = PagamentoAssinatura.objects.filter(
            status='APROVADO'
        ).exclude(
            metodo__in=['MANUAL_ADMIN', 'SIMULACAO', 'CORTESIA']
        ).aggregate(total=Sum('valor'))['total'] or Decimal('0.00')
    except Exception:
        _garantir_coluna_order_id()
        receita_total = Decimal('0.00')

    # Filtros
    if query:
        empresas = empresas.filter(
            Q(nome__icontains=query) |
            Q(cnpj__icontains=query) |
            Q(userprofile__user__email__icontains=query) |
            Q(userprofile__user__first_name__icontains=query)
        ).distinct()

    if filtro_status == 'ativas':
        empresas = empresas.filter(status_assinatura='ATIVA')
    elif filtro_status == 'trial':
        empresas = empresas.filter(status_assinatura='TRIAL')
    elif filtro_status == 'vencidas':
        empresas = empresas.filter(status_assinatura__in=['VENCIDA', 'CANCELADA'])
    elif filtro_status == 'bloqueadas':
        empresas = empresas.filter(ativo=False)

    # Paginação
    paginator = Paginator(empresas, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Últimos pagamentos aprovados do sistema (exibe até 20 transações mais recentes)
    try:
        ultimos_pagamentos = PagamentoAssinatura.objects.select_related('empresa').order_by('-data_criacao')[:20]
    except Exception:
        _garantir_coluna_order_id()
        ultimos_pagamentos = []

    contexto = {
        'page_obj': page_obj,
        'query': query,
        'filtro_status': filtro_status,
        'total_empresas': total_empresas,
        'total_ativas': total_ativas,
        'total_trial': total_trial,
        'total_vencidas': total_vencidas,
        'receita_total': receita_total,
        'ultimos_pagamentos': ultimos_pagamentos,
        'mp_configurado': is_mercadopago_configured(),
    }
    return render(request, 'estoque/superadmin_assinaturas.html', contexto)


@login_required
def prorrogar_trial_superadmin(request, pk):
    if not request.user.is_superuser:
        raise Http404("Acesso restrito.")
    if request.method == 'POST':
        empresa = get_object_or_404(Empresa, pk=pk)
        try:
            dias = int(request.POST.get('dias', 3))
        except ValueError:
            dias = 3

        agora = timezone.now()
        if empresa.trial_fim and empresa.trial_fim > agora:
            empresa.trial_fim += timedelta(days=dias)
        else:
            empresa.trial_fim = agora + timedelta(days=dias)

        empresa.status_assinatura = 'TRIAL'
        empresa.ativo = True
        empresa.save(update_fields=['trial_fim', 'status_assinatura', 'ativo'])
        messages.success(request, f"Período de testes da empresa '{empresa.nome}' prorrogado em +{dias} dias!")

    return redirect('painel_superadmin_assinaturas')


@login_required
def ativar_assinatura_superadmin(request, pk):
    if not request.user.is_superuser:
        raise Http404("Acesso restrito.")
    if request.method == 'POST':
        empresa = get_object_or_404(Empresa, pk=pk)
        try:
            dias = int(request.POST.get('dias', 30))
        except ValueError:
            dias = 30

        processar_aprovacao_assinatura(
            empresa=empresa,
            metodo='MANUAL_ADMIN',
            valor=Decimal('0.00'),
            dias=dias,
            observacoes=f"Ativação manual concedida pelo Superadmin {request.user.username}"
        )
        messages.success(request, f"Assinatura da empresa '{empresa.nome}' ativada com sucesso por +{dias} dias!")

    return redirect('painel_superadmin_assinaturas')


@login_required
def toggle_bloqueio_empresa_superadmin(request, pk):
    if not request.user.is_superuser:
        raise Http404("Acesso restrito.")
    if request.method == 'POST':
        empresa = get_object_or_404(Empresa, pk=pk)
        empresa.ativo = not empresa.ativo
        empresa.save(update_fields=['ativo'])
        status_txt = "desbloqueada e liberada" if empresa.ativo else "bloqueada com sucesso"
        messages.success(request, f"Empresa '{empresa.nome}' {status_txt}.")

    return redirect('painel_superadmin_assinaturas')


@login_required
def salvar_order_id_pagamento_superadmin(request, pk):
    """
    Permite ao Superadmin salvar ou atualizar manualmente o Order ID completo do Mercado Pago
    (ex: ORDTST01M3A2C8WFYB52ARVXW4G3Y6D5) diretamente na tabela de transações de assinatura.
    """
    if not request.user.is_superuser:
        raise Http404("Acesso restrito.")
    if request.method == 'POST':
        pagamento = get_object_or_404(PagamentoAssinatura, pk=pk)
        order_id = request.POST.get('order_id', '').strip()
        if order_id:
            pagamento.mp_order_id = order_id
            pagamento.save(update_fields=['mp_order_id'])

            # Se a transação estiver pendente e o Mercado Pago estiver configurado,
            # verifica se já foi aprovada/paga na API de Orders do Mercado Pago
            if pagamento.status == 'PENDENTE' and is_mercadopago_configured():
                dados = consultar_order_mp(order_id)
                if dados and dados.get('status') in ('closed', 'processed', 'paid', 'approved'):
                    real_pay_id = order_id
                    if dados.get('transactions', {}).get('payments'):
                        first_pay = dados['transactions']['payments'][0]
                        real_pay_id = str(first_pay.get('reference_id') or first_pay.get('id') or order_id)
                    processar_aprovacao_assinatura(
                        empresa=pagamento.empresa,
                        payment_id=real_pay_id,
                        preference_id=order_id,
                        order_id=order_id,
                        metodo='MERCADO_PAGO',
                        valor=pagamento.valor,
                        dias=pagamento.dias_concedidos,
                        observacoes=f"Aprovado após vínculo manual do Order ID {order_id}"
                    )
                    messages.success(request, f"Order ID '{order_id}' salvo e pagamento APROVADO com sucesso via Mercado Pago!")
                    return redirect('painel_superadmin_assinaturas')

            messages.success(request, f"Order ID '{order_id}' salvo com sucesso para a transação #{pagamento.id} ({pagamento.empresa.nome})!")
        else:
            pagamento.mp_order_id = None
            pagamento.save(update_fields=['mp_order_id'])
            messages.info(request, f"Order ID removido da transação #{pagamento.id}.")

    return redirect('painel_superadmin_assinaturas')


@login_required
def executar_migracoes_superadmin(request):
    """
    Permite ao Superadministrador disparar o comando 'python manage.py migrate'
    diretamente pelo painel web com relatório visual detalhado em formato de console/terminal.
    Crucial em plataformas serverless (como Vercel) onde não existe terminal SSH
    e migrações de banco não são executadas automaticamente no deploy.
    """
    if not request.user.is_superuser:
        raise Http404("Acesso restrito ao Superadministrador.")

    import io
    from django.core.management import call_command

    out = io.StringIO()
    err = io.StringIO()
    sucesso = True

    try:
        call_command('migrate', interactive=False, stdout=out, stderr=err)
        output_texto = out.getvalue()
        if not output_texto.strip():
            output_texto = "Nenhuma migração pendente. O banco de dados já está 100% atualizado."
        messages.success(request, "Migrações do banco de dados verificadas e aplicadas com sucesso!")
    except Exception as e:
        sucesso = False
        output_texto = f"Erro durante a execução de 'manage.py migrate':\n{e}\n{err.getvalue()}"
        messages.error(request, f"Falha ao aplicar migrações: {e}")

    contexto = {
        'sucesso': sucesso,
        'output': output_texto,
    }
    return render(request, 'estoque/superadmin_migracoes.html', contexto)
