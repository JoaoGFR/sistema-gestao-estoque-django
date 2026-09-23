from django.db import models
from django.contrib.auth.models import User
from django.db.models import Sum, F
from django.utils import timezone

from decimal import Decimal
from datetime import timedelta

# 1. EMPRESA 
class Empresa(models.Model):
    STATUS_ASSINATURA = [
        ('TRIAL', 'Período de Testes (3 dias)'),
        ('ATIVA', 'Assinatura Ativa'),
        ('VENCIDA', 'Vencida / Expirada'),
        ('CANCELADA', 'Cancelada'),
    ]

    nome = models.CharField(max_length=100)
    cnpj = models.CharField(max_length=20, blank=True, null=True)
    ativo = models.BooleanField(default=True)
    data_criacao = models.DateTimeField(default=timezone.now, verbose_name="Data de Cadastro")
    
    # Controle de Assinatura & Degustação
    status_assinatura = models.CharField(max_length=20, choices=STATUS_ASSINATURA, default='TRIAL', verbose_name="Status da Assinatura")
    trial_fim = models.DateTimeField(null=True, blank=True, verbose_name="Fim do Período de Testes")
    assinatura_fim = models.DateTimeField(null=True, blank=True, verbose_name="Fim da Vigência da Assinatura")

    def save(self, *args, **kwargs):
        if self.pk is None and not self.trial_fim and self.status_assinatura == 'TRIAL':
            base_time = self.data_criacao or timezone.now()
            self.trial_fim = base_time + timedelta(days=3)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nome

    @property
    def em_trial(self):
        if self.status_assinatura == 'TRIAL' and self.trial_fim:
            return timezone.now() <= self.trial_fim
        return False

    @property
    def assinatura_valida(self):
        agora = timezone.now()
        if self.status_assinatura == 'ATIVA' and self.assinatura_fim:
            return agora <= self.assinatura_fim
        if self.em_trial:
            return True
        return False

    @property
    def dias_restantes_trial(self):
        if not self.trial_fim:
            return 0
        delta = self.trial_fim - timezone.now()
        return max(0, delta.days)

    @property
    def horas_restantes_trial(self):
        if not self.trial_fim:
            return 0
        delta = self.trial_fim - timezone.now()
        horas = int(delta.total_seconds() // 3600)
        return max(0, horas)

    @property
    def dias_restantes_assinatura(self):
        if not self.assinatura_fim:
            return 0
        delta = self.assinatura_fim - timezone.now()
        return max(0, delta.days)

    @property
    def dono(self):
        perfil = self.userprofile_set.filter(e_dono=True).select_related('user').first()
        return perfil.user if perfil else None

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
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    controla_lote = models.BooleanField(default=True, verbose_name="Controla Lote e Validade?")
    disponivel_venda = models.BooleanField(default=False, verbose_name="Produto Destinado à Venda (PDV)?")
    preco_venda = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Preço de Venda (R$)")

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

    @property
    def margem_lucro(self):
        """Margem de Lucro percentual sobre a venda: ((Venda - Custo) / Venda) * 100"""
        venda = float(self.preco_venda or 0)
        custo = float(self.preco_medio or 0)
        if venda > 0:
            return round(((venda - custo) / venda) * 100, 2)
        return 0.0

    @property
    def markup(self):
        """Markup percentual sobre o custo: ((Venda - Custo) / Custo) * 100"""
        venda = float(self.preco_venda or 0)
        custo = float(self.preco_medio or 0)
        if custo > 0:
            return round(((venda - custo) / custo) * 100, 2)
        return 0.0

    @property
    def lucro_unitario(self):
        """Lucro bruto unitário: Venda - Custo"""
        venda = float(self.preco_venda or 0)
        custo = float(self.preco_medio or 0)
        return round(venda - custo, 2)

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

    @property
    def custo_total(self):
        return (self.preco_compra or Decimal('0.00')) * self.quantidade_inicial

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
    codigo_grupo = models.CharField(max_length=32, blank=True, null=True, db_index=True, verbose_name="Código da Baixa Agrupada")

    @property
    def subtotal(self):
        if self.valor_venda is not None:
            return self.valor_venda * self.quantidade
        return Decimal('0.00')

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
    aliquota_nome = models.CharField(max_length=255, verbose_name="Nome do Imposto")
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


# =============================================================================
# 12. MÓDULO COMERCIAL: CLIENTES, VENDAS E CREDIÁRIO
# =============================================================================

# 12.1 CLIENTES
class Cliente(models.Model):
    TIPO_PESSOA_CHOICES = [
        ('F', 'Pessoa Física'),
        ('J', 'Pessoa Jurídica'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='clientes')
    nome = models.CharField(max_length=200, verbose_name="Nome / Razão Social")
    tipo_pessoa = models.CharField(max_length=1, choices=TIPO_PESSOA_CHOICES, default='F', verbose_name="Tipo de Pessoa")
    cpf_cnpj = models.CharField(max_length=20, blank=True, null=True, db_index=True, verbose_name="CPF / CNPJ")
    telefone = models.CharField(max_length=30, blank=True, null=True, verbose_name="Telefone / WhatsApp")
    email = models.EmailField(blank=True, null=True, verbose_name="E-mail")
    endereco = models.CharField(max_length=255, blank=True, null=True, verbose_name="Endereço Completo")
    cidade = models.CharField(max_length=100, blank=True, null=True, verbose_name="Cidade")
    limite_credito = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Limite de Crediário (R$)")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    observacoes = models.TextField(blank=True, null=True, verbose_name="Observações")
    data_cadastro = models.DateTimeField(auto_now_add=True, verbose_name="Data de Cadastro")

    class Meta:
        ordering = ['nome']
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"

    def __str__(self):
        return self.nome

    @property
    def saldo_devedor(self):
        from django.db.models import Sum, F
        resultado = self.contas.filter(status__in=['PENDENTE', 'ATRASADO']).aggregate(
            total=Sum(F('valor_parcela') - F('valor_pago'))
        )['total']
        return resultado or 0.00

    @property
    def limite_disponivel(self):
        saldo = float(self.saldo_devedor)
        limite = float(self.limite_credito or 0)
        return max(0.0, limite - saldo)

    @property
    def tem_debitos_vencidos(self):
        hoje = timezone.now().date()
        return self.contas.filter(status='ATRASADO').exists() or self.contas.filter(status='PENDENTE', data_vencimento__lt=hoje).exists()


# 12.2 VENDAS
class Venda(models.Model):
    FORMAS_PAGAMENTO = [
        ('DINHEIRO', 'Dinheiro'),
        ('PIX', 'PIX'),
        ('DEBITO', 'Cartão de Débito'),
        ('CREDITO', 'Cartão de Crédito'),
        ('CREDIARIO', 'Crediário / A Prazo'),
    ]

    STATUS_VENDA = [
        ('CONCLUIDA', 'Concluída'),
        ('CANCELADA', 'Cancelada'),
    ]

    STATUS_PAGAMENTO = [
        ('PAGO', 'Pago'),
        ('PENDENTE', 'Pendente (Em Aberto)'),
        ('PARCIAL', 'Parcialmente Pago'),
        ('CANCELADO', 'Cancelado'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='vendas')
    codigo_venda = models.CharField(max_length=32, unique=True, db_index=True, verbose_name="Código da Venda")
    cliente = models.ForeignKey(Cliente, null=True, blank=True, on_delete=models.SET_NULL, related_name='vendas', verbose_name="Cliente")
    usuario = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Vendedor / Operador")
    data_venda = models.DateTimeField(default=timezone.now, verbose_name="Data da Venda")
    
    valor_subtotal = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Subtotal (R$)")
    desconto = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Desconto (R$)")
    valor_total = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor Total (R$)")
    
    forma_pagamento = models.CharField(max_length=20, choices=FORMAS_PAGAMENTO, default='DINHEIRO', verbose_name="Forma de Pagamento")
    status = models.CharField(max_length=20, choices=STATUS_VENDA, default='CONCLUIDA', verbose_name="Status da Venda")
    status_pagamento = models.CharField(max_length=20, choices=STATUS_PAGAMENTO, default='PAGO', verbose_name="Status do Pagamento")
    observacoes = models.TextField(blank=True, null=True, verbose_name="Observações")

    class Meta:
        ordering = ['-data_venda']
        verbose_name = "Venda"
        verbose_name_plural = "Vendas"

    def __str__(self):
        cliente_str = self.cliente.nome if self.cliente else "Consumidor Final"
        return f"{self.codigo_venda} - {cliente_str} (R$ {self.valor_total})"


# 12.3 ITENS DA VENDA
class ItemVenda(models.Model):
    venda = models.ForeignKey(Venda, related_name='itens', on_delete=models.CASCADE)
    produto = models.ForeignKey(Produto, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Produto")
    nome_produto = models.CharField(max_length=150, blank=True, null=True, verbose_name="Nome do Produto")
    lote = models.ForeignKey(Lote, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Lote de Origem")
    quantidade = models.IntegerField(verbose_name="Quantidade")
    preco_unitario = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Preço Unitário (R$)")
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Subtotal (R$)")
    saida_estoque = models.ForeignKey(SaidaEstoque, null=True, blank=True, on_delete=models.SET_NULL, related_name='itens_venda')

    @property
    def nome_exibicao(self):
        if self.produto:
            return self.produto.nome
        return self.nome_produto or "Produto Excluído"

    def __str__(self):
        return f"{self.nome_exibicao} ({self.quantidade}x R$ {self.preco_unitario})"


# 12.4 CREDIÁRIO / CONTAS A RECEBER
class ContaReceber(models.Model):
    STATUS_CONTA = [
        ('PENDENTE', 'Pendente'),
        ('PAGO', 'Pago'),
        ('ATRASADO', 'Atrasado'),
        ('CANCELADO', 'Cancelado'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='contas_receber')
    cliente = models.ForeignKey(Cliente, related_name='contas', on_delete=models.PROTECT, verbose_name="Cliente")
    venda = models.ForeignKey(Venda, related_name='parcelas', on_delete=models.CASCADE, verbose_name="Venda de Origem")
    numero_parcela = models.IntegerField(default=1, verbose_name="Nº da Parcela")
    total_parcelas = models.IntegerField(default=1, verbose_name="Total de Parcelas")
    valor_parcela = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor da Parcela (R$)")
    valor_pago = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Valor Pago (R$)")
    data_vencimento = models.DateField(verbose_name="Data de Vencimento")
    data_pagamento = models.DateTimeField(null=True, blank=True, verbose_name="Data de Pagamento")
    status = models.CharField(max_length=20, choices=STATUS_CONTA, default='PENDENTE', verbose_name="Status")
    observacoes = models.TextField(blank=True, null=True, verbose_name="Observações")

    class Meta:
        ordering = ['data_vencimento', 'numero_parcela']
        verbose_name = "Conta a Receber"
        verbose_name_plural = "Contas a Receber"

    def __str__(self):
        return f"{self.cliente.nome} - Parc {self.numero_parcela}/{self.total_parcelas} (R$ {self.valor_parcela})"

    @property
    def saldo_restante(self):
        return max(0.0, float(self.valor_parcela) - float(self.valor_pago))

    @property
    def esta_vencida(self):
        hoje = timezone.now().date()
        return self.status in ['PENDENTE', 'ATRASADO'] and self.data_vencimento < hoje

    @property
    def dias_atraso(self):
        if self.esta_vencida:
            return (timezone.now().date() - self.data_vencimento).days
        return 0


# 12.5 PAGAMENTO / BAIXA DE CREDIÁRIO
class PagamentoCrediario(models.Model):
    FORMAS_RECEBIMENTO = [
        ('DINHEIRO', 'Dinheiro'),
        ('PIX', 'PIX'),
        ('DEBITO', 'Cartão de Débito'),
        ('CREDITO', 'Cartão de Crédito'),
        ('OUTRO', 'Outro'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='pagamentos_crediario')
    conta = models.ForeignKey(ContaReceber, related_name='pagamentos', on_delete=models.CASCADE, verbose_name="Conta / Parcela")
    valor_recebido = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor Recebido (R$)")
    forma_pagamento = models.CharField(max_length=20, choices=FORMAS_RECEBIMENTO, default='DINHEIRO', verbose_name="Forma de Pagamento")
    data_recebimento = models.DateTimeField(default=timezone.now, verbose_name="Data do Recebimento")
    usuario = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Operador")
    observacoes = models.TextField(blank=True, null=True, verbose_name="Observações")

    class Meta:
        ordering = ['-data_recebimento']
        verbose_name = "Pagamento de Crediário"
        verbose_name_plural = "Pagamentos de Crediário"

    def __str__(self):
        return f"Pagamento R$ {self.valor_recebido} ({self.conta.cliente.nome})"


# 13. ASSINATURAS & PAGAMENTOS SAAS (MERCADO PAGO)
class PagamentoAssinatura(models.Model):
    STATUS_PAGAMENTO = [
        ('PENDENTE', 'Pendente'),
        ('APROVADO', 'Aprovado'),
        ('REJEITADO', 'Rejeitado / Falhou'),
        ('CANCELADO', 'Cancelado'),
    ]

    METODOS = [
        ('MERCADO_PAGO', 'Mercado Pago (Pix / Cartão)'),
        ('MANUAL_ADMIN', 'Ativação Manual / Cortesia'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='pagamentos_assinatura')
    valor = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('50.00'), verbose_name="Valor da Assinatura (R$)")
    metodo = models.CharField(max_length=30, choices=METODOS, default='MERCADO_PAGO', verbose_name="Método")
    status = models.CharField(max_length=20, choices=STATUS_PAGAMENTO, default='PENDENTE', verbose_name="Status")
    
    # Identificadores do Mercado Pago
    mp_preference_id = models.CharField(max_length=150, blank=True, null=True, verbose_name="ID da Preferência MP")
    mp_payment_id = models.CharField(max_length=150, blank=True, null=True, unique=True, verbose_name="ID do Pagamento MP")
    mp_init_point = models.URLField(max_length=500, blank=True, null=True, verbose_name="URL de Checkout MP")
    
    dias_concedidos = models.IntegerField(default=30, verbose_name="Dias Concedidos")
    data_criacao = models.DateTimeField(default=timezone.now, verbose_name="Data de Criação")
    data_confirmacao = models.DateTimeField(blank=True, null=True, verbose_name="Data de Confirmação")
    observacoes = models.TextField(blank=True, null=True, verbose_name="Observações / Detalhes")

    class Meta:
        ordering = ['-data_criacao']
        verbose_name = "Pagamento de Assinatura"
        verbose_name_plural = "Pagamentos de Assinatura"

    def __str__(self):
        return f"Assinatura R$ {self.valor} - {self.empresa.nome} ({self.status})"


# 14. HISTÓRICO DE PREÇOS DE VENDA
class HistoricoPreco(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='historicos_preco')
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name='historico_precos')
    preco_anterior = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Preço Anterior (R$)")
    preco_novo = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Novo Preço (R$)")
    usuario = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Usuário Responsável")
    data_alteracao = models.DateTimeField(auto_now_add=True, verbose_name="Data da Alteração")
    motivo = models.CharField(max_length=255, blank=True, default="Ajuste de preço", verbose_name="Motivo")

    class Meta:
        ordering = ['-data_alteracao']
        verbose_name = "Histórico de Preço"
        verbose_name_plural = "Históricos de Preços"

    @property
    def variacao_valor(self):
        return self.preco_novo - self.preco_anterior

    @property
    def variacao_percentual(self):
        if self.preco_anterior and self.preco_anterior > 0:
            return round(((self.preco_novo - self.preco_anterior) / self.preco_anterior) * 100, 1)
        return 0.0

    def __str__(self):
        return f"{self.produto.nome}: R$ {self.preco_anterior} -> R$ {self.preco_novo}"
