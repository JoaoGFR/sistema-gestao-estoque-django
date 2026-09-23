from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from .models import (
    Produto, Emprestimo, SaidaEstoque, Lote, UserProfile, Categoria, Localizacao,
    AliquotaImposto, Cliente, Venda, ItemVenda, ContaReceber, PagamentoCrediario
)
from django.utils.text import slugify
from django.utils import timezone
from django.db.models import Q
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
        fields = [
            'nome', 'sku', 'ean', 'categoria', 'unidade', 'estoque_minimo', 
            'localizacao', 'controla_lote', 'disponivel_venda', 'preco_venda'
        ]
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Cabo de Rede Cat6'}),
            'sku': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: CAB-001'}),
            'ean': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 7891234567890'}),
            'categoria': forms.Select(attrs={'class': 'form-select', 'id': 'id_categoria'}),
            'localizacao': forms.Select(attrs={'class': 'form-select', 'id': 'id_localizacao'}),
            'unidade': forms.Select(attrs={'class': 'form-select'}),
            'estoque_minimo': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'controla_lote': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_controla_lote'}),
            'disponivel_venda': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_disponivel_venda'}),
            'preco_venda': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'placeholder': '0.00', 'id': 'id_preco_venda'}),
        }

    def __init__(self, user, *args, **kwargs):
        super(ProdutoForm, self).__init__(*args, **kwargs)
        self.fields['preco_venda'].required = False
        self.fields['disponivel_venda'].required = False
        
        if user and hasattr(user, 'userprofile'):
            empresa = user.userprofile.empresa
            self.fields['categoria'].queryset = Categoria.objects.filter(empresa=empresa)
            self.fields['localizacao'].queryset = Localizacao.objects.filter(empresa=empresa)
        else:
            self.fields['categoria'].queryset = Categoria.objects.none()
            self.fields['localizacao'].queryset = Localizacao.objects.none()

    def clean(self):
        cleaned_data = super().clean()
        disponivel_venda = cleaned_data.get('disponivel_venda')
        preco_venda = cleaned_data.get('preco_venda')
        if disponivel_venda and (preco_venda is None or preco_venda < 0):
            self.add_error('preco_venda', 'Informe um preço de venda válido para produtos destinados à venda.')
        if preco_venda is None:
            cleaned_data['preco_venda'] = 0.00
        return cleaned_data

# --- FORMULÁRIO DE LOTE (ENTRADA) ---

class LoteForm(forms.ModelForm):
    class Meta:
        model = Lote
        fields = ['produto', 'numero_lote', 'preco_compra', 'fornecedor', 'data_fabricacao', 'data_validade', 'quantidade_inicial', 'numero_nota_fiscal', 'nota_fiscal']
        widgets = {
            'data_fabricacao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': 'form-control'}),
            'data_validade': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': 'form-control'}),
            'preco_compra': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'nota_fiscal': forms.FileInput(attrs={'class': 'form-control'}),
        }

        labels = {
            'quantidade_inicial': 'Quantidade',
            'preco_compra': 'Preço de Custo (Unitário)',
            'numero_lote': 'Número do Lote',
            'fornecedor': 'Fornecedor',
            'numero_nota_fiscal': 'Número da Nota Fiscal',
            'data_fabricacao': 'Data de Fabricação',
            'data_validade': 'Data de Validade',
        }

    def __init__(self, user, *args, **kwargs):
        super(LoteForm, self).__init__(*args, **kwargs)
        if user and hasattr(user, 'userprofile'):
             self.fields['produto'].queryset = Produto.objects.filter(empresa=user.userprofile.empresa)
        
        self.fields['data_fabricacao'].input_formats = ['%Y-%m-%d', '%d/%m/%Y']
        self.fields['data_validade'].input_formats = ['%Y-%m-%d', '%d/%m/%Y']

        # Quando editando um lote existente, preserva produto e pré-carrega as datas
        if self.instance and self.instance.pk:
            self.fields['produto'].disabled = True
            if self.instance.data_fabricacao:
                self.initial['data_fabricacao'] = self.instance.data_fabricacao.strftime('%Y-%m-%d')
            if self.instance.data_validade:
                self.initial['data_validade'] = self.instance.data_validade.strftime('%Y-%m-%d')

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

        # Preserva datas originais se deixadas em branco ao editar lote existente
        if self.instance and self.instance.pk:
            if not cleaned_data.get('data_fabricacao') and self.instance.data_fabricacao:
                cleaned_data['data_fabricacao'] = self.instance.data_fabricacao
            if not cleaned_data.get('data_validade') and self.instance.data_validade:
                cleaned_data['data_validade'] = self.instance.data_validade
                data_validade = self.instance.data_validade

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
        if user and hasattr(user, 'userprofile'):
            self.fields['produto'].queryset = Produto.objects.filter(empresa=user.userprofile.empresa)
            self.fields['lote_especifico'].queryset = Lote.objects.filter(produto__empresa=user.userprofile.empresa, status='ATIVO')
            self.fields['lote_especifico'].widget.attrs.update({'class': 'form-select'})

    def clean(self):
        cleaned_data = super().clean()
        produto = cleaned_data.get('produto')
        lote_especifico = cleaned_data.get('lote_especifico')
        if lote_especifico and produto and lote_especifico.produto_id != produto.id:
            self.add_error('lote_especifico', 'O lote selecionado não pertence ao produto informado.')
        return cleaned_data

class CadastroSaaSForm(forms.Form):
    nome_completo = forms.CharField(
        max_length=100, 
        label="Nome Completo",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Seu nome completo'})
    )
    email = forms.EmailField(
        label="E-mail de Acesso",
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'seu@email.com'})
    )
    senha = forms.CharField(
        label="Senha",
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Crie uma senha segura (mín. 8 caracteres)'})
    )
    nome_empresa = forms.CharField(
        max_length=100, 
        label="Nome da Sua Empresa / Negócio", 
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Auto Peças Modelo, Oficina Central'})
    )
    
    def clean_nome_completo(self):
        return self.cleaned_data.get('nome_completo', '').strip()

    def clean_nome_empresa(self):
        return self.cleaned_data.get('nome_empresa', '').strip()

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
            raise forms.ValidationError("Este e-mail já está cadastrado no sistema. Se já possui conta, faça login.")
        return email

    def clean_senha(self):
        senha = self.cleaned_data.get('senha')
        if senha:
            validate_password(senha)
        return senha

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

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password:
            validate_password(password)
        return password

    def clean_username(self):
        username = self.cleaned_data.get('username')
        username_limpo = slugify(username)
        username_limpo = username_limpo.replace('-', '')

        if not re.match(r'^[a-z0-9]+$', username_limpo):
            raise forms.ValidationError("O usuário deve conter apenas letras minúsculas e números (sem acentos, espaços ou símbolos).")
        
        return username_limpo

class AliquotaImpostoForm(forms.ModelForm):
    class Meta:
        model = AliquotaImposto
        fields = ['nome', 'percentual']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Simples Nacional, ICMS...'}),
            'percentual': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
        }


class EditarFuncionarioForm(forms.Form):
    first_name = forms.CharField(
        label="Nome",
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome'})
    )
    last_name = forms.CharField(
        label="Sobrenome",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Sobrenome'})
    )
    email = forms.EmailField(
        label="E-mail",
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'usuario@email.com'})
    )
    e_dono = forms.ChoiceField(
        label="Função no Sistema",
        choices=[(False, 'Colaborador'), (True, 'Administrador / Dono')],
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=True
    )
    is_active = forms.ChoiceField(
        label="Status da Conta",
        choices=[(True, 'Ativo (Pode acessar o sistema)'), (False, 'Inativo (Acesso bloqueado, histórico preservado)')],
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=True
    )
    nova_senha = forms.CharField(
        label="Nova Senha",
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Deixe em branco para manter a senha atual'}),
        help_text="Opcional. Preencha apenas se desejar redefinir a senha do colaborador."
    )

    def __init__(self, *args, user_instance=None, **kwargs):
        self.user_instance = user_instance
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data.get('email')
        query = User.objects.filter(email=email)
        if self.user_instance:
            query = query.exclude(pk=self.user_instance.pk)
        if query.exists():
            raise forms.ValidationError("Este e-mail já está sendo utilizado por outro usuário.")
        return email

    def clean_nova_senha(self):
        senha = self.cleaned_data.get('nova_senha')
        if senha:
            validate_password(senha, self.user_instance)
        return senha

    def clean_e_dono(self):
        val = self.cleaned_data.get('e_dono')
        return val in [True, 'True', 'true', 1, '1']

    def clean_is_active(self):
        val = self.cleaned_data.get('is_active')
        return val in [True, 'True', 'true', 1, '1']


# =============================================================================
# 13. FORMULÁRIOS COMERCIAIS: CLIENTES E CREDIÁRIO
# =============================================================================

class ClienteForm(forms.ModelForm):
    nome = forms.CharField(
        required=True,
        label="Nome Completo / Razão Social",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ex: Maria Silva ou Silva Comércio Ltda',
            'required': 'required'
        })
    )
    cpf_cnpj = forms.CharField(
        required=True,
        label="CPF / CNPJ",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'id': 'id_cpf_cnpj',
            'placeholder': '000.000.000-00',
            'autocomplete': 'off',
            'required': 'required'
        })
    )
    endereco = forms.CharField(
        required=True,
        label="Endereço Completo",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ex: Rua das Flores, 123 - Bairro',
            'required': 'required'
        })
    )
    telefone = forms.CharField(
        required=False,
        label="Telefone / WhatsApp",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'id': 'id_telefone',
            'placeholder': '(00) 00000-0000',
            'autocomplete': 'off'
        })
    )
    email = forms.EmailField(
        required=False,
        label="E-mail",
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ex: cliente@email.com (opcional)'
        })
    )

    class Meta:
        model = Cliente
        fields = [
            'nome', 'tipo_pessoa', 'cpf_cnpj', 'telefone', 'email',
            'endereco', 'cidade', 'limite_credito', 'ativo', 'observacoes'
        ]
        widgets = {
            'tipo_pessoa': forms.Select(attrs={'class': 'form-select', 'id': 'id_tipo_pessoa'}),
            'cidade': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: São Paulo'}),
            'limite_credito': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'observacoes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Observações internas sobre o cliente...'}),
        }

    def clean_nome(self):
        nome = self.cleaned_data.get('nome', '').strip()
        if not nome:
            raise forms.ValidationError("O nome ou razão social é obrigatório.")
        return nome

    def clean_cpf_cnpj(self):
        val = self.cleaned_data.get('cpf_cnpj', '').strip()
        if not val:
            raise forms.ValidationError("O CPF ou CNPJ é obrigatório.")
        digitos = re.sub(r'\D', '', val)
        if len(digitos) not in [11, 14]:
            raise forms.ValidationError("Informe um CPF com 11 dígitos ou CNPJ com 14 dígitos.")
        return val

    def clean_endereco(self):
        endereco = self.cleaned_data.get('endereco', '').strip()
        if not endereco:
            raise forms.ValidationError("O endereço completo é obrigatório.")
        return endereco

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if not email:
            return ""
        return email.strip()

    def clean_limite_credito(self):
        limite = self.cleaned_data.get('limite_credito')
        if limite is not None and limite < 0:
            raise forms.ValidationError("O limite de crédito não pode ser negativo.")
        return limite or 0.00


class ReceberPagamentoForm(forms.Form):
    valor_recebido = forms.DecimalField(
        label="Valor a Receber (R$)",
        max_digits=10,
        decimal_places=2,
        min_value=0.01,
        widget=forms.NumberInput(attrs={'class': 'form-control form-control-lg fw-bold text-success', 'step': '0.01'})
    )
    forma_pagamento = forms.ChoiceField(
        label="Forma de Pagamento",
        choices=PagamentoCrediario.FORMAS_RECEBIMENTO,
        widget=forms.Select(attrs={'class': 'form-select form-select-lg'})
    )
    data_recebimento = forms.DateField(
        label="Data do Pagamento",
        initial=timezone.now,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    observacoes = forms.CharField(
        label="Observações / Anotações",
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Pago via PIX pelo WhatsApp, recibo nº...'})
    )
