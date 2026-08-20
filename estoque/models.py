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

# 10. ALÍQUOTA DE IMPOSTO
class AliquotaImposto(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    nome = models.CharField(max_length=100, verbose_name="Nome do Imposto/Regime")
    percentual = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Alíquota (%)")

    def __str__(self):
        return f"{self.nome} ({self.percentual}%)"

# 11. SIMULAÇÃO DE PREÇO SALVA
class SimulacaoPreco(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    
    # Parâmetros de Entrada
    preco_custo = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Preço de Custo")
    quantidade_estoque = models.IntegerField(default=0, verbose_name="Quantidade no Estoque")
    
    # Dados da Compra Futura (Opcional)
    preco_custo_futuro = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Preço de Custo Futuro")
    quantidade_futura = models.IntegerField(null=True, blank=True, verbose_name="Quantidade da Compra Futura")
    
    # Custos Adicionais
    frete_valor = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Frete")
    tipo_frete = models.CharField(max_length=15, default='valor', verbose_name="Tipo de Frete")
    outros_valor = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Outros Custos")
    tipo_outros = models.CharField(max_length=15, default='valor', verbose_name="Tipo de Outros Custos")
    
    # Alíquota
    aliquota_nome = models.CharField(max_length=100, verbose_name="Nome do Imposto")
    aliquota_percentual = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Alíquota (%)")
    
    # Parâmetros Calculados
    margem_desejada = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Margem Desejada (%)")
    metodo = models.CharField(max_length=10, default='inside', verbose_name="Método (Markup)")
    
    # Resultados
    preco_sugerido = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Preço Sugerido")
    preco_praticado = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Preço Praticado")
    lucro_liquido = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Lucro Líquido (R$)")
    margem_realizada = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Margem Realizada (%)")
    
    data_criacao = models.DateTimeField(auto_now_add=True, verbose_name="Data de Simulação")

    @property
    def quantidade_total(self):
        return (self.quantidade_estoque or 0) + (self.quantidade_futura or 0)

    @property
    def lucro_total_lote(self):
        return float(self.lucro_liquido or 0) * self.quantidade_total

    @property
    def custo_efetivo(self):
        custo_base = float(self.preco_custo or 0)
        qtd_est = self.quantidade_estoque or 0
        qtd_fut = self.quantidade_futura or 0
        qtd_tot = self.quantidade_total
        
        if self.preco_custo_futuro and qtd_fut > 0 and qtd_tot > 0:
            custo_base = ((float(self.preco_custo or 0) * qtd_est) + (float(self.preco_custo_futuro or 0) * qtd_fut)) / qtd_tot
            
        frete_val = float(self.frete_valor or 0)
        outros_val = float(self.outros_valor or 0)
        
        frete_unit = frete_val
        if self.tipo_frete == 'percentual':
            frete_unit = custo_base * (frete_val / 100.0)
        elif self.tipo_frete == 'total':
            frete_unit = frete_val / (qtd_tot if qtd_tot > 0 else 1.0)

        outros_unit = outros_val
        if self.tipo_outros == 'percentual':
            outros_unit = custo_base * (outros_val / 100.0)
        elif self.tipo_outros == 'total':
            outros_unit = outros_val / (qtd_tot if qtd_tot > 0 else 1.0)
            
        return custo_base + frete_unit + outros_unit

    def __str__(self):
        return f"Simulação: {self.produto.nome} - R$ {self.preco_praticado} ({self.margem_realizada}%)"