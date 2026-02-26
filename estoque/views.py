from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout
from django.contrib.auth.models import User 
from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Sum, F, Q, Case, When, IntegerField
from django.db.models.functions import Coalesce
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
from django.http import JsonResponse
from django.utils.text import slugify
from .models import Produto, Emprestimo, SaidaEstoque, Empresa, UserProfile, Lote, Categoria, Localizacao
from django.core.paginator import Paginator
from django.db.models.functions import Coalesce
from django.db import transaction
import json
from django.core.serializers.json import DjangoJSONEncoder
from datetime import timedelta, datetime
from itertools import chain
from operator import attrgetter
from .models import Produto, Emprestimo, SaidaEstoque, Empresa, UserProfile, Lote
from .forms import ProdutoForm, EmprestimoForm, SaidaEstoqueForm, CadastroSaaSForm, FuncionarioForm, LoteForm



def get_empresa_usuario(user):
    try:
        return user.userprofile.empresa
    except ObjectDoesNotExist:
        return None


def landing_page(request):
    return render(request, 'estoque/landing.html')

def cadastro_saas(request):
    if request.method == 'POST':
        form = CadastroSaaSForm(request.POST)
        if form.is_valid():
            nova_empresa = Empresa.objects.create(
                nome=form.cleaned_data['nome_empresa'],
                cnpj=None,   
                ativo=True
            )
            novo_usuario = User.objects.create_user(
                username=form.cleaned_data['email'],
                email=form.cleaned_data['email'],
                password=form.cleaned_data['senha'],
                first_name=form.cleaned_data['nome_completo']
            )
            UserProfile.objects.create(
                user=novo_usuario,
                empresa=nova_empresa,
                e_dono=True
            )
            login(request, novo_usuario)
            messages.success(request, f"Bem-vindo, {novo_usuario.first_name}! Sua conta foi criada.")
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
            'valor_total_estoque': 0, 
            'lotes_vencendo': [] 
        })
    
    # 1. TOTAIS
    total_produtos = Produto.objects.filter(empresa=empresa).count()
    total_categorias = Categoria.objects.filter(empresa=empresa).count()
    
    # 2. FINANCEIRO
    soma_valor = Lote.objects.filter(
        produto__empresa=empresa, 
        status='ATIVO'
    ).aggregate(
        total=Sum(F('quantidade_atual') * F('preco_compra'))
    )['total']
    valor_total_estoque = soma_valor if soma_valor else 0

    # 3. ALERTAS DE ESTOQUE BAIXO
    produtos_anotados = Produto.objects.filter(empresa=empresa).annotate(
        qtd_real=Coalesce(Sum('lotes__quantidade_atual', filter=Q(lotes__status='ATIVO')), 0)
    )
    estoque_baixo = produtos_anotados.filter(
        qtd_real__lt=F('estoque_minimo')
    ).count()
    
    # 4. EMPRÉSTIMOS PENDENTES
    emprestimos_pendentes = Emprestimo.objects.filter(
        produto__empresa=empresa, 
        devolvido=False
    ).count()
    
    # 5. ÚLTIMAS MOVIMENTAÇÕES
    ultimas_saidas = SaidaEstoque.objects.filter(
        produto__empresa=empresa
    ).select_related('produto').order_by('-data')[:5] 

    # 6. VENCIMENTOS PRÓXIMOS
    hoje = timezone.now().date()
    daqui_30_dias = hoje + timedelta(days=30)
    lotes_vencendo = Lote.objects.filter(
        produto__empresa=empresa,
        status='ATIVO',
        quantidade_atual__gt=0,
        data_validade__range=[hoje, daqui_30_dias] 
    ).select_related('produto').order_by('data_validade')

    contexto = {
        'total_produtos': total_produtos,
        'total_categorias': total_categorias,
        'estoque_baixo': estoque_baixo,
        'emprestimos_pendentes': emprestimos_pendentes,
        'ultimas_saidas': ultimas_saidas,
        'valor_total_estoque': valor_total_estoque,
        'lotes_vencendo': lotes_vencendo, 
    }
    return render(request, 'estoque/dashboard.html', contexto)

# --- PRODUTOS ---
@login_required
def lista_produtos(request):
    empresa = get_empresa_usuario(request.user)
    
    # Parâmetros da URL 
    query = request.GET.get('q')
    filtro_critico = request.GET.get('filtro')
    categoria_id = request.GET.get('categoria')

    # 1. Query Base 
    produtos = Produto.objects.filter(empresa=empresa)

    # 2. Anota a Quantidade Real (Soma dos Lotes Ativos)
   
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
        produtos = produtos.filter(qtd_real__lt=F('estoque_minimo'))

    # 4. Ordenação
    produtos = produtos.order_by('nome')

    # 5. Paginação (10 itens por página)
    paginator = Paginator(produtos, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
   
    categorias = Categoria.objects.filter(empresa=empresa)

    return render(request, 'estoque/lista_produtos.html', {
        'page_obj': page_obj,
        'query': query,
        'filtro_critico': filtro_critico,
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
            messages.success(request, 'Produto cadastrado! Agora adicione um Lote para incluir estoque.')
            return redirect('lista_produtos')
    else:
        form = ProdutoForm(request.user)
        
    return render(request, 'estoque/criar_produto.html', {'form': form})

@login_required
def editar_produto(request, pk):
    empresa = get_empresa_usuario(request.user)
    produto = get_object_or_404(Produto, pk=pk, empresa=empresa)
    
    if request.method == 'POST':
        
        form = ProdutoForm(request.user, request.POST, instance=produto)
        if form.is_valid():
            form.save()
            messages.success(request, 'Produto atualizado!')
            return redirect('lista_produtos')
    else:
        form = ProdutoForm(request.user, instance=produto)
        
    return render(request, 'estoque/criar_produto.html', {'form': form})

@login_required
def excluir_produto(request, pk):
    empresa = get_empresa_usuario(request.user)
    produto = get_object_or_404(Produto, pk=pk, empresa=empresa)
    if request.method == 'POST':
        produto.delete()
        messages.success(request, 'Produto excluído.')
        return redirect('lista_produtos')
    return render(request, 'estoque/confirmar_exclusao.html', {'item': produto})

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
    return render(request, 'estoque/entrada_estoque.html', {'form': form})

# --- SAÍDAS (FEFO) ---
@login_required
@transaction.atomic
def registrar_saida(request):
    empresa = get_empresa_usuario(request.user)
    error_message = None

    if request.method == 'POST':
        
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
                if lote_escolhido.quantidade_atual < qtd_solicitada:
                    error_message = f"O Lote {lote_escolhido.numero_lote} só tem {lote_escolhido.quantidade_atual} unidades. Você pediu {qtd_solicitada}."
                else:
                    lote_escolhido.quantidade_atual -= qtd_solicitada
                    lote_escolhido.save() 
                    
                    # Registra Saída
                    SaidaEstoque.objects.create(
                        produto=produto,
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
                    lotes = Lote.objects.filter(
                        produto=produto, 
                        status='ATIVO', 
                        quantidade_atual__gt=0
                    ).order_by('data_validade', 'data_entrada')

                    qtd_restante = qtd_solicitada
                    lotes_afetados = []

                    for lote in lotes:
                        if qtd_restante <= 0: break
                        
                        qtd_retirar = min(qtd_restante, lote.quantidade_atual)
                        lote.quantidade_atual -= qtd_retirar
                        lote.save()
                        
                        qtd_restante -= qtd_retirar
                        lotes_afetados.append(lote.numero_lote)

                    SaidaEstoque.objects.create(
                        produto=produto,
                        quantidade=qtd_solicitada,
                        motivo=f"{motivo} (Auto: {', '.join(lotes_afetados)})",
                        usuario=request.user,
                        
                        
                        valor_venda=valor_venda
                    )
                    messages.success(request, f"Saída automática realizada com sucesso (Lotes: {', '.join(lotes_afetados)}).")
                    return redirect('lista_saidas')
    else:
        form = SaidaEstoqueForm(user=request.user)
    
    return render(request, 'estoque/form_saida.html', {'form': form, 'error_message': error_message})

@login_required
def lista_saidas(request):
    empresa = get_empresa_usuario(request.user)
    saidas = SaidaEstoque.objects.filter(produto__empresa=empresa).order_by('-data')
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
                # 2. ALGORITMO FIFO
                lotes_disponiveis = Lote.objects.filter(
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

    produtos_data = list(Produto.objects.filter(empresa=empresa).values('id', 'nome', 'categoria_id'))
    import json
    produtos_json = json.dumps(produtos_data, default=str)

    return render(request, 'estoque/registrar_emprestimo.html', {
        'form': form, 
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
    emprestimo = get_object_or_404(Emprestimo, pk=pk)
    
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
def historico_produto(request, pk):
    empresa = get_empresa_usuario(request.user)
    produto = get_object_or_404(Produto, pk=pk, empresa=empresa)
    lotes = Lote.objects.filter(produto=produto).order_by('data_entrada')
    dados_compra = [
        {
            'x': lote.data_entrada.strftime("%Y-%m-%d"), 
            'x_display': lote.data_entrada.strftime("%d/%m/%Y"), 
            'y': float(lote.preco_compra)
        } 
        for lote in lotes
    ]
    
    saidas_com_valor = SaidaEstoque.objects.filter(
        produto=produto, 
        valor_venda__isnull=False
    ).order_by('data')
    
    dados_venda = [
        {
            'x': s.data.strftime("%Y-%m-%d"), 
            'x_display': s.data.strftime("%d/%m/%Y"),
            'y': float(s.valor_venda)
        } 
        for s in saidas_com_valor
    ]
    saidas = SaidaEstoque.objects.filter(produto=produto).order_by('-data')
    context = {
        'produto': produto,
        'lotes': lotes.order_by('-data_entrada'),
        'saidas': saidas,
        
        # Enviamos os objetos completos agora
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
            'unidade': produto.unidade
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
    lote = get_object_or_404(Lote, pk=pk)
    empresa = get_empresa_usuario(request.user)

    if lote.produto.empresa != empresa:
        return redirect('lista_lotes')


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
        
       
        form.fields['produto'].disabled = True 

    return render(request, 'estoque/editar_lote.html', {'form': form, 'lote': lote})

@login_required
def relatorios_gerais(request):
    
    return render(request, 'estoque/relatorios_index.html')

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
def relatorio_movimentacoes(request):
    empresa = get_empresa_usuario(request.user)
    
   
    data_inicio = request.GET.get('data_inicio')
    data_fim = request.GET.get('data_fim')
    
    if not data_inicio:
        data_inicio = (timezone.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    if not data_fim:
        data_fim = timezone.now().strftime('%Y-%m-%d')

    dt_ini = datetime.strptime(data_inicio, '%Y-%m-%d')
    dt_fim = datetime.strptime(data_fim, '%Y-%m-%d').replace(hour=23, minute=59, second=59)

    
    entradas = Lote.objects.filter(
        produto__empresa=empresa,
        data_entrada__range=(dt_ini, dt_fim)
    )
    
    saidas = SaidaEstoque.objects.filter(
        produto__empresa=empresa,
        data__range=(dt_ini, dt_fim) 
    )
    
    emprestimos = Emprestimo.objects.filter(
        produto__empresa=empresa,
        data_saida__range=(dt_ini, dt_fim)
    )

    
    lista_movimentacoes = []

    for item in entradas:
        item.tipo_movimento = 'ENTRADA'
        item.data_evento = item.data_entrada
        if hasattr(item, 'usuario_criacao') and item.usuario_criacao:
            item.responsavel = item.usuario_criacao.username
        else:
            item.responsavel = 'Sistema'
        lista_movimentacoes.append(item)

    for item in saidas:
        item.tipo_movimento = 'SAIDA'
        item.data_evento = item.data 
        item.responsavel = item.usuario.username
        lista_movimentacoes.append(item)

    for item in emprestimos:
        item.tipo_movimento = 'EMPRESTIMO'
        item.data_evento = item.data_saida
        item.responsavel = item.responsavel_saida.username
        lista_movimentacoes.append(item)

    lista_movimentacoes.sort(key=lambda x: x.data_evento, reverse=True)

    return render(request, 'estoque/relatorio_movimentacoes.html', {
        'movimentacoes': lista_movimentacoes,
        'data_inicio': data_inicio,
        'data_fim': data_fim,
        'empresa': empresa  
    })