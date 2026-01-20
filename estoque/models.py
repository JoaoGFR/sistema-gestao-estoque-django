from django.db import models
from django.contrib.auth.models import User

class Produto(models.Model):
    CATEGORIAS = [
        ('PECA', 'Peça de Reposição'),
        ('EQUIP', 'Equipamento'),
        ('FERRA', 'Ferramenta'),
    ]

    nome = models.CharField(max_length=100)
    categoria = models.CharField(max_length=5, choices=CATEGORIAS)
    quantidade = models.IntegerField(default=0)
    preco_custo = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    
    # --- CAMPO NOVO ---
    locacao = models.CharField(max_length=100, blank=True, null=True, verbose_name="Localização na Estante")
    # ------------------

    data_entrada = models.DateTimeField(auto_now_add=True)
    descricao = models.TextField(blank=True)

    def __str__(self):
        return f"{self.nome} ({self.quantidade})"

# --- MODELOS DE EMPRÉSTIMO E SAÍDA (Mantenha igual) ---
class Emprestimo(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    nome_funcionario = models.CharField(max_length=100, help_text="Quem retirou o item")
    data_saida = models.DateTimeField(auto_now_add=True)
    data_devolucao = models.DateTimeField(null=True, blank=True)
    devolvido = models.BooleanField(default=False)
    responsavel_saida = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='saidas')
    responsavel_devolucao = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='entradas')

    def __str__(self):
        return f"{self.produto.nome} - {self.nome_funcionario}"

class SaidaEstoque(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    quantidade = models.PositiveIntegerField()
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    motivo = models.CharField(max_length=200)
    data = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Saída: {self.produto.nome}"