from django import forms
from django.contrib.auth.models import User
from .models import Produto, Emprestimo, SaidaEstoque, Lote, UserProfile, Categoria, Localizacao
from django.utils.text import slugify
import re

# --- FORMULÁRIOS AUXILIARES (Para os Modais) ---

class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nome']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Elétrica, Hidráulica...'}),
        }

class LocalizacaoForm(forms.ModelForm):
    class Meta:
        model = Localizacao
        fields = ['nome']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Prateleira B3, Gaveta 2...'}),
        }

# --- FORMULÁRIO PRINCIPAL DE PRODUTO ---

class ProdutoForm(forms.ModelForm):
    class Meta:
        model = Produto
        fields = ['nome', 'sku', 'ean', 'categoria', 'unidade', 'estoque_minimo', 'localizacao', 'controla_lote']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome do item'}),
            'sku': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Código interno'}),
            'ean': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Código de barras'}),
            'categoria': forms.Select(attrs={'class': 'form-select', 'id': 'id_categoria'}),
            'localizacao': forms.Select(attrs={'class': 'form-select', 'id': 'id_localizacao'}),
            'unidade': forms.Select(attrs={'class': 'form-select'}),
            'estoque_minimo': forms.NumberInput(attrs={'class': 'form-control'}),
            'controla_lote': forms.CheckboxInput(attrs={'class': 'form-check-input', 'style': 'width: 20px; height: 20px;'}),
        }

    def __init__(self, user, *args, **kwargs):
        super(ProdutoForm, self).__init__(*args, **kwargs)
        if user and hasattr(user, 'userprofile'):
            empresa = user.userprofile.empresa
            self.fields['categoria'].queryset = Categoria.objects.filter(empresa=empresa)
            self.fields['localizacao'].queryset = Localizacao.objects.filter(empresa=empresa)
        else:
            self.fields['categoria'].queryset = Categoria.objects.none()
            self.fields['localizacao'].queryset = Localizacao.objects.none()

# --- FORMULÁRIO DE LOTE (ENTRADA) ---

class LoteForm(forms.ModelForm):
    class Meta:
        model = Lote
        fields = ['produto', 'numero_lote', 'preco_compra', 'fornecedor', 'data_fabricacao', 'data_validade', 'quantidade_inicial', 'numero_nota_fiscal', 'nota_fiscal']
        widgets = {
            'data_fabricacao': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'data_validade': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'preco_compra': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'nota_fiscal': forms.FileInput(attrs={'class': 'form-control'}),
        }

        labels = {
            'quantidade_inicial': 'Quantidade',
            'preco_compra': 'Preço de Custo (Unitário)',
            'numero_lote': 'Número do Lote',
            'fornecedor': 'Fornecedor',
            'numero_nota_fiscal': 'Número da Nota Fiscal',
        }

    def __init__(self, user, *args, **kwargs):
        super(LoteForm, self).__init__(*args, **kwargs)
        if user and hasattr(user, 'userprofile'):
             self.fields['produto'].queryset = Produto.objects.filter(empresa=user.userprofile.empresa)
        
        # Campos opcionais no HTML
        self.fields['numero_lote'].required = False
        self.fields['data_validade'].required = False
        
        for field in self.fields:
            if field != 'nota_fiscal' and field != 'controla_lote':
                self.fields[field].widget.attrs.update({'class': 'form-control'})

    def clean(self):
        cleaned_data = super().clean()
        produto = cleaned_data.get('produto')
        numero_lote = cleaned_data.get('numero_lote')
        data_validade = cleaned_data.get('data_validade')

        if produto:
            if produto.controla_lote:
                if not numero_lote:
                    self.add_error('numero_lote', 'Este produto exige um Número de Lote.')
                if not data_validade:
                    self.add_error('data_validade', 'Este produto exige Data de Validade.')
            else:
                if not numero_lote:
                    cleaned_data['numero_lote'] = 'GERAL'
                if not data_validade:
                    cleaned_data['data_validade'] = None
        
        return cleaned_data

# --- OUTROS FORMULÁRIOS (Empréstimo, Saída, Funcionário) ---

class EmprestimoForm(forms.ModelForm):
    categoria_filtro = forms.ModelChoiceField(
        queryset=Categoria.objects.none(),
        label="Filtrar por Categoria",
        required=False,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_categoria_filtro'})
    )

    class Meta:
        model = Emprestimo
        fields = ['categoria_filtro', 'produto', 'quantidade', 'solicitante', 'observacao'] # <--- Adicione 'quantidade'
        widgets = {
            'produto': forms.Select(attrs={'class': 'form-select', 'id': 'id_produto'}),
            'quantidade': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'step': '1'}), 
            'solicitante': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome de quem está retirando'}),
            'observacao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, user, *args, **kwargs):
        super(EmprestimoForm, self).__init__(*args, **kwargs)
        if user and hasattr(user, 'userprofile'):
            empresa = user.userprofile.empresa
            self.fields['categoria_filtro'].queryset = Categoria.objects.filter(empresa=empresa)
            self.fields['produto'].queryset = Produto.objects.filter(empresa=empresa).order_by('nome')
            

class SaidaEstoqueForm(forms.ModelForm):
    lote_especifico = forms.ModelChoiceField(
        queryset=Lote.objects.none(),
        required=False,
        label="Escolher Lote Específico (Opcional)",
        empty_label="Automático (Mais antigo primeiro)"
    )

    class Meta:
        model = SaidaEstoque
        fields = ['produto', 'lote_especifico', 'quantidade', 'valor_venda', 'motivo']
        widgets = {
            'produto': forms.Select(attrs={'class': 'form-select'}),
            'quantidade': forms.NumberInput(attrs={'class': 'form-control'}),
            'motivo': forms.TextInput(attrs={'class': 'form-control'}),
            'valor_venda': forms.NumberInput(attrs={
                'class': 'form-control',
                  'step': '0.01',
                    'placeholder': '0.00'}),
        }

    def __init__(self, user=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['produto'].queryset = Produto.objects.filter(empresa=user.userprofile.empresa)
            self.fields['lote_especifico'].queryset = Lote.objects.filter(produto__empresa=user.userprofile.empresa, status='ATIVO')
            self.fields['lote_especifico'].widget.attrs.update({'class': 'form-select'})

class CadastroSaaSForm(forms.Form):
    nome_completo = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Seu nome'}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'seu@email.com'}))
    senha = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Crie uma senha segura'}))
    nome_empresa = forms.CharField(max_length=100, label="Nome da Empresa", widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Oficina do Zé'}))
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Este e-mail já está cadastrado.")
        return email

class FuncionarioForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Senha inicial'}))
    username = forms.CharField(
        label="Usuário (Sufixo)",
        help_text="Apenas letras minúsculas e números.",
        widget=forms.TextInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Ex: joao',
            'onkeyup': 'this.value = this.value.toLowerCase().replace(/[^a-z0-9]/g, "");'
        })
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email', 'password']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Este e-mail já está em uso.")
        return email

    def clean_username(self):
        username = self.cleaned_data.get('username')
        username_limpo = slugify(username)
        username_limpo = username_limpo.replace('-', '')

        if not re.match(r'^[a-z0-9]+$', username_limpo):
            raise forms.ValidationError("O usuário deve conter apenas letras minúsculas e números (sem acentos, espaços ou símbolos).")
        
        return username_limpo