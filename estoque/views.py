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

# Seus models e forms
from .models import Produto, Emprestimo, SaidaEstoque, Empresa, UserProfile, Lote
from .forms import ProdutoForm, EmprestimoForm, SaidaEstoqueForm, CadastroSaaSForm, FuncionarioForm, LoteForm

# ... (o resto do arquivo continua igual) ...
# --- FUNÇÕES AUXILIARES ---
def get_empresa_usuario(user):
    try:
        return user.userprofile.empresa
    except ObjectDoesNotExist:
        return None

# --- VIEWS PÚBLICAS ---
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

# --- DASHBOARD (CORRIGIDA) ---
@login_required
def dashboard(request):
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        # Se não tiver empresa, renderiza zerado para não dar erro
        return render(request, 'estoque/dashboard.html', {
            'total_produtos': 0, 
            'total_categorias': 0, 
            'estoque_baixo': 0, 
            'emprestimos_pendentes': 0, 
            'ultimas_saidas': [],
            'valor_total_estoque': 0, 
            'lotes_vencendo': [] 
        })
    
    # 1. TOTAIS GERAIS (Correção do erro 'PECA' aqui)
    # Não filtramos mais por nome fixo, pegamos o total da empresa
    total_produtos = Produto.objects.filter(empresa=empresa).count()
    
    # Contamos quantas categorias diferentes você criou
    total_categorias = Categoria.objects.filter(empresa=empresa).count()
    
    # 2. FINANCEIRO
    # Soma (Quantidade Atual * Preço de Compra) direto na tabela de Lotes
    soma_valor = Lote.objects.filter(
        produto__empresa=empresa, 
        status='ATIVO'
    ).aggregate(
        total=Sum(F('quantidade_atual') * F('preco_compra'))
    )['total']
    
    valor_total_estoque = soma_valor if soma_valor else 0

    # 3. ALERTAS DE ESTOQUE BAIXO
    # Anota a quantidade real e compara com o mínimo
    produtos_anotados = Produto.objects.filter(empresa=empresa).annotate(
        qtd_real=Coalesce(Sum('lotes__quantidade_atual', filter=Q(lotes__status='ATIVO')), 0)
    )
    
    # Removemos o filtro categoria='PECA' para pegar QUALQUER item baixo
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
    ).order_by('-data')[:5]

    # 6. VENCIMENTOS PRÓXIMOS (30 DIAS)
    hoje = timezone.now().date()
    daqui_30_dias = hoje + timedelta(days=30)
    lotes_vencendo = Lote.objects.filter(
        produto__empresa=empresa,
        status='ATIVO',
        quantidade_atual__gt=0,
        data_validade__range=[hoje, daqui_30_dias] 
    ).order_by('data_validade')

    contexto = {
        'total_produtos': total_produtos,     # Mudamos de 'total_pecas' para 'total_produtos'
        'total_categorias': total_categorias, # Nova métrica
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
    
    # Parâmetros da URL (Busca e Filtros)
    query = request.GET.get('q')
    filtro_critico = request.GET.get('filtro')
    categoria_id = request.GET.get('categoria') # Novo filtro por categoria

    # 1. Query Base (Traz todos os produtos da empresa)
    produtos = Produto.objects.filter(empresa=empresa)

    # 2. Anota a Quantidade Real (Soma dos Lotes Ativos)
    # Isso é necessário para saber o saldo antes de filtrar
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
    
    # Busca todas categorias para montar o filtro no HTML
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
        # MUDANÇA AQUI: Passamos 'request.user' antes do 'request.POST'
        form = ProdutoForm(request.user, request.POST)
        if form.is_valid():
            produto = form.save(commit=False)
            produto.empresa = empresa
            produto.save()
            messages.success(request, 'Produto cadastrado! Agora adicione um Lote para incluir estoque.')
            return redirect('lista_produtos')
    else:
        # MUDANÇA AQUI: Passamos 'request.user' aqui também
        form = ProdutoForm(request.user)
        
    return render(request, 'estoque/criar_produto.html', {'form': form})

@login_required
def editar_produto(request, pk):
    empresa = get_empresa_usuario(request.user)
    produto = get_object_or_404(Produto, pk=pk, empresa=empresa)
    
    if request.method == 'POST':
        # MUDANÇA AQUI: Passamos 'request.user' + POST + instance
        form = ProdutoForm(request.user, request.POST, instance=produto)
        if form.is_valid():
            form.save()
            messages.success(request, 'Produto atualizado!')
            return redirect('lista_produtos')
    else:
        # MUDANÇA AQUI: Passamos 'request.user' + instance
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
            # Qtd atual nasce igual a inicial
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
        # Passamos 'user' para o form filtrar os querysets corretamente
        form = SaidaEstoqueForm(user=request.user, data=request.POST)
        
        if form.is_valid():
            produto = form.cleaned_data['produto']
            qtd_solicitada = form.cleaned_data['quantidade']
            motivo = form.cleaned_data['motivo']
            lote_escolhido = form.cleaned_data['lote_especifico'] # Campo novo
            
            # Verificação de Segurança básica
            if produto.empresa != empresa:
                return redirect('lista_produtos')

            # --- CENÁRIO 1: BAIXA MANUAL (Lote Específico) ---
            if lote_escolhido:
                if lote_escolhido.quantidade_atual < qtd_solicitada:
                    error_message = f"O Lote {lote_escolhido.numero_lote} só tem {lote_escolhido.quantidade_atual} unidades. Você pediu {qtd_solicitada}."
                else:
                    lote_escolhido.quantidade_atual -= qtd_solicitada
                    lote_escolhido.save() # O save() já atualiza status se zerar
                    
                    # Registra Saída
                    SaidaEstoque.objects.create(
                        produto=produto,
                        quantidade=qtd_solicitada,
                        motivo=f"{motivo} (Lote Manual: {lote_escolhido.numero_lote})",
                        usuario=request.user
                    )
                    messages.success(request, f"Saída manual do lote {lote_escolhido.numero_lote} realizada!")
                    return redirect('lista_saidas')

            # --- CENÁRIO 2: BAIXA AUTOMÁTICA (FEFO/FIFO) ---
            else:
                # Verifica saldo total antes de tentar baixar
                if produto.saldo_total < qtd_solicitada:
                    error_message = f"Saldo Insuficiente! Total disponível: {produto.saldo_total}"
                else:
                    # Busca lotes ativos, ordenados por Validade (FEFO) e depois Data Entrada (FIFO)
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
                        usuario=request.user
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
            emprestimo = form.save(commit=False)
            produto = emprestimo.produto
            
            # 1. VALIDAÇÃO DE ESTOQUE
            # Busca lotes ativos com saldo > 0, do mais antigo para o mais novo (FIFO)
            lote_disponivel = Lote.objects.filter(
                produto=produto, 
                status='ATIVO', 
                quantidade_atual__gt=0
            ).order_by('data_entrada').first()

            if not lote_disponivel:
                messages.error(request, f"Erro: O produto '{produto.nome}' não tem estoque disponível para empréstimo.")
            else:
                # 2. BAIXA NO ESTOQUE
                lote_disponivel.quantidade_atual -= 1
                lote_disponivel.save()
                
                # 3. SALVA O EMPRÉSTIMO VINCULADO AO LOTE
                emprestimo.lote = lote_disponivel
                emprestimo.responsavel_saida = request.user
                emprestimo.save()
                
                messages.success(request, f"Empréstimo registrado para {emprestimo.solicitante}!")
                return redirect('lista_emprestimos')
    else:
        form = EmprestimoForm(request.user)

    # Passamos produtos com ID da categoria para o template fazer a mágica do JS
    produtos_data = list(Produto.objects.filter(empresa=empresa).values('id', 'nome', 'categoria_id'))
    import json
    produtos_json = json.dumps(produtos_data)

    return render(request, 'estoque/registrar_emprestimo.html', {
        'form': form, 
        'produtos_json': produtos_json
    })

@login_required
def lista_emprestimos(request):
    empresa = get_empresa_usuario(request.user)
    emprestimos = Emprestimo.objects.filter(produto__empresa=empresa, devolvido=False)
    return render(request, 'estoque/lista_emprestimos.html', {'emprestimos': emprestimos})

@login_required
@transaction.atomic
def devolver_item(request, pk):
    emprestimo = get_object_or_404(Emprestimo, pk=pk)
    
    if request.method == 'POST':
        if not emprestimo.devolvido:
            # 1. DEVOLVE AO ESTOQUE (No lote original que saiu)
            if emprestimo.lote:
                lote = emprestimo.lote
                lote.quantidade_atual += 1
                # Se o lote estava esgotado, reativa ele
                if lote.status == 'ESGOTADO':
                    lote.status = 'ATIVO'
                lote.save()
            
            # 2. MARCA COMO DEVOLVIDO
            emprestimo.devolvido = True
            emprestimo.data_devolucao = timezone.now()
            emprestimo.responsavel_devolucao = request.user
            emprestimo.save()
            
            messages.success(request, "Item devolvido com sucesso!")
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

    # Cria o "Slug" da empresa (ex: "Oficina do Zé" -> "oficinadoze")
    # Removemos hífens para ficar mais curto: "oficinadoze"
    prefixo_empresa = slugify(empresa.nome).replace('-', '')

    if request.method == 'POST':
        form = FuncionarioForm(request.POST)
        if form.is_valid():
            # 1. Pega os dados sem salvar ainda
            user = form.save(commit=False)
            
            # 2. Captura o sufixo que o usuário digitou (ex: "maria")
            sufixo = form.cleaned_data['username'].lower()
            
            # 3. Gera o Login Final (ex: "oficinadoze.maria")
            login_final = f"{prefixo_empresa}.{sufixo}"
            
            # 4. Verifica se esse login COMBINADO já existe
            if User.objects.filter(username=login_final).exists():
                form.add_error('username', f"O usuário '{login_final}' já existe nesta empresa.")
            else:
                # 5. Salva o usuário com o novo login
                user.username = login_final
                user.set_password(form.cleaned_data['password'])
                user.save()
                
                # 6. Cria o perfil vinculado
                UserProfile.objects.create(user=user, empresa=empresa, e_dono=False)
                
                messages.success(request, f"Funcionário criado! Login de acesso: {login_final}")
                return redirect('lista_funcionarios')
    else:
        form = FuncionarioForm()

    return render(request, 'estoque/criar_funcionario.html', {
        'form': form,
        'prefixo': prefixo_empresa # Passamos o prefixo para mostrar na tela
    })

@login_required
def historico_produto(request, pk):
    empresa = get_empresa_usuario(request.user)
    produto = get_object_or_404(Produto, pk=pk, empresa=empresa)
    
    # Busca todas as entradas (Lotes) desse produto, do mais antigo para o novo
    lotes = Lote.objects.filter(produto=produto).order_by('data_entrada')
    
    # Prepara dados para o Gráfico (Eixo X = Data, Eixo Y = Preço)
    datas = [lote.data_entrada.strftime("%d/%m/%Y") for lote in lotes]
    precos = [float(lote.preco_compra) for lote in lotes]
    
    # Converte para JSON para o Javascript ler
    datas_json = json.dumps(datas, cls=DjangoJSONEncoder)
    precos_json = json.dumps(precos, cls=DjangoJSONEncoder)
    
    # Pega também as saídas para mostrar movimentação completa
    saidas = SaidaEstoque.objects.filter(produto=produto).order_by('-data')

    context = {
        'produto': produto,
        'lotes': lotes.order_by('-data_entrada'), # Na tabela mostramos o mais recente primeiro
        'saidas': saidas,
        'datas_json': datas_json,
        'precos_json': precos_json,
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
    
# ... (outros imports) ...

@login_required
def api_lotes_produto(request, pk):
    """Retorna os lotes ativos de um produto para o dropdown"""
    empresa = get_empresa_usuario(request.user)
    lotes = Lote.objects.filter(
        produto_id=pk, 
        produto__empresa=empresa, 
        status='ATIVO', 
        quantidade_atual__gt=0
    ).order_by('data_validade', 'data_entrada') # Ordena pelo que deve sair primeiro
    
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
            # Cria a categoria vinculada à empresa
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
    # 1. Segurança: Só o Dono pode editar
    if not request.user.userprofile.e_dono:
        messages.error(request, "Apenas administradores podem editar lançamentos passados.")
        return redirect('lista_lotes')

    # 2. Busca o Lote
    lote = get_object_or_404(Lote, pk=pk)
    empresa = get_empresa_usuario(request.user)
    
    # Garante que o lote é da empresa dele
    if lote.produto.empresa != empresa:
        return redirect('lista_lotes')

    # Guardamos a quantidade inicial "velha" para calcular a diferença depois
    qtd_inicial_antiga = lote.quantidade_inicial

    if request.method == 'POST':
        form = LoteForm(request.user, request.POST, request.FILES, instance=lote)
        
        if form.is_valid():
            lote_editado = form.save(commit=False)
            
            # 3. CÁLCULO DE AJUSTE DE ESTOQUE
            # Se ele mudou a quantidade inicial (ex: de 10 para 12), a diferença é +2
            diferenca = lote_editado.quantidade_inicial - qtd_inicial_antiga
            
            # Aplica a diferença no saldo atual
            nova_qtd_atual = lote_editado.quantidade_atual + diferenca
            
            # 4. Validação: Não permitir que o estoque fique negativo
            # (Ex: Comprou 10, vendeu 8, sobram 2. Se tentar editar inicial para 5, sobra -3. Isso não pode.)
            if nova_qtd_atual < 0:
                messages.error(request, f"Não é possível reduzir tanto a quantidade. Já foram vendidos itens deste lote. O mínimo aceitável seria {qtd_inicial_antiga - lote_editado.quantidade_atual}.")
            else:
                lote_editado.quantidade_atual = nova_qtd_atual
                lote_editado.save()
                messages.success(request, "Lote atualizado com sucesso! O estoque foi recalculado.")
                return redirect('lista_lotes')
                
    else:
        form = LoteForm(request.user, instance=lote)
        
        # Bloqueia a edição do Produto para não quebrar o histórico
        # (Não faz sentido transformar um lote de Leite em um lote de Parafuso depois de criado)
        form.fields['produto'].disabled = True 

    return render(request, 'estoque/editar_lote.html', {'form': form, 'lote': lote})