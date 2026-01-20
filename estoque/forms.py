from django import forms
from .models import Produto, Emprestimo, SaidaEstoque

class ProdutoForm(forms.ModelForm):
    class Meta:
        model = Produto
        # Adicionei 'locacao' na lista abaixo
        fields = ['nome', 'categoria', 'quantidade', 'preco_custo', 'locacao', 'descricao']
        
        widgets = {
            'nome': forms.TextInput(attrs={'placeholder': 'Ex: Parafusadeira Makita 12v'}),
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'quantidade': forms.NumberInput(attrs={'placeholder': '0'}),
            'preco_custo': forms.NumberInput(attrs={'placeholder': '0.00'}),
            # Visual do campo Locacao
            'locacao': forms.TextInput(attrs={'placeholder': 'Ex: Estante B, Prateleira 2'}), 
            'descricao': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Detalhes adicionais...'}),
        }
        labels = {
            'preco_custo': 'Preço de Custo (R$)',
            'descricao': 'Observações',
            'locacao': 'Localização Física'
        }

class EmprestimoForm(forms.ModelForm):
    class Meta:
        model = Emprestimo
        fields = ['produto', 'nome_funcionario']
        widgets = {
            'nome_funcionario': forms.TextInput(attrs={'placeholder': 'Ex: João da Manutenção'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['produto'].queryset = Produto.objects.filter(quantidade__gt=0)

class SaidaEstoqueForm(forms.ModelForm):
    class Meta:
        model = SaidaEstoque
        fields = ['produto', 'quantidade', 'motivo']
        widgets = {
            'motivo': forms.TextInput(attrs={'placeholder': 'Onde a peça será usada?'}),
            'quantidade': forms.NumberInput(attrs={'placeholder': 'Qtd'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['produto'].queryset = Produto.objects.filter(quantidade__gt=0)