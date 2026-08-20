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
from .models import Produto, Emprestimo, SaidaEstoque, Empresa, UserProfile, Lote, Categoria, Localizacao, AliquotaImposto, SimulacaoPreco
from django.core.paginator import Paginator
from django.db.models.functions import Coalesce
from django.db import transaction
import json
from django.core.serializers.json import DjangoJSONEncoder
from datetime import timedelta, datetime
from itertools import chain
from operator import attrgetter
from django.db.models import ProtectedError
from .models import Produto, Emprestimo, SaidaEstoque, Empresa, UserProfile, Lote
from .forms import ProdutoForm, EmprestimoForm, SaidaEstoqueForm, CadastroSaaSForm, FuncionarioForm, LoteForm, AliquotaImpostoForm
import os
from django.conf import settings
from django.core.management import call_command
from django.http import FileResponse, Http404
from django.contrib import messages
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required


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
    daqui_180_dias = hoje + timedelta(days=180)
    lotes_vencendo = Lote.objects.filter(
        produto__empresa=empresa,
        status='ATIVO',
        quantidade_atual__gt=0,
        data_validade__range=[hoje, daqui_180_dias] 
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

   
    produtos = Produto.objects.filter(empresa=empresa)

   
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

            # -----------------------------------------------------------------
            # FLUXO 1: SAÍDA MANUAL (LOTE ESPECÍFICO)
            # -----------------------------------------------------------------
            if lote_escolhido:
                if lote_escolhido.produto != produto:
                    error_message = "O lote selecionado não pertence ao produto informado."
                elif lote_escolhido.quantidade_atual < qtd_solicitada:
                    error_message = f"O Lote {lote_escolhido.numero_lote} só tem {lote_escolhido.quantidade_atual} unidades. Você pediu {qtd_solicitada}."
                else:
                    lote_escolhido.quantidade_atual -= qtd_solicitada
                    lote_escolhido.save() 
                    
                    # Registra a Saída vinculando o lote escolhido
                    SaidaEstoque.objects.create(
                        produto=produto,
                        lote=lote_escolhido,  # Vínculo direto gravado com sucesso
                        quantidade=qtd_solicitada,
                        motivo=f"{motivo} (Lote Manual: {lote_escolhido.numero_lote})",
                        usuario=request.user,
                        valor_venda=valor_venda 
                    )
                    messages.success(request, f"Saída manual do lote {lote_escolhido.numero_lote} realizada!")
                    return redirect('lista_saidas')

            # -----------------------------------------------------------------
            # FLUXO 2: SAÍDA AUTOMÁTICA (FIFO/FEFO)
            # -----------------------------------------------------------------
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
                        if qtd_restante <= 0: 
                            break
                        
                        # Calcula quanto vai retirar deste lote específico
                        qtd_retirar = min(qtd_restante, lote.quantidade_atual)
                        
                        lote.quantidade_atual -= qtd_retirar
                        lote.save()
                        
                        # CRUCIAL: Cria um registro de SaidaEstoque exclusivo para ESTE lote
                        SaidaEstoque.objects.create(
                            produto=produto,
                            lote=lote,  # Grava o lote específico da iteração atual
                            quantidade=qtd_retirar,  # Grava apenas a parte retirada deste lote
                            motivo=f"{motivo} (Auto: Lote {lote.numero_lote})",
                            usuario=request.user,
                            valor_venda=valor_venda
                        )
                        
                        qtd_restante -= qtd_retirar
                        lotes_afetados.append(lote.numero_lote)

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

@login_required
def painel_backups(request):
    
    if not request.user.is_superuser:
        messages.error(request, "Acesso restrito ao administrador do sistema.")
        return redirect('dashboard')

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

    return render(request, 'estoque/painel_backups.html', {'arquivos': arquivos})

@login_required
def criar_backup(request):
    if not request.user.is_superuser:
        messages.error(request, "Acesso restrito ao administrador do sistema.")
        return redirect('dashboard')

    # [SEGURANÇA] Apenas aceita POST para evitar disparo acidental via link GET
    if request.method != 'POST':
        return redirect('painel_backups')

    pasta_backups = os.path.join(settings.BASE_DIR, 'backups')
    
    # Gera um nome de arquivo com a data e hora atual
    data_atual = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    nome_arquivo = f"backup_jgtech_{data_atual}.json"
    caminho_arquivo = os.path.join(pasta_backups, nome_arquivo)

    try:
        os.makedirs(pasta_backups, exist_ok=True)
        # Extrai os dados do banco, excluindo tabelas de permissão padrão que causam conflito
        with open(caminho_arquivo, 'w', encoding='utf-8') as f:
            call_command('dumpdata', exclude=['contenttypes', 'auth.Permission'], format='json', indent=4, stdout=f)
        
        messages.success(request, f"Backup '{nome_arquivo}' criado com sucesso!")
    except OSError as e:
        messages.error(request, f"O ambiente serverless não permite gravação de arquivos em disco local ({str(e)}). Utilize os backups automáticos gerenciados do seu banco de dados PostgreSQL.")
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
                messages.success(request, f"O sistema foi restaurado com sucesso usando o arquivo '{os.path.basename(filepath)}'.")
            except Exception as e:
                messages.error(request, f"Erro crítico ao restaurar banco de dados: {str(e)}")
        
    return redirect('painel_backups')


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
    
    aliquota_id = request.GET.get('aliquota_id', '0')
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

    # Alíquota de imposto
    imposto_pct = 0.0
    aliquota_nome = "Sem Impostos"
    if aliquota_id != '0' and aliquota_id != '':
        aliq = get_object_or_404(AliquotaImposto, id=aliquota_id, empresa=empresa)
        imposto_pct = float(aliq.percentual)
        aliquota_nome = aliq.nome

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