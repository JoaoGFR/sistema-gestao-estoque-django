from django.db import models
from django.contrib.auth.models import User
from django.db.models import Sum, F
from django.utils import timezone

# 1. EMPRESA 
class Empresa(models.Model):
    nome = models.CharField(max_length=100)
    cnpj = models.CharField(max_length=20, blank=True, null=True)
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return self.nome

# 2. PERFIL DE USUÁRIO
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    e_dono = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} - {self.empresa.nome}"

# 3. CATEGORIA
class Categoria(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    nome = models.CharField(max_length=100)
    
    def __str__(self):
        return self.nome

# 4. LOCALIZAÇÃO (NOVA TABELA)
class Localizacao(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    nome = models.CharField(max_length=100, verbose_name="Endereço/Local")
    
    def __str__(self):
        return self.nome

# 5. UNIDADES DE MEDIDA
class UnidadeMedida(models.TextChoices):
    UNIDADE = 'UN', 'Unidade'
    METRO = 'M', 'Metro'
    KILO = 'KG', 'Quilo'
    LITRO = 'L', 'Litro'
    CAIXA = 'CX', 'Caixa'
    ROLO = 'RL', 'Rolo'
    PACOTE = 'PCT', 'Pacote'
    GALAO = 'GL', 'Galão'
    BAG = 'BG', 'Bag'
# 6. PRODUTO 
class Produto(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    
    # Vínculos com as tabelas auxiliares
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Categoria")
    localizacao = models.ForeignKey(Localizacao, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Localização no Estoque")
    
    nome = models.CharField(max_length=100)
    sku = models.CharField(max_length=50, blank=True, null=True, verbose_name="SKU")
    ean = models.CharField(max_length=13, blank=True, null=True, verbose_name="Código de Barras (EAN)")
    unidade = models.CharField(max_length=5, choices=UnidadeMedida.choices, default=UnidadeMedida.UNIDADE)
    estoque_minimo = models.IntegerField(default=5)
    
    controla_lote = models.BooleanField(default=True, verbose_name="Controla Lote e Validade?")

    def __str__(self):
        return self.nome

    # Propriedades para cálculos no Template
    @property
    def saldo_total(self):
        lotes_ativos = self.lotes.filter(status='ATIVO')
        return sum(lote.quantidade_atual for lote in lotes_ativos)

    @property
    def preco_medio(self):
        lotes_ativos = self.lotes.filter(status='ATIVO', quantidade_atual__gt=0)
        if not lotes_ativos.exists():
            return 0
        
        total_valor = sum(lote.quantidade_atual * lote.preco_compra for lote in lotes_ativos)
        total_qtd = sum(lote.quantidade_atual for lote in lotes_ativos)
        
        if total_qtd == 0: return 0
        return total_valor / total_qtd

# 7. LOTE (Entrada de Mercadoria)
class Lote(models.Model):
    STATUS_CHOICES = [
        ('ATIVO', 'Ativo'),
        ('ESGOTADO', 'Esgotado'),
        ('VENCIDO', 'Vencido'),
    ]
    
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name='lotes')
    numero_lote = models.CharField(max_length=50, blank=True)
    preco_compra = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Preço de Custo (Unitário)")
    
    fornecedor = models.CharField(max_length=100, blank=True, null=True)
    data_fabricacao = models.DateField(null=True, blank=True, verbose_name="Data de Fabricação")
    data_validade = models.DateField(null=True, blank=True, verbose_name="Data de Validade")
    
    quantidade_inicial = models.IntegerField()
    quantidade_atual = models.IntegerField()
    
    data_entrada = models.DateTimeField(auto_now_add=True)
    numero_nota_fiscal = models.CharField(max_length=50, blank=True, null=True)
    nota_fiscal = models.FileField(upload_to='notas_fiscais/', blank=True, null=True)
    
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='ATIVO')

    def save(self, *args, **kwargs):
        if self.quantidade_atual <= 0:
            self.status = 'ESGOTADO'
        elif self.status == 'ESGOTADO' and self.quantidade_atual > 0:
            self.status = 'ATIVO'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Lote {self.numero_lote} - {self.produto.nome}"

# 8. SAÍDA DE ESTOQUE
class SaidaEstoque(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    quantidade = models.IntegerField()
    motivo = models.CharField(max_length=200)
    data = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    valor_venda = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, null=True, blank=True, verbose_name="Valor de Venda (Unitário)")
    lote = models.ForeignKey(Lote, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Lote de Origem")

    def __str__(self):
        return f"{self.produto.nome} - {self.quantidade}"

# 9. EMPRÉSTIMO
class Emprestimo(models.Model):
    lote = models.ForeignKey(Lote, on_delete=models.CASCADE, null=True, blank=True)
    quantidade = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    responsavel_saida = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='emprestimos_realizados')
    solicitante = models.CharField(max_length=100, verbose_name="Nome do Solicitante")  
    data_saida = models.DateTimeField(default=timezone.now, verbose_name="Data de Saída")
    data_devolucao = models.DateTimeField(null=True, blank=True)
    devolvido = models.BooleanField(default=False)
    observacao = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.produto.nome} - {self.solicitante} ({self.quantidade})"