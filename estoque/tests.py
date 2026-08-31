from django.test import TestCase
from django.contrib.auth.models import User
from .models import Empresa, Produto, SimulacaoPreco

class SimulacaoPrecoTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password123')
        self.empresa = Empresa.objects.create(nome='Empresa Teste', cnpj='12.345.678/0001-99')
        self.produto = Produto.objects.create(
            empresa=self.empresa,
            nome='Produto Teste'
        )
        self.simulacao = SimulacaoPreco.objects.create(
            empresa=self.empresa,
            produto=self.produto,
            preco_custo=50.00,
            quantidade_estoque=10,
            preco_custo_futuro=40.00,
            quantidade_futura=10,
            frete_valor=10.00,
            tipo_frete='valor',
            outros_valor=5.00,
            tipo_outros='valor',
            aliquota_nome='Sem Imposto',
            aliquota_percentual=0,
            margem_desejada=20,
            metodo='inside',
            preco_sugerido=81.25,
            preco_praticado=85.00,
            lucro_liquido=20.00,
            margem_realizada=23.5
        )

    def test_quantidade_total(self):
        self.assertEqual(self.simulacao.quantidade_total, 20)

    def test_lucro_total_lote(self):
        self.assertEqual(self.simulacao.lucro_total_lote, 400.0)

    def test_custo_efetivo(self):
        # Base ponderada: (50*10 + 40*10)/20 = 45.0 + 10(frete) + 5(outros) = 60.0
        self.assertEqual(self.simulacao.custo_efetivo, 60.0)


class SecurityAuditTestCase(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome='Empresa Segura')
        self.user = User.objects.create_user(username='admin_empresa', email='admin@empresa.com', password='StrongPassword123!')
        self.produto_a = Produto.objects.create(empresa=self.empresa, nome='Produto A')
        self.produto_b = Produto.objects.create(empresa=self.empresa, nome='Produto B')

    def test_cadastro_saas_rejects_weak_password(self):
        from .forms import CadastroSaaSForm
        form = CadastroSaaSForm(data={
            'nome_completo': 'Novo Usuario',
            'email': 'novo@empresa.com',
            'senha': '123',
            'nome_empresa': 'Nova Empresa'
        })
        self.assertFalse(form.is_valid())
        self.assertIn('senha', form.errors)

    def test_cadastro_saas_accepts_strong_password(self):
        from .forms import CadastroSaaSForm
        form = CadastroSaaSForm(data={
            'nome_completo': 'Novo Usuario',
            'email': 'novo@empresa.com',
            'senha': 'StrongPassword123!',
            'nome_empresa': 'Nova Empresa'
        })
        self.assertTrue(form.is_valid())

    def test_cadastro_saas_post_success(self):
        response = self.client.post('/assinar/', data={
            'nome_completo': 'Usuário Teste Cadastro',
            'email': 'cadastro_teste@empresa.com',
            'senha': 'StrongPassword123!',
            'nome_empresa': 'Empresa Nova Teste'
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, '/dashboard/')
        self.assertTrue(User.objects.filter(email='cadastro_teste@empresa.com').exists())

    def test_saida_estoque_rejects_mismatched_batch(self):
        from .models import Lote, UserProfile
        from .forms import SaidaEstoqueForm
        UserProfile.objects.create(user=self.user, empresa=self.empresa, e_dono=True)
        
        # Lote pertencente ao Produto B
        lote_b = Lote.objects.create(
            produto=self.produto_b,
            numero_lote='LOT-B',
            quantidade_inicial=10,
            quantidade_atual=10
        )

        # Tentativa de saída do Produto A usando o lote do Produto B
        form = SaidaEstoqueForm(user=self.user, data={
            'produto': self.produto_a.id,
            'lote_especifico': lote_b.id,
            'quantidade': 2,
            'motivo': 'Venda teste'
        })
        self.assertFalse(form.is_valid())
        self.assertIn('lote_especifico', form.errors)

    def test_default_admin_url_is_not_found(self):
        # A rota padrão /admin/ deve retornar 404
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, 404)

    def test_secure_admin_url_exists(self):
        # A rota segura /gerencia-segura/ deve responder (redirecionar para login ou 200)
        response = self.client.get('/gerencia-segura/login/')
        self.assertEqual(response.status_code, 200)


