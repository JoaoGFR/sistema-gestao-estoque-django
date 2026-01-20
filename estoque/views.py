from django.shortcuts import render, redirect, get_object_or_404
from .forms import ProdutoForm
from .models import Produto
from django.contrib.auth.decorators import login_required
from .models import Produto, Emprestimo, SaidaEstoque
from .forms import ProdutoForm, EmprestimoForm, SaidaEstoqueForm
from django.utils import timezone

@login_required
def lista_produtos(request):
    query = request.GET.get('q')
    
    # 1. Começamos com TODOS os produtos
    produtos_base = Produto.objects.all()
    
    # 2. Se tiver busca, filtramos a base primeiro
    if query:
        produtos_base = produtos_base.filter(nome__icontains=query)
    
    # 3. Agora dividimos em duas listas baseadas na Categoria
    # 'PECA' vai para um lado
    pecas = produtos_base.filter(categoria='PECA')
    
    # 'FERRA' (Ferramenta) e 'EQUIP' (Equipamento) vão para o outro
    ferramentas = produtos_base.filter(categoria__in=['FERRA', 'EQUIP'])
    
    # 4. Enviamos as duas listas separadas para o HTML
    contexto = {
        'pecas': pecas,
        'ferramentas': ferramentas,
        'query': query # Para manter o texto na barra de busca
    }
    
    return render(request, 'estoque/lista_produtos.html', contexto)

@login_required
def criar_produto(request):
    if request.method == 'POST':
        # Se o usuário clicou em "Salvar", preenchemos o formulário com os dados
        form = ProdutoForm(request.POST)
        if form.is_valid():
            form.save() # Salva no banco
            return redirect('lista_produtos') # Volta para a lista
    else:
        # Se o usuário só abriu a página, mostramos o formulário vazio
        form = ProdutoForm()

    return render(request, 'estoque/criar_produto.html', {'form': form})

@login_required
def editar_produto(request, pk):
    # 'pk' é a Primary Key (o ID do produto no banco)
    produto = get_object_or_404(Produto, pk=pk)

    if request.method == 'POST':
        # Carregamos o formulário COM os dados desse produto específico
        form = ProdutoForm(request.POST, instance=produto)
        if form.is_valid():
            form.save()
            return redirect('lista_produtos')
    else:
        # Mostramos o formulário preenchido para edição
        form = ProdutoForm(instance=produto)

    return render(request, 'estoque/criar_produto.html', {'form': form})

@login_required
def excluir_produto(request, pk):
    produto = get_object_or_404(Produto, pk=pk)
    
    if request.method == 'POST':
        produto.delete()
        return redirect('lista_produtos')
    
    # Pergunta de confirmação antes de apagar
    return render(request, 'estoque/confirmar_exclusao.html', {'produto': produto})

@login_required
def lista_emprestimos(request):
    # Mostra primeiro os que NÃO foram devolvidos
    emprestimos = Emprestimo.objects.all().order_by('devolvido', '-data_saida')
    return render(request, 'estoque/lista_emprestimos.html', {'emprestimos': emprestimos})

@login_required
def registrar_emprestimo(request):
    if request.method == 'POST':
        form = EmprestimoForm(request.POST)
        if form.is_valid():
            emprestimo = form.save(commit=False)
            
            # --- NOVO ---
            # Preenche automaticamente quem está logado
            emprestimo.responsavel_saida = request.user 
            # ------------

            produto = emprestimo.produto
            produto.quantidade -= 1
            produto.save()
            
            emprestimo.save()
            return redirect('lista_emprestimos')
    else:
        form = EmprestimoForm()
    
    return render(request, 'estoque/form_emprestimo.html', {'form': form})

@login_required
def devolver_ferramenta(request, pk):
    emprestimo = get_object_or_404(Emprestimo, pk=pk)
    
    if not emprestimo.devolvido:
        emprestimo.devolvido = True
        emprestimo.data_devolucao = timezone.now()
        
        # --- NOVO ---
        # Registra quem clicou no botão de devolver
        emprestimo.responsavel_devolucao = request.user
        # ------------
        
        emprestimo.save()
        
        produto = emprestimo.produto
        produto.quantidade += 1
        produto.save()
        
    return redirect('lista_emprestimos')

@login_required
def lista_saidas(request):
    # Mostra as últimas saídas primeiro (-data)
    saidas = SaidaEstoque.objects.all().order_by('-data')
    return render(request, 'estoque/lista_saidas.html', {'saidas': saidas})

@login_required
def registrar_saida(request):
    error_message = None

    if request.method == 'POST':
        form = SaidaEstoqueForm(request.POST)
        if form.is_valid():
            saida = form.save(commit=False)
            
            # --- VERIFICAÇÃO DE SALDO ---
            produto = saida.produto
            if produto.quantidade >= saida.quantidade:
                # 1. Diminui o estoque
                produto.quantidade -= saida.quantidade
                produto.save()
                
                # 2. Registra quem fez (usuário logado) e salva
                saida.usuario = request.user
                saida.save()
                return redirect('lista_saidas')
            else:
                # Erro se tentar tirar mais do que tem
                error_message = f"Erro: Saldo insuficiente! Estoque atual: {produto.quantidade}"
    else:
        form = SaidaEstoqueForm()
    
    return render(request, 'estoque/form_saida.html', {'form': form, 'error_message': error_message})