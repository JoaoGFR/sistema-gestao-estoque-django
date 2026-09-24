import json
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock
from .models import (
    Empresa, Produto, SimulacaoPreco, UserProfile, Lote, Cliente,
    Venda, ItemVenda, ContaReceber, PagamentoCrediario, SaidaEstoque,
    PagamentoAssinatura, HistoricoPreco, AliquotaImposto, Categoria
)
from django.core.files.uploadedfile import SimpleUploadedFile

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


class FuncionarioEditTestCase(TestCase):
    def setUp(self):
        from .models import Empresa, UserProfile
        self.empresa = Empresa.objects.create(nome='Empresa Alpha')
        self.dono = User.objects.create_user(
            username='alpha.dono',
            email='dono@alpha.com',
            password='StrongPassword123!',
            first_name='Carlos',
            last_name='Silva'
        )
        self.dono_profile = UserProfile.objects.create(user=self.dono, empresa=self.empresa, e_dono=True)

        self.colaborador = User.objects.create_user(
            username='alpha.joao',
            email='joao@alpha.com',
            password='PasswordJoao123!',
            first_name='Joao',
            last_name='Souza'
        )
        self.colab_profile = UserProfile.objects.create(user=self.colaborador, empresa=self.empresa, e_dono=False)

        # Outra empresa para teste de isolamento multi-tenant (IDOR)
        self.empresa_beta = Empresa.objects.create(nome='Empresa Beta')
        self.user_beta = User.objects.create_user(
            username='beta.maria',
            email='maria@beta.com',
            password='PasswordBeta123!'
        )
        self.beta_profile = UserProfile.objects.create(user=self.user_beta, empresa=self.empresa_beta, e_dono=False)

    def test_editar_funcionario_e_preservar_historico(self):
        from .models import Produto, Lote, SaidaEstoque
        # 1. Cria produto, lote e saída atribuída ao colaborador
        produto = Produto.objects.create(empresa=self.empresa, nome='Chave de Fenda')
        lote = Lote.objects.create(produto=produto, quantidade_inicial=10, quantidade_atual=8)
        saida = SaidaEstoque.objects.create(
            produto=produto,
            lote=lote,
            quantidade=2,
            motivo='Saida de teste',
            usuario=self.colaborador
        )

        # Login como dono
        self.client.force_login(self.dono)

        # 2. Executa POST de edição do colaborador
        colab_id = self.colaborador.id
        response = self.client.post(f'/equipe/editar/{colab_id}/', data={
            'first_name': 'Joao Victor',
            'last_name': 'Souza Editado',
            'email': 'joao.novo@alpha.com',
            'e_dono': 'False',
            'is_active': 'True',
            'nova_senha': ''
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, '/equipe/')

        # 3. Verifica se os dados foram atualizados sem mudar a PK
        self.colaborador.refresh_from_db()
        self.assertEqual(self.colaborador.first_name, 'Joao Victor')
        self.assertEqual(self.colaborador.last_name, 'Souza Editado')
        self.assertEqual(self.colaborador.email, 'joao.novo@alpha.com')
        self.assertEqual(self.colaborador.id, colab_id)

        # 4. CRUCIAL: Verifica se a saída histórica continua vinculada exatamente a ele
        saida.refresh_from_db()
        self.assertEqual(saida.usuario.id, colab_id)
        self.assertEqual(saida.usuario.get_full_name(), 'Joao Victor Souza Editado')

    def test_desativar_funcionario_mantem_historico(self):
        # Desativa o colaborador
        self.client.force_login(self.dono)
        response = self.client.post(f'/equipe/editar/{self.colaborador.id}/', data={
            'first_name': self.colaborador.first_name,
            'last_name': self.colaborador.last_name,
            'email': self.colaborador.email,
            'e_dono': 'False',
            'is_active': 'False',  # Inativo
            'nova_senha': ''
        })
        self.assertEqual(response.status_code, 302)
        self.colaborador.refresh_from_db()
        self.assertFalse(self.colaborador.is_active)

    def test_bloqueio_cross_tenant_idor(self):
        # Dono da empresa Alpha tenta editar funcionário da empresa Beta
        self.client.force_login(self.dono)
        response = self.client.get(f'/equipe/editar/{self.user_beta.id}/')
        self.assertEqual(response.status_code, 404)

    def test_colaborador_sem_permissao_redireciona(self):
        # Colaborador tenta acessar a tela de edição
        self.client.force_login(self.colaborador)
        response = self.client.get(f'/equipe/editar/{self.dono.id}/')
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, '/dashboard/')

    def test_colisao_email_rejeitada(self):
        self.client.force_login(self.dono)
        # Tenta trocar o e-mail do colaborador pelo do dono
        response = self.client.post(f'/equipe/editar/{self.colaborador.id}/', data={
            'first_name': 'Joao',
            'last_name': 'Souza',
            'email': 'dono@alpha.com',  # Já existente
            'e_dono': 'False',
            'is_active': 'True',
            'nova_senha': ''
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('Este e-mail já está sendo utilizado por outro usuário.', response.context['form'].errors['email'])


class BaixaMultiplaTestCase(TestCase):
    def setUp(self):
        import json
        from .models import Empresa, UserProfile, Produto, Lote, SaidaEstoque
        self.empresa = Empresa.objects.create(nome='Oficina Central')
        self.user = User.objects.create_user(
            username='oficina.admin',
            email='admin@oficina.com',
            password='StrongPassword123!',
            first_name='Mestre',
            last_name='Oficina'
        )
        self.profile = UserProfile.objects.create(user=self.user, empresa=self.empresa, e_dono=True)

        # Produto 1 (com 2 lotes para testar quebra FEFO)
        self.prod_1 = Produto.objects.create(empresa=self.empresa, nome='Parafuso Sextavado', estoque_minimo=5)
        self.lote_1a = Lote.objects.create(
            produto=self.prod_1, numero_lote='LOT-1A', preco_compra=0.50,
            quantidade_inicial=10, quantidade_atual=10, status='ATIVO'
        )
        self.lote_1b = Lote.objects.create(
            produto=self.prod_1, numero_lote='LOT-1B', preco_compra=0.60,
            quantidade_inicial=10, quantidade_atual=10, status='ATIVO'
        )

        # Produto 2 (com 1 lote)
        self.prod_2 = Produto.objects.create(empresa=self.empresa, nome='Porca Travante', estoque_minimo=5)
        self.lote_2 = Lote.objects.create(
            produto=self.prod_2, numero_lote='LOT-2', preco_compra=0.30,
            quantidade_inicial=15, quantidade_atual=15, status='ATIVO'
        )

    def test_baixa_multipla_sucesso(self):
        import json
        from .models import SaidaEstoque
        self.client.force_login(self.user)

        itens_payload = [
            {
                'produto_id': self.prod_1.id,
                'lote_id': None,  # Automático (FEFO divide entre 1A e 1B)
                'quantidade': 12,
                'valor_venda': 1.00
            },
            {
                'produto_id': self.prod_2.id,
                'lote_id': self.lote_2.id,  # Lote manual
                'quantidade': 5,
                'valor_venda': 0.80
            }
        ]

        response = self.client.post('/saidas/nova/', data={
            'itens_json': json.dumps(itens_payload),
            'motivo': 'Ordem de Servico #501'
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, '/saidas/')

        # Verifica decremento de lotes
        self.lote_1a.refresh_from_db()
        self.lote_1b.refresh_from_db()
        self.lote_2.refresh_from_db()

        self.assertEqual(self.lote_1a.quantidade_atual, 0)
        self.assertEqual(self.lote_1a.status, 'ESGOTADO')
        self.assertEqual(self.lote_1b.quantidade_atual, 8)
        self.assertEqual(self.lote_2.quantidade_atual, 10)

        # Verifica registros de saída
        saidas = SaidaEstoque.objects.filter(motivo__startswith='Ordem de Servico #501')
        self.assertEqual(saidas.count(), 3)  # 2 saídas para prod 1 (lote 1a e 1b) + 1 saída para prod 2

        # Verifica se todos compartilham o mesmo codigo_grupo
        codigos = set(s.codigo_grupo for s in saidas)
        self.assertEqual(len(codigos), 1)
        self.assertTrue(list(codigos)[0].startswith('BX-'))

    def test_baixa_multipla_reverte_atomicamente_em_falha(self):
        import json
        from .models import SaidaEstoque
        self.client.force_login(self.user)

        itens_payload = [
            {
                'produto_id': self.prod_1.id,
                'lote_id': None,
                'quantidade': 5,  # Válido
                'valor_venda': 1.00
            },
            {
                'produto_id': self.prod_2.id,
                'lote_id': None,
                'quantidade': 500,  # Saldo insuficiente! (Só tem 15)
                'valor_venda': 0.80
            }
        ]

        response = self.client.post('/saidas/nova/', data={
            'itens_json': json.dumps(itens_payload),
            'motivo': 'Tentativa com saldo insuficiente'
        })
        self.assertEqual(response.status_code, 200)

        # Verifica que o lote 1A NÃO sofreu baixa (rollback total)
        self.lote_1a.refresh_from_db()
        self.assertEqual(self.lote_1a.quantidade_atual, 10)
        self.assertEqual(SaidaEstoque.objects.filter(motivo__contains='Tentativa').count(), 0)

    def test_baixa_individual_legado_mantida(self):
        # Garante que requisições legadas via SaidaEstoqueForm continuam funcionando
        from .models import SaidaEstoque
        self.client.force_login(self.user)

        response = self.client.post('/saidas/nova/', data={
            'produto': self.prod_2.id,
            'lote_especifico': '',  # Automático
            'quantidade': 3,
            'motivo': 'Venda Legado Avulsa',
            'valor_venda': '0.75'
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, '/saidas/')

        self.lote_2.refresh_from_db()
        self.assertEqual(self.lote_2.quantidade_atual, 12)
        self.assertTrue(SaidaEstoque.objects.filter(motivo__contains='Venda Legado Avulsa').exists())


class VendasCrediarioTestCase(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Tech Distribuidora", cnpj="12345678000199")
        self.user = User.objects.create_user(username="tech.joao", password="password123")
        self.profile = UserProfile.objects.create(user=self.user, empresa=self.empresa, e_dono=True)

        self.prod = Produto.objects.create(
            empresa=self.empresa,
            nome="Cabo de Rede Cat6 305m",
            sku="CABO-CAT6",
            unidade="CX"
        )
        self.lote = Lote.objects.create(
            produto=self.prod,
            numero_lote="L-900",
            preco_compra=250.00,
            quantidade_inicial=20,
            quantidade_atual=20,
            status='ATIVO'
        )

        self.cliente = Cliente.objects.create(
            empresa=self.empresa,
            nome="Instaladora Silva & Cia",
            cpf_cnpj="98.765.432/0001-10",
            telefone="(11) 98888-7777",
            limite_credito=1500.00,
            ativo=True
        )

    def test_cliente_saldo_e_limite_inicial(self):
        self.assertEqual(self.cliente.saldo_devedor, 0.00)
        self.assertEqual(self.cliente.limite_disponivel, 1500.00)
        self.assertFalse(self.cliente.tem_debitos_vencidos)

    def test_cliente_form_obrigatoriedade_e_email_opcional(self):
        from .forms import ClienteForm

        # 1. Sucesso com e-mail em branco (opcional), mas com nome, CPF e endereço preenchidos
        form_valido = ClienteForm(data={
            'nome': 'João da Silva',
            'tipo_pessoa': 'F',
            'cpf_cnpj': '123.456.789-01',
            'endereco': 'Rua Principal, 50',
            'telefone': '(11) 98765-4321',
            'email': '',  # Opcional!
            'cidade': 'São Paulo',
            'limite_credito': '500.00',
            'ativo': True
        })
        self.assertTrue(form_valido.is_valid(), form_valido.errors)

        # 2. Erro se faltar CPF/CNPJ
        form_sem_cpf = ClienteForm(data={
            'nome': 'João da Silva',
            'tipo_pessoa': 'F',
            'cpf_cnpj': '',
            'endereco': 'Rua Principal, 50'
        })
        self.assertFalse(form_sem_cpf.is_valid())
        self.assertIn('cpf_cnpj', form_sem_cpf.errors)

        # 3. Erro se faltar Endereço
        form_sem_endereco = ClienteForm(data={
            'nome': 'João da Silva',
            'tipo_pessoa': 'F',
            'cpf_cnpj': '123.456.789-01',
            'endereco': ''
        })
        self.assertFalse(form_sem_endereco.is_valid())
        self.assertIn('endereco', form_sem_endereco.errors)

    def test_venda_a_vista_debita_estoque(self):
        import json
        from .models import Venda, SaidaEstoque
        self.client.force_login(self.user)

        itens_payload = [
            {
                'produto_id': self.prod.id,
                'lote_id': self.lote.id,
                'quantidade': 3,
                'preco_unitario': 350.00
            }
        ]

        response = self.client.post('/vendas/nova/', data={
            'itens_json': json.dumps(itens_payload),
            'forma_pagamento': 'PIX',
            'desconto': '50.00',
            'observacoes': 'Venda balcão à vista'
        })
        self.assertEqual(response.status_code, 302)

        venda = Venda.objects.first()
        self.assertIsNotNone(venda)
        self.assertEqual(venda.valor_subtotal, 1050.00)
        self.assertEqual(venda.desconto, 50.00)
        self.assertEqual(venda.valor_total, 1000.00)
        self.assertEqual(venda.forma_pagamento, 'PIX')
        self.assertEqual(venda.status_pagamento, 'PAGO')

        # Estoque debitado
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, 17)

        # Saída gerada com mesmo código
        saida = SaidaEstoque.objects.filter(codigo_grupo=venda.codigo_venda).first()
        self.assertIsNotNone(saida)
        self.assertEqual(saida.quantidade, 3)

        # Sem parcelas no crediário
        self.assertEqual(venda.parcelas.count(), 0)

    def test_venda_crediario_gera_parcelas_e_debito(self):
        import json
        from .models import Venda, ContaReceber
        self.client.force_login(self.user)

        itens_payload = [
            {
                'produto_id': self.prod.id,
                'lote_id': None,  # Automático
                'quantidade': 2,
                'preco_unitario': 400.00
            }
        ]

        response = self.client.post('/vendas/nova/', data={
            'itens_json': json.dumps(itens_payload),
            'cliente_id': self.cliente.id,
            'forma_pagamento': 'CREDIARIO',
            'desconto': '0.00',
            'num_parcelas': 2,
            'intervalo_dias': 30
        })
        self.assertEqual(response.status_code, 302)

        venda = Venda.objects.first()
        self.assertIsNotNone(venda)
        self.assertEqual(venda.valor_total, 800.00)
        self.assertEqual(venda.status_pagamento, 'PENDENTE')

        # 2 parcelas de R$ 400 geradas
        parcelas = venda.parcelas.all().order_by('numero_parcela')
        self.assertEqual(parcelas.count(), 2)
        self.assertEqual(parcelas[0].valor_parcela, 400.00)
        self.assertEqual(parcelas[1].valor_parcela, 400.00)
        self.assertEqual(parcelas[0].status, 'PENDENTE')

        # Saldo devedor do cliente atualizado
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.saldo_devedor, 800.00)
        self.assertEqual(self.cliente.limite_disponivel, 700.00)

    def test_venda_crediario_bloqueia_excesso_de_limite(self):
        import json
        from .models import Venda
        self.client.force_login(self.user)

        # Cliente tem limite 1500, tenta comprar 10 unidades x 400 = 4000
        itens_payload = [
            {
                'produto_id': self.prod.id,
                'lote_id': None,
                'quantidade': 10,
                'preco_unitario': 400.00
            }
        ]

        response = self.client.post('/vendas/nova/', data={
            'itens_json': json.dumps(itens_payload),
            'cliente_id': self.cliente.id,
            'forma_pagamento': 'CREDIARIO',
            'desconto': '0.00',
            'num_parcelas': 1
        })
        self.assertEqual(response.status_code, 200)

        # Nenhuma venda e nenhum lote alterado
        self.assertEqual(Venda.objects.count(), 0)
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, 20)

    def test_quitar_parcela_crediario(self):
        import json
        from .models import Venda, PagamentoCrediario
        self.client.force_login(self.user)

        # Cria venda no crediário
        itens_payload = [{'produto_id': self.prod.id, 'lote_id': self.lote.id, 'quantidade': 1, 'preco_unitario': 300.00}]
        self.client.post('/vendas/nova/', data={
            'itens_json': json.dumps(itens_payload),
            'cliente_id': self.cliente.id,
            'forma_pagamento': 'CREDIARIO',
            'num_parcelas': 1
        })

        venda = Venda.objects.first()
        conta = venda.parcelas.first()
        self.assertEqual(conta.saldo_restante, 300.00)

        # Baixa de parcela
        resp = self.client.post(f'/crediario/baixar/{conta.id}/', data={
            'valor_recebido': '300.00',
            'forma_pagamento': 'PIX',
            'data_recebimento': timezone.now().strftime('%Y-%m-%d'),
            'observacoes': 'Pago via chave PIX CNPJ'
        })
        self.assertEqual(resp.status_code, 302)

        conta.refresh_from_db()
        self.assertEqual(conta.status, 'PAGO')
        self.assertEqual(conta.valor_pago, 300.00)
        self.assertEqual(conta.saldo_restante, 0.00)

        venda.refresh_from_db()
        self.assertEqual(venda.status_pagamento, 'PAGO')

        # Pagamento registrado
        pag = PagamentoCrediario.objects.filter(conta=conta).first()
        self.assertIsNotNone(pag)
        self.assertEqual(pag.valor_recebido, 300.00)

        # Saldo do cliente zerado
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.saldo_devedor, 0.00)

    def test_cancelar_venda_estorna_estoque_e_cancela_contas(self):
        import json
        from .models import Venda
        self.client.force_login(self.user)

        itens_payload = [{'produto_id': self.prod.id, 'lote_id': self.lote.id, 'quantidade': 4, 'preco_unitario': 200.00}]
        self.client.post('/vendas/nova/', data={
            'itens_json': json.dumps(itens_payload),
            'cliente_id': self.cliente.id,
            'forma_pagamento': 'CREDIARIO',
            'num_parcelas': 1
        })
        venda = Venda.objects.first()

        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, 16)

        # Cancelamento
        resp = self.client.post(f'/vendas/{venda.id}/cancelar/')
        self.assertEqual(resp.status_code, 302)

        venda.refresh_from_db()
        self.assertEqual(venda.status, 'CANCELADA')
        self.assertEqual(venda.status_pagamento, 'CANCELADO')

        # Estoque estornado
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, 20)

        # Parcela cancelada
        conta = venda.parcelas.first()
        self.assertEqual(conta.status, 'CANCELADO')

    def test_bloqueio_exclusao_saida_vinculada_a_venda(self):
        import json
        from .models import Venda, SaidaEstoque
        self.client.force_login(self.user)

        # 1. Realiza uma venda
        itens_payload = [{'produto_id': self.prod.id, 'lote_id': self.lote.id, 'quantidade': 3, 'preco_unitario': 250.00}]
        self.client.post('/vendas/nova/', data={
            'itens_json': json.dumps(itens_payload),
            'forma_pagamento': 'PIX'
        })
        venda = Venda.objects.first()
        saida_venda = SaidaEstoque.objects.filter(codigo_grupo=venda.codigo_venda).first()
        self.assertIsNotNone(saida_venda)

        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, 17)

        # 2. Tenta excluir a saída diretamente pela rota /saidas/excluir/<id>/
        resp = self.client.post(f'/saidas/excluir/{saida_venda.id}/')
        self.assertEqual(resp.status_code, 302)

        # 3. Verifica que o cancelamento foi BLOQUEADO e a saída continua existindo
        self.assertTrue(SaidaEstoque.objects.filter(id=saida_venda.id).exists())
        # Estoque NÃO foi duplicado
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, 17)


class BuscaInteligenteModalTestCase(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome='Empresa Busca Modal', cnpj='77.888.999/0001-11')
        self.user = User.objects.create_user(username='operador_busca', password='Password123!')
        UserProfile.objects.create(user=self.user, empresa=self.empresa)

        from .models import Categoria, Localizacao
        self.cat_eletrica = Categoria.objects.create(empresa=self.empresa, nome='Elétrica')
        self.loc_a1 = Localizacao.objects.create(empresa=self.empresa, nome='Prateleira A1')

        self.prod1 = Produto.objects.create(
            empresa=self.empresa,
            nome='Disjuntor Bipolar 20A',
            sku='DISJ-20A',
            ean='7891112223334',
            categoria=self.cat_eletrica,
            localizacao=self.loc_a1
        )
        Lote.objects.create(
            produto=self.prod1,
            numero_lote='LT-001',
            preco_compra=35.00,
            quantidade_inicial=50,
            quantidade_atual=50,
            status='ATIVO'
        )

        self.prod2 = Produto.objects.create(
            empresa=self.empresa,
            nome='Fita Isolante 3M',
            sku='FITA-ISO',
            ean='7895556667778'
        )

        self.cliente = Cliente.objects.create(
            empresa=self.empresa,
            nome='Carlos Alberto de Oliveira',
            cpf_cnpj='123.456.789-00',
            telefone='(11) 98765-4321',
            email='carlos.alberto@emailteste.com',
            cidade='Campinas',
            endereco='Av. Brasil 1500',
            limite_credito=1000.00
        )

    def test_api_buscar_produtos_por_qualquer_dado(self):
        self.client.force_login(self.user)

        # 1. Busca por nome
        resp = self.client.get('/api/produtos/?q=disjuntor')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['nome'], 'Disjuntor Bipolar 20A')

        # 2. Busca por SKU
        resp_sku = self.client.get('/api/produtos/?q=DISJ-20A')
        data_sku = resp_sku.json()
        self.assertEqual(len(data_sku), 1)
        self.assertEqual(data_sku[0]['id'], self.prod1.id)

        # 3. Busca por EAN (Código de barras)
        resp_ean = self.client.get('/api/produtos/?q=7891112223334')
        data_ean = resp_ean.json()
        self.assertEqual(len(data_ean), 1)
        self.assertEqual(data_ean[0]['id'], self.prod1.id)

        # 4. Busca por Categoria
        resp_cat = self.client.get('/api/produtos/?q=Elétrica')
        data_cat = resp_cat.json()
        self.assertEqual(len(data_cat), 1)
        self.assertEqual(data_cat[0]['id'], self.prod1.id)

        # 5. Busca por Localização
        resp_loc = self.client.get('/api/produtos/?q=Prateleira')
        data_loc = resp_loc.json()
        self.assertEqual(len(data_loc), 1)
        self.assertEqual(data_loc[0]['id'], self.prod1.id)

    def test_api_buscar_clientes_por_qualquer_dado(self):
        self.client.force_login(self.user)

        # 1. Busca por nome
        resp_nome = self.client.get('/api/clientes/?q=Carlos')
        data_nome = resp_nome.json()
        self.assertEqual(len(data_nome), 1)
        self.assertEqual(data_nome[0]['nome'], 'Carlos Alberto de Oliveira')

        # 2. Busca por CPF/CNPJ
        resp_cpf = self.client.get('/api/clientes/?q=123.456')
        data_cpf = resp_cpf.json()
        self.assertEqual(len(data_cpf), 1)
        self.assertEqual(data_cpf[0]['id'], self.cliente.id)

        # 3. Busca por Telefone
        resp_tel = self.client.get('/api/clientes/?q=98765')
        data_tel = resp_tel.json()
        self.assertEqual(len(data_tel), 1)
        self.assertEqual(data_tel[0]['id'], self.cliente.id)

        # 4. Busca por E-mail
        resp_email = self.client.get('/api/clientes/?q=carlos.alberto')
        data_email = resp_email.json()
        self.assertEqual(len(data_email), 1)
        self.assertEqual(data_email[0]['id'], self.cliente.id)

        # 5. Busca por Cidade
        resp_cidade = self.client.get('/api/clientes/?q=Campinas')
        data_cidade = resp_cidade.json()
        self.assertEqual(len(data_cidade), 1)
        self.assertEqual(data_cidade[0]['id'], self.cliente.id)

        # 6. Busca por Endereço
        resp_end = self.client.get('/api/clientes/?q=Brasil')
        data_end = resp_end.json()
        self.assertEqual(len(data_end), 1)
        self.assertEqual(data_end[0]['id'], self.cliente.id)

    def test_telas_renderizam_modais_de_busca(self):
        self.client.force_login(self.user)

        # Vendas / PDV
        resp_venda = self.client.get('/vendas/nova/')
        self.assertEqual(resp_venda.status_code, 200)
        self.assertContains(resp_venda, 'modalBuscarProduto')
        self.assertContains(resp_venda, 'modalBuscarCliente')

        # Saídas / Baixas
        resp_saida = self.client.get('/saidas/nova/')
        self.assertEqual(resp_saida.status_code, 200)
        self.assertContains(resp_saida, 'modalBuscaProdutoSaida')

        # Entradas
        resp_entrada = self.client.get('/estoque/nova-entrada/')
        self.assertEqual(resp_entrada.status_code, 200)
        self.assertContains(resp_entrada, 'modalBuscaProdutoEntrada')

        # Empréstimos
        resp_emp = self.client.get('/emprestimos/novo/')
        self.assertEqual(resp_emp.status_code, 200)
        self.assertContains(resp_emp, 'modalBuscaProdutoEmprestimo')

        # Simulador
        resp_sim = self.client.get('/simulador/')
        self.assertEqual(resp_sim.status_code, 200)
        self.assertContains(resp_sim, 'modalBuscaProdutoSimulador')

        # Painel Crediário
        resp_cred = self.client.get('/crediario/')
        self.assertEqual(resp_cred.status_code, 200)
        self.assertContains(resp_cred, 'modalBuscaClienteCrediario')

    def test_editar_lote_preserva_datas_fabricacao_validade(self):
        import datetime
        self.user.userprofile.e_dono = True
        self.user.userprofile.save()
        self.client.force_login(self.user)

        # Lote com datas de fabricação e validade
        lote = Lote.objects.create(
            produto=self.prod1,
            numero_lote='LT-FAB-VAL',
            preco_compra=45.00,
            quantidade_inicial=20,
            quantidade_atual=20,
            data_fabricacao=datetime.date(2026, 4, 15),
            data_validade=datetime.date(2027, 4, 15),
            status='ATIVO'
        )

        # 1. Abre a tela de edição e verifica se os inputs type="date" recebem o formato ISO YYYY-MM-DD
        resp = self.client.get(f'/estoque/editar/{lote.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'value="2026-04-15"')
        self.assertContains(resp, 'value="2027-04-15"')

        # 2. Edita apenas a quantidade ou preço (sem reenviar as datas, testando o fallback de preservação)
        resp_post = self.client.post(f'/estoque/editar/{lote.id}/', data={
            'numero_lote': 'LT-FAB-VAL',
            'quantidade_inicial': 25,
            'preco_compra': '48.00',
            'data_fabricacao': '',
            'data_validade': '',
        })
        self.assertEqual(resp_post.status_code, 302)

        lote.refresh_from_db()
        self.assertEqual(lote.quantidade_inicial, 25)
        self.assertEqual(lote.quantidade_atual, 25)
        # As datas originais foram preservadas!
        self.assertEqual(lote.data_fabricacao, datetime.date(2026, 4, 15))
        self.assertEqual(lote.data_validade, datetime.date(2027, 4, 15))


class LandingPageECadastroSaaSTestCase(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Empresa Base Landing", ativo=True)
        self.user = User.objects.create_user(
            username="dono_landing@empresa.com",
            email="dono_landing@empresa.com",
            password="SenhaForte123!@#"
        )
        self.profile = UserProfile.objects.create(
            user=self.user,
            empresa=self.empresa,
            e_dono=True
        )

    def test_landing_page_renderiza_secoes_e_modulos(self):
        resp = self.client.get('/', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "JGTECH")
        self.assertContains(resp, "Estoque & Lotes")
        self.assertContains(resp, "Frente de Caixa (PDV)")
        self.assertContains(resp, "Crediário & Clientes")
        self.assertContains(resp, "Assinatura JGTECH")
        self.assertContains(resp, "R$ 50,00")
        self.assertContains(resp, "Perguntas Frequentes")

    def test_landing_page_usuario_autenticado_mostra_atalho_painel(self):
        self.client.force_login(self.user)
        resp = self.client.get('/', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Acessar Meu Painel")

    def test_cadastro_saas_get_renderiza_formulario(self):
        resp = self.client.get('/assinar/', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Cadastre sua Empresa")
        self.assertContains(resp, "Nome da Sua Empresa")

    def test_cadastro_saas_usuario_logado_redireciona_dashboard(self):
        self.client.force_login(self.user)
        resp = self.client.get('/assinar/', HTTP_HOST='localhost')
        self.assertRedirects(resp, '/dashboard/')

    def test_cadastro_saas_cria_empresa_usuario_e_faz_login(self):
        dados = {
            'nome_completo': 'Marcos Vinicius',
            'email': 'marcos.novo@empresa.com',
            'senha': 'SenhaRobusta998!@#',
            'nome_empresa': 'Auto Pecas e Servicos Marcos'
        }
        resp = self.client.post('/assinar/', data=dados, HTTP_HOST='localhost')
        self.assertRedirects(resp, '/dashboard/')

        # Verifica se o usuário e a empresa foram criados no banco
        user_criado = User.objects.filter(email='marcos.novo@empresa.com').first()
        self.assertIsNotNone(user_criado)
        self.assertEqual(user_criado.first_name, 'Marcos Vinicius')
        self.assertTrue(user_criado.userprofile.e_dono)
        self.assertEqual(user_criado.userprofile.empresa.nome, 'Auto Pecas e Servicos Marcos')

    def test_cadastro_saas_rejeita_email_duplicado(self):
        dados = {
            'nome_completo': 'Outro Usuario',
            'email': 'dono_landing@empresa.com', # Já existente
            'senha': 'SenhaRobusta998!@#',
            'nome_empresa': 'Empresa Clone'
        }
        resp = self.client.post('/assinar/', data=dados, HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "já está cadastrado")


class ExclusaoProdutoTestCase(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome='Auto Pecas Silva')
        self.user = User.objects.create_user(username='dono_silva', email='silva@empresa.com', password='StrongPassword123!')
        UserProfile.objects.create(user=self.user, empresa=self.empresa, e_dono=True)
        self.client.force_login(self.user)

        self.produto = Produto.objects.create(
            empresa=self.empresa,
            nome='Produto Teste Venda',
            sku='TEST-001',
            estoque_minimo=3
        )
        self.lote = Lote.objects.create(
            produto=self.produto,
            numero_lote='LT-001',
            quantidade_inicial=10,
            quantidade_atual=10,
            preco_compra=20.00,
            status='ATIVO'
        )

    def test_excluir_produto_sem_vendas_sucesso(self):
        resp = self.client.post(f'/excluir/{self.produto.id}/', data={'acao': 'excluir'}, HTTP_HOST='localhost')
        self.assertRedirects(resp, '/produtos/')
        self.assertFalse(Produto.objects.filter(id=self.produto.id).exists())

    def test_inativar_produto_com_vendas(self):
        # Cria uma venda vinculada
        venda = Venda.objects.create(
            empresa=self.empresa,
            usuario=self.user,
            codigo_venda='VD-9999',
            valor_subtotal=40.00,
            valor_total=40.00,
            forma_pagamento='PIX',
            status='CONCLUIDA'
        )
        item = ItemVenda.objects.create(
            venda=venda,
            produto=self.produto,
            nome_produto=self.produto.nome,
            quantidade=2,
            preco_unitario=20.00,
            subtotal=40.00
        )

        resp = self.client.post(f'/excluir/{self.produto.id}/', data={'acao': 'inativar'}, HTTP_HOST='localhost')
        self.assertRedirects(resp, '/produtos/')

        self.produto.refresh_from_db()
        self.assertFalse(self.produto.ativo)
        self.assertTrue(ItemVenda.objects.filter(id=item.id).exists())

    def test_excluir_produto_com_vendas_preserva_historico_sem_protected_error(self):
        # Cria uma venda vinculada exatamente como o caso reportado pelo usuário
        venda = Venda.objects.create(
            empresa=self.empresa,
            usuario=self.user,
            codigo_venda='VD-9998',
            valor_subtotal=40.00,
            valor_total=40.00,
            forma_pagamento='DINHEIRO',
            status='CONCLUIDA'
        )
        item = ItemVenda.objects.create(
            venda=venda,
            produto=self.produto,
            nome_produto=self.produto.nome,
            quantidade=2,
            preco_unitario=20.00,
            subtotal=40.00
        )

        # Tenta excluir o produto: não deve gerar ProtectedError
        resp = self.client.post(f'/excluir/{self.produto.id}/', data={'acao': 'excluir'}, HTTP_HOST='localhost')
        self.assertRedirects(resp, '/produtos/')

        # Produto físico foi excluído
        self.assertFalse(Produto.objects.filter(id=self.produto.id).exists())

        # O item da venda permanece no banco com o nome preservado e produto desvinculado (SET_NULL)
        item.refresh_from_db()
        self.assertIsNone(item.produto)
        self.assertEqual(item.nome_produto, 'Produto Teste Venda')
        self.assertEqual(item.nome_exibicao, 'Produto Teste Venda')

    def test_alternar_status_produto(self):
        self.assertTrue(self.produto.ativo)
        resp = self.client.post(f'/produto/{self.produto.id}/status/', HTTP_HOST='localhost')
        self.assertRedirects(resp, '/produtos/')
        self.produto.refresh_from_db()
        self.assertFalse(self.produto.ativo)

        # Reativa
        resp = self.client.post(f'/produto/{self.produto.id}/status/', HTTP_HOST='localhost')
        self.produto.refresh_from_db()
        self.assertTrue(self.produto.ativo)


class AssinaturasSaaSTestCase(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_superuser(
            username='admin_geral',
            email='admin@saas.com',
            password='AdminPassword123!'
        )
        self.empresa = Empresa.objects.create(
            nome='Oficina Auto Pecas Express',
            status_assinatura='TRIAL',
            trial_fim=timezone.now() + timedelta(days=3),
            ativo=True
        )
        self.user_dono = User.objects.create_user(
            username='dono_express',
            email='dono@express.com',
            password='Password123!'
        )
        self.perfil = UserProfile.objects.create(
            user=self.user_dono,
            empresa=self.empresa,
            e_dono=True
        )

    def test_nova_empresa_ganha_3_dias_trial_no_cadastro(self):
        dados = {
            'nome_completo': 'Carlos Lojista',
            'email': 'carlos@novaloja.com',
            'senha': 'SenhaRobusta998!@#',
            'nome_empresa': 'Nova Loja do Carlos'
        }
        resp = self.client.post('/assinar/', data=dados, HTTP_HOST='localhost')
        self.assertRedirects(resp, '/dashboard/')

        empresa_criada = Empresa.objects.filter(nome='Nova Loja do Carlos').first()
        self.assertIsNotNone(empresa_criada)
        self.assertEqual(empresa_criada.status_assinatura, 'TRIAL')
        self.assertTrue(empresa_criada.em_trial)
        self.assertTrue(empresa_criada.assinatura_valida)
        # Deve expirar em aproximadamente 3 dias
        delta = empresa_criada.trial_fim - timezone.now()
        self.assertGreaterEqual(delta.days, 2)
        self.assertLessEqual(delta.days, 3)

    def test_nova_empresa_com_opcao_pagar_agora_redireciona_para_checkout(self):
        dados = {
            'nome_completo': 'Ana Maria Lojista',
            'email': 'ana@novaloja.com',
            'senha': 'SenhaRobusta998!@#',
            'nome_empresa': 'Loja da Ana',
            'opcao_pagamento': 'pagar_agora'
        }
        resp = self.client.post('/assinar/', data=dados, HTTP_HOST='localhost')
        self.assertRedirects(resp, '/assinatura/pagar/', fetch_redirect_response=False)
        empresa_criada = Empresa.objects.filter(nome='Loja da Ana').first()
        self.assertIsNotNone(empresa_criada)
        self.assertEqual(int(self.client.session['_auth_user_id']), empresa_criada.dono.id)

    def test_preferencia_mercadopago_exclui_boleto(self):
        from .mercadopago_service import criar_preferencia_assinatura
        from unittest.mock import patch, MagicMock
        from django.test import RequestFactory

        rf = RequestFactory()
        req = rf.get('/assinatura/pagar/')
        req.user = self.user_dono

        with patch('estoque.mercadopago_service.requests.post') as mock_post, \
             patch('estoque.mercadopago_service.settings.MERCADO_PAGO_ACCESS_TOKEN', 'TEST-TOKEN-12345'):
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.json.return_value = {
                'id': 'PREF-TEST-123',
                'checkout_url': 'https://mercadopago.com/checkout/123',
                'init_point': 'https://mercadopago.com/checkout/123'
            }
            mock_post.return_value = mock_resp

            resultado = criar_preferencia_assinatura(self.empresa, req)
            self.assertFalse(resultado['simulacao'])
            self.assertEqual(resultado['id'], 'PREF-TEST-123')

            # Verifica se o payload enviado à API do Mercado Pago excluiu ticket (boleto)
            args, kwargs = mock_post.call_args
            payload_enviado = kwargs.get('json', {})
            payment_methods = payload_enviado.get('payment_methods', {})
            excluded_types = [item['id'] for item in payment_methods.get('excluded_payment_types', [])]
            if not excluded_types and 'config' in payload_enviado:
                excluded_types = payload_enviado.get('config', {}).get('payment_method', {}).get('not_allowed_types', [])
            self.assertIn('ticket', excluded_types)

    def test_acesso_liberado_durante_trial(self):
        self.client.force_login(self.user_dono)
        resp = self.client.get('/dashboard/', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)

    def test_bloqueio_apos_expiracao_trial(self):
        # Avança o fim do teste para o passado
        self.empresa.trial_fim = timezone.now() - timedelta(hours=1)
        self.empresa.save()

        self.client.force_login(self.user_dono)
        resp = self.client.get('/dashboard/', HTTP_HOST='localhost')
        # Middleware deve interceptar e redirecionar para minha-assinatura
        self.assertRedirects(resp, '/minha-assinatura/')

        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.status_assinatura, 'VENCIDA')

    def test_superadmin_acessa_painel_superadmin_mesmo_com_empresa_vencida(self):
        # Superadministrador sempre pode acessar o painel de gestão do SaaS (/superadmin/)
        UserProfile.objects.create(user=self.superadmin, empresa=self.empresa, e_dono=True)
        self.empresa.trial_fim = timezone.now() - timedelta(days=1)
        self.empresa.status_assinatura = 'VENCIDA'
        self.empresa.save()

        self.client.force_login(self.superadmin)
        resp = self.client.get('/superadmin/assinaturas/', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)

    def test_bloqueio_empresa_com_trial_fim_nulo(self):
        # Empresas legadas ou com trial_fim nulo devem ser bloqueadas
        self.empresa.trial_fim = None
        self.empresa.status_assinatura = 'TRIAL'
        self.empresa.save()

        self.client.force_login(self.user_dono)
        resp = self.client.get('/dashboard/', HTTP_HOST='localhost')
        self.assertRedirects(resp, '/minha-assinatura/')
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.status_assinatura, 'VENCIDA')

    def test_modo_demonstracao_oculto_para_usuario_comum(self):
        from unittest.mock import patch
        with patch('estoque.mercadopago_service.settings.MERCADO_PAGO_ACCESS_TOKEN', ''):
            # Usuário comum não deve ver o card de modo demonstração
            self.client.force_login(self.user_dono)
            resp = self.client.get('/minha-assinatura/', HTTP_HOST='localhost')
            self.assertEqual(resp.status_code, 200)
            self.assertNotContains(resp, 'Modo Demonstração')
            self.assertNotContains(resp, 'Simular Aprovação de Pagamento')

            # Superadministrador deve ver o card para fins de teste
            UserProfile.objects.get_or_create(user=self.superadmin, defaults={'empresa': self.empresa, 'e_dono': False})
            self.client.force_login(self.superadmin)
            resp_admin = self.client.get('/minha-assinatura/', HTTP_HOST='localhost')
            self.assertEqual(resp_admin.status_code, 200)
            self.assertContains(resp_admin, 'Modo Demonstração')
            self.assertContains(resp_admin, 'Simular Aprovação de Pagamento')

    def test_usuario_comum_nao_pode_acessar_simular_pagamento(self):
        # Acesso direto à URL de simulação por usuário comum retorna 404
        self.client.force_login(self.user_dono)
        resp = self.client.get('/assinatura/simular-pagamento/', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 404)

    def test_processar_aprovacao_assinatura_ativa_30_dias(self):
        from .mercadopago_service import processar_aprovacao_assinatura
        self.empresa.status_assinatura = 'VENCIDA'
        self.empresa.save()

        pag = processar_aprovacao_assinatura(
            empresa=self.empresa,
            payment_id='MP-TEST-9988',
            metodo='MERCADO_PAGO',
            dias=30
        )
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.status_assinatura, 'ATIVA')
        self.assertTrue(self.empresa.assinatura_valida)
        self.assertGreater(self.empresa.assinatura_fim, timezone.now())
        self.assertEqual(pag.status, 'APROVADO')

    def test_superadmin_painel_e_acoes(self):
        self.client.force_login(self.superadmin)
        resp = self.client.get('/superadmin/assinaturas/', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Gestão de Assinaturas & Empresas SaaS")
        self.assertContains(resp, self.empresa.nome)

        # Prorroga teste por +7 dias
        resp_prorroga = self.client.post(
            f'/superadmin/empresa/{self.empresa.id}/prorrogar/',
            data={'dias': 7},
            HTTP_HOST='localhost'
        )
        self.assertRedirects(resp_prorroga, '/superadmin/assinaturas/')
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.status_assinatura, 'TRIAL')

        # Ativa manualmente por +30 dias
        resp_ativa = self.client.post(
            f'/superadmin/empresa/{self.empresa.id}/ativar/',
            data={'dias': 30},
            HTTP_HOST='localhost'
        )
        self.assertRedirects(resp_ativa, '/superadmin/assinaturas/')
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.status_assinatura, 'ATIVA')

        # Verifica se a ativação manual NÃO contabilizou faturamento (R$ 0,00)
        pag_manual = PagamentoAssinatura.objects.filter(empresa=self.empresa, metodo='MANUAL_ADMIN').first()
        self.assertIsNotNone(pag_manual)
        self.assertEqual(pag_manual.valor, Decimal('0.00'))

        resp_painel = self.client.get('/superadmin/assinaturas/', HTTP_HOST='localhost')
        self.assertEqual(resp_painel.context['receita_total'], Decimal('0.00'))

        # Bloqueia empresa
        resp_bloqueio = self.client.post(
            f'/superadmin/empresa/{self.empresa.id}/bloquear/',
            HTTP_HOST='localhost'
        )
        self.empresa.refresh_from_db()
        self.assertFalse(self.empresa.ativo)


class SegurancaAssinaturasETenantTests(TestCase):
    def setUp(self):
        self.empresa1 = Empresa.objects.create(
            nome="Empresa Segura 1",
            status_assinatura="VENCIDA",
            ativo=True
        )
        self.user1 = User.objects.create_user(
            username="user1@teste.com",
            email="user1@teste.com",
            password="SenhaForte123!@#"
        )
        self.profile1 = UserProfile.objects.create(
            user=self.user1,
            empresa=self.empresa1,
            e_dono=True
        )

        self.empresa2 = Empresa.objects.create(
            nome="Empresa Alvo 2",
            status_assinatura="VENCIDA",
            ativo=True
        )
        self.user2 = User.objects.create_user(
            username="user2@teste.com",
            email="user2@teste.com",
            password="SenhaForte123!@#"
        )
        self.profile2 = UserProfile.objects.create(
            user=self.user2,
            empresa=self.empresa2,
            e_dono=True
        )

    def test_minha_assinatura_bloqueia_ativacao_forjada_sem_confirmacao_mp(self):
        """Garante que parâmetros GET forjados (?status_mp=aprovado) NÃO ativam assinatura sem confirmação da API"""
        self.client.force_login(self.user1)
        with patch('estoque.views.is_mercadopago_configured', return_value=True), \
             patch('estoque.views.consultar_pagamento_mp', return_value=None), \
             patch('estoque.views.consultar_order_mp', return_value=None):
            
            resp = self.client.get('/minha-assinatura/?status_mp=aprovado&payment_id=FAKE123456', HTTP_HOST='localhost')
            self.assertEqual(resp.status_code, 200)

            self.empresa1.refresh_from_db()
            # Deve continuar VENCIDA e sem aprovação
            self.assertEqual(self.empresa1.status_assinatura, 'VENCIDA')
            self.assertFalse(PagamentoAssinatura.objects.filter(empresa=self.empresa1, status='APROVADO').exists())

    def test_minha_assinatura_rejeita_pagamento_de_outra_empresa(self):
        """Garante que um pagamento legítimo do Mercado Pago mas pertencente a outra empresa não pode ser usado por terceiros"""
        self.client.force_login(self.user1)
        # Simula resposta da API do Mercado Pago onde o external_reference aponta para empresa2 (não empresa1)
        fake_dados_mp = {
            'id': 888888,
            'status': 'approved',
            'external_reference': str(self.empresa2.id),
            'transaction_amount': 50.00
        }
        with patch('estoque.views.is_mercadopago_configured', return_value=True), \
             patch('estoque.views.consultar_pagamento_mp', return_value=fake_dados_mp):
            
            resp = self.client.get('/minha-assinatura/?status_mp=aprovado&payment_id=888888', HTTP_HOST='localhost')
            self.assertEqual(resp.status_code, 200)

            self.empresa1.refresh_from_db()
            # Empresa 1 NÃO pode ser ativada com comprovante da Empresa 2
            self.assertEqual(self.empresa1.status_assinatura, 'VENCIDA')

    def test_simular_pagamento_bloqueado_para_usuario_comum_quando_mp_configurado(self):
        """Garante que a rota de simulação retorna 404 quando o Mercado Pago está ativo"""
        self.client.force_login(self.user1)
        with patch('estoque.views.is_mercadopago_configured', return_value=True):
            resp = self.client.get('/assinatura/simular-pagamento/', HTTP_HOST='localhost')
            self.assertEqual(resp.status_code, 404)

    def test_sanitizacao_ids_prevenindo_path_traversal_ssrf(self):
        """Garante que IDs com caracteres maliciosos ou tentativas de traversal são barrados pelo sanitizador"""
        from .mercadopago_service import consultar_pagamento_mp, consultar_order_mp
        with patch('estoque.mercadopago_service.settings.MERCADO_PAGO_ACCESS_TOKEN', 'TOKEN-VALIDO'):
            self.assertIsNone(consultar_pagamento_mp('../../../etc/passwd'))
            self.assertIsNone(consultar_pagamento_mp('12345; DROP TABLE'))
            self.assertIsNone(consultar_order_mp('ORD<script>alert(1)</script>'))
            self.assertIsNone(consultar_order_mp('../../v1/oauth'))

    def test_webhook_rejeita_payload_excessivo_e_id_invalido(self):
        """Garante que o Webhook rejeita payloads maiores que 64KB e IDs malformados"""
        # Payload > 64KB
        payload_gigante = b'{"dados": "' + (b'A' * 70000) + b'"}'
        resp = self.client.post('/api/mercadopago/webhook/', data=payload_gigante, content_type='application/json', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 400)

        # ID malformado com path traversal
        resp_id_invalido = self.client.post('/api/mercadopago/webhook/?id=../../malicioso', HTTP_HOST='localhost')
        self.assertEqual(resp_id_invalido.status_code, 400)

    def test_idempotencia_processar_aprovacao_assinatura(self):
        """Garante que múltiplos processamentos com mesmo ID não duplicam a vigência de dias"""
        from .mercadopago_service import processar_aprovacao_assinatura
        p1 = processar_aprovacao_assinatura(
            empresa=self.empresa1,
            payment_id='PAY-IDEMP-001',
            preference_id='PREF-IDEMP-001',
            dias=30
        )
        self.empresa1.refresh_from_db()
        fim_inicial = self.empresa1.assinatura_fim

        # Segunda chamada idêntica
        p2 = processar_aprovacao_assinatura(
            empresa=self.empresa1,
            payment_id='PAY-IDEMP-001',
            preference_id='PREF-IDEMP-001',
            dias=30
        )
        self.empresa1.refresh_from_db()
        # Data de vigência deve permanecer inalterada (30 dias, e não 60 dias)
        self.assertEqual(self.empresa1.assinatura_fim, fim_inicial)
        self.assertEqual(PagamentoAssinatura.objects.filter(empresa=self.empresa1, status='APROVADO').count(), 1)

    def test_idempotencia_cruzada_webhook_e_retorno_mp(self):
        """
        Garante que notificações concorrentes com IDs correlacionados (Merchant Order,
        Payment e Preference ID) unificam o registro e NUNCA duplicam a vigência de dias.
        """
        from .mercadopago_service import processar_aprovacao_assinatura
        # 1. Cria pendência como no início do checkout
        PagamentoAssinatura.objects.create(
            empresa=self.empresa1,
            valor=Decimal('50.00'),
            metodo='MERCADO_PAGO',
            status='PENDENTE',
            mp_preference_id='PREF-TEST-XYZ-123'
        )

        # 2. Primeira notificação (Webhook de Merchant Order)
        p1 = processar_aprovacao_assinatura(
            empresa=self.empresa1,
            payment_id='180707030360',
            preference_id='PREF-TEST-XYZ-123',
            order_id='180707030360',
            dias=30
        )
        self.empresa1.refresh_from_db()
        fim_esperado = self.empresa1.assinatura_fim

        # 3. Segunda notificação (Webhook de Payment com payment_id real e order_id)
        p2 = processar_aprovacao_assinatura(
            empresa=self.empresa1,
            payment_id='44709047309',
            preference_id=None,
            order_id='180707030360',
            dias=30
        )

        # 4. Terceira chamada (Redirecionamento do comprador com payment_id e preference_id)
        p3 = processar_aprovacao_assinatura(
            empresa=self.empresa1,
            payment_id='44709047309',
            preference_id='PREF-TEST-XYZ-123',
            order_id=None,
            dias=30
        )

        self.empresa1.refresh_from_db()
        # Não pode ter concedido 60 ou 90 dias, exatamente 30 dias
        self.assertEqual(self.empresa1.assinatura_fim, fim_esperado)

        # Apenas 1 registro aprovado existente
        aprovados = PagamentoAssinatura.objects.filter(empresa=self.empresa1, status='APROVADO')
        self.assertEqual(aprovados.count(), 1)

        registro = aprovados.first()
        self.assertEqual(registro.mp_payment_id, '44709047309')
        self.assertEqual(registro.mp_order_id, '180707030360')
        self.assertEqual(registro.mp_preference_id, 'PREF-TEST-XYZ-123')

    def test_get_empresa_usuario_com_anonymous_user(self):
        """Garante que AnonymousUser não gera exceção nem vaza contexto"""
        from django.contrib.auth.models import AnonymousUser
        from .views import get_empresa_usuario
        anon = AnonymousUser()
        self.assertIsNone(get_empresa_usuario(anon))
        self.assertIsNone(get_empresa_usuario(None))

    def test_imprimir_cupom_venda_sucesso(self):
        """Garante que a visualização do cupom térmico renderiza perfeitamente os dados da venda"""
        self.empresa1.status_assinatura = 'ATIVA'
        self.empresa1.assinatura_fim = timezone.now() + timedelta(days=30)
        self.empresa1.save()

        venda = Venda.objects.create(
            empresa=self.empresa1,
            codigo_venda="VD-TEST-998877",
            usuario=self.user1,
            valor_subtotal=100.00,
            desconto=10.00,
            valor_total=90.00,
            forma_pagamento='PIX',
            status='CONCLUIDA',
            status_pagamento='PAGO'
        )

        self.client.force_login(self.user1)
        resp = self.client.get(f'/vendas/{venda.pk}/cupom/', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'estoque/cupom_venda.html')
        self.assertContains(resp, "COMPROVANTE NÃO FISCAL")
        self.assertContains(resp, self.empresa1.nome.upper())
        self.assertContains(resp, "VD-TEST-998877")
        self.assertContains(resp, "R$ 90,00")
        self.assertNotContains(resp, "OPERADOR:")
        self.assertNotContains(resp, "STATUS:")

    def test_imprimir_cupom_venda_isolamento_multitenant(self):
        """Garante que um usuário não pode imprimir cupom térmico de outra empresa (retorna 404)"""
        self.empresa1.status_assinatura = 'ATIVA'
        self.empresa1.assinatura_fim = timezone.now() + timedelta(days=30)
        self.empresa1.save()

        venda_empresa2 = Venda.objects.create(
            empresa=self.empresa2,
            codigo_venda="VD-ALVO-123456",
            usuario=self.user2,
            valor_subtotal=50.00,
            valor_total=50.00,
            forma_pagamento='DINHEIRO',
            status='CONCLUIDA'
        )

        self.client.force_login(self.user1)
        resp = self.client.get(f'/vendas/{venda_empresa2.pk}/cupom/', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 404)


class TabelaPrecosTestCase(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome='Empresa Precificacao',
            cnpj='99.888.777/0001-66',
            status_assinatura='ATIVA',
            assinatura_fim=timezone.now() + timedelta(days=30)
        )
        self.user = User.objects.create_user(username='gestor_precos', password='password123')
        self.perfil = UserProfile.objects.create(user=self.user, empresa=self.empresa, e_dono=True)

    def test_produto_padrao_nao_disponivel_para_venda(self):
        """Por padrão todos os itens não são destinados à venda (disponivel_venda=False, preco_venda=0.00)"""
        produto = Produto.objects.create(
            empresa=self.empresa,
            nome='Item Insumo Padrão'
        )
        self.assertFalse(produto.disponivel_venda)
        self.assertEqual(float(produto.preco_venda), 0.0)

    def test_produto_criacao_com_preco_registra_historico(self):
        """Ao cadastrar produto com preço de venda, um registro em HistoricoPreco é criado"""
        self.client.force_login(self.user)
        resp = self.client.post('/novo/', {
            'nome': 'Produto Novo Para Venda',
            'unidade': 'UN',
            'estoque_minimo': 5,
            'controla_lote': True,
            'disponivel_venda': True,
            'preco_venda': '49.90',
        }, HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 302)

        produto = Produto.objects.get(empresa=self.empresa, nome='Produto Novo Para Venda')
        self.assertTrue(produto.disponivel_venda)
        self.assertEqual(float(produto.preco_venda), 49.90)

        historico = HistoricoPreco.objects.filter(produto=produto)
        self.assertEqual(historico.count(), 1)
        h = historico.first()
        self.assertEqual(float(h.preco_anterior), 0.0)
        self.assertEqual(float(h.preco_novo), 49.90)
        self.assertEqual(h.usuario, self.user)

    def test_produto_edicao_preco_registra_novo_historico(self):
        """Ao editar o preço de venda de um produto, novo registro de histórico é criado"""
        produto = Produto.objects.create(
            empresa=self.empresa,
            nome='Produto Alteracao',
            disponivel_venda=True,
            preco_venda=30.00
        )
        HistoricoPreco.objects.create(
            empresa=self.empresa,
            produto=produto,
            preco_anterior=0.00,
            preco_novo=30.00,
            usuario=self.user,
            motivo="Inicial"
        )

        self.client.force_login(self.user)
        resp = self.client.post(f'/editar/{produto.pk}/', {
            'nome': 'Produto Alteracao',
            'unidade': 'UN',
            'estoque_minimo': 5,
            'controla_lote': True,
            'disponivel_venda': True,
            'preco_venda': '45.00',
        }, HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 302)

        produto.refresh_from_db()
        self.assertEqual(float(produto.preco_venda), 45.00)

        historico = HistoricoPreco.objects.filter(produto=produto).order_by('-data_alteracao')
        self.assertEqual(historico.count(), 2)
        mais_recente = historico.first()
        self.assertEqual(float(mais_recente.preco_anterior), 30.00)
        self.assertEqual(float(mais_recente.preco_novo), 45.00)

    def test_calculo_margem_e_markup(self):
        """Garante a precisão das properties margem_lucro, markup e lucro_unitario"""
        produto = Produto.objects.create(
            empresa=self.empresa,
            nome='Produto Margens',
            disponivel_venda=True,
            preco_venda=100.00
        )
        Lote.objects.create(
            produto=produto,
            numero_lote='LOTE-01',
            preco_compra=60.00,
            quantidade_inicial=10,
            quantidade_atual=10,
            status='ATIVO'
        )

        # Custo = 60.00, Venda = 100.00
        # Margem = ((100 - 60) / 100) * 100 = 40.0%
        # Markup = ((100 - 60) / 60) * 100 = 66.67%
        # Lucro Unitário = 40.00
        self.assertEqual(produto.preco_medio, 60.00)
        self.assertEqual(produto.margem_lucro, 40.0)
        self.assertEqual(produto.markup, 66.67)
        self.assertEqual(produto.lucro_unitario, 40.00)

    def test_tabela_precos_view_carrega_com_sucesso(self):
        """Garante que a rota /tabela-precos/ responde 200 e lista estritamente produtos para venda"""
        p_venda = Produto.objects.create(empresa=self.empresa, nome='Item Venda 1', disponivel_venda=True, preco_venda=25.00)
        p_insumo = Produto.objects.create(empresa=self.empresa, nome='Item Insumo 2', disponivel_venda=False, preco_venda=0.00)

        self.client.force_login(self.user)
        resp = self.client.get('/tabela-precos/', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        # Na tabela de preços (page_obj), apenas p_venda deve constar
        self.assertEqual(list(resp.context['page_obj']), [p_venda])
        self.assertContains(resp, 'Item Venda 1')
        self.assertContains(resp, 'Tabela de Preços de Venda')
        # O insumo consta no select de inclusão de novos itens na tabela
        self.assertIn(p_insumo, resp.context['produtos_insumo'])

    def test_lista_produtos_filtro_venda_e_insumo(self):
        """Testa filtros de itens de venda e insumo na tela de estoque geral"""
        p_venda = Produto.objects.create(empresa=self.empresa, nome='Cabo de Rede Para Venda', disponivel_venda=True, preco_venda=50.00)
        p_insumo = Produto.objects.create(empresa=self.empresa, nome='Chave Phillips Insumo', disponivel_venda=False, preco_venda=0.00)

        self.client.force_login(self.user)

        # Filtro tipo=venda
        resp_venda = self.client.get('/produtos/?tipo=venda', HTTP_HOST='localhost')
        self.assertEqual(resp_venda.status_code, 200)
        self.assertContains(resp_venda, 'Cabo de Rede Para Venda')
        self.assertNotContains(resp_venda, 'Chave Phillips Insumo')

        # Filtro tipo=insumo
        resp_insumo = self.client.get('/produtos/?tipo=insumo', HTTP_HOST='localhost')
        self.assertEqual(resp_insumo.status_code, 200)
        self.assertContains(resp_insumo, 'Chave Phillips Insumo')
        self.assertNotContains(resp_insumo, 'Cabo de Rede Para Venda')

    def test_atualizar_preco_produto_api(self):
        """API de atualização rápida de preço atualiza o produto e registra histórico"""
        produto = Produto.objects.create(
            empresa=self.empresa,
            nome='Produto API Preco',
            disponivel_venda=False,
            preco_venda=0.00
        )

        self.client.force_login(self.user)
        resp = self.client.post(f'/api/produto/{produto.pk}/atualizar-preco/', {
            'preco_venda': '88.50',
            'disponivel_venda': 'true',
            'motivo': 'Ajuste via teste automatizado'
        }, HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['preco_venda'], '88.50')
        self.assertTrue(data['disponivel_venda'])

        produto.refresh_from_db()
        self.assertEqual(float(produto.preco_venda), 88.50)
        self.assertTrue(produto.disponivel_venda)

        historico = HistoricoPreco.objects.filter(produto=produto)
        self.assertEqual(historico.count(), 1)
        self.assertEqual(float(historico.first().preco_novo), 88.50)
        self.assertEqual(historico.first().motivo, 'Ajuste via teste automatizado')

    def test_api_historico_precos(self):
        """API retorna lista de registros de histórico do produto"""
        produto = Produto.objects.create(
            empresa=self.empresa,
            nome='Produto Historico API',
            preco_venda=120.00
        )
        HistoricoPreco.objects.create(
            empresa=self.empresa,
            produto=produto,
            preco_anterior=100.00,
            preco_novo=120.00,
            usuario=self.user,
            motivo="Reajuste fornecedor"
        )

        self.client.force_login(self.user)
        resp = self.client.get(f'/api/produto/{produto.pk}/historico-precos/', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(len(data['historico']), 1)
        self.assertEqual(data['historico'][0]['preco_anterior'], '100.00')
        self.assertEqual(data['historico'][0]['preco_novo'], '120.00')

    def test_historico_produto_view_and_properties(self):
        """Testa a view historico_produto, context variables, KPIs e propriedades de modelo"""
        produto = Produto.objects.create(
            empresa=self.empresa,
            nome='Teclado Mecânico RGB',
            sku='TEC-001',
            disponivel_venda=True,
            preco_venda=Decimal('150.00'),
            estoque_minimo=10
        )
        # 1. Entrada de Lote
        lote = Lote.objects.create(
            produto=produto,
            numero_lote='LOTE-2026-A',
            preco_compra=Decimal('80.00'),
            quantidade_inicial=20,
            quantidade_atual=15,
            status='ATIVO'
        )
        self.assertEqual(lote.custo_total, Decimal('1600.00'))

        # 2. Saída / Venda
        saida = SaidaEstoque.objects.create(
            produto=produto,
            quantidade=5,
            motivo='Venda PDV #1001',
            usuario=self.user,
            valor_venda=Decimal('150.00'),
            lote=lote
        )
        self.assertEqual(saida.subtotal, Decimal('750.00'))

        # 3. Alteração de Preço
        hp = HistoricoPreco.objects.create(
            empresa=self.empresa,
            produto=produto,
            preco_anterior=Decimal('120.00'),
            preco_novo=Decimal('150.00'),
            usuario=self.user,
            motivo="Reajuste inflacionário"
        )
        self.assertEqual(hp.variacao_valor, Decimal('30.00'))
        self.assertEqual(hp.variacao_percentual, 25.0)

        # 4. Requisição à View historico_produto
        self.client.force_login(self.user)
        response = self.client.get(reverse('historico_produto', args=[produto.pk]), HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200)

        # Verifica dados no contexto
        self.assertIn('chart_labels_json', response.context)
        self.assertIn('chart_custo_json', response.context)
        self.assertIn('chart_venda_json', response.context)
        self.assertIn('chart_tabela_json', response.context)
        self.assertIn('total_investido', response.context)
        self.assertIn('total_faturado', response.context)
        self.assertIn('custo_medio', response.context)
        self.assertIn('margem_atual', response.context)
        self.assertIn('markup_atual', response.context)
        self.assertIn('lucro_unitario', response.context)

        self.assertEqual(response.context['total_entradas_qtd'], 20)
        self.assertEqual(response.context['total_saidas_qtd'], 5)
        self.assertEqual(response.context['total_investido'], 1600.0)
        self.assertEqual(response.context['total_faturado'], 750.0)
        self.assertEqual(response.context['custo_medio'], 80.0)
        self.assertEqual(response.context['lucro_unitario'], 70.0)

        # Verifica conteúdo renderizado no HTML
        content = response.content.decode('utf-8')
        self.assertIn('Teclado Mecânico RGB', content)
        self.assertIn('TEC-001', content)
        self.assertIn('Painel Gráfico de Inteligência de Estoque', content)
        self.assertIn('Evolução de Preços (R$)', content)
        self.assertIn('Fluxo de Movimentação (Qtd)', content)
        self.assertIn('LOTE-2026-A', content)
        self.assertIn('Venda PDV #1001', content)
        self.assertIn('Reajuste inflacionário', content)


class SimuladorPrecoMultiImpostosTestCase(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome='Empresa Simulador',
            cnpj='11.222.333/0001-44',
            status_assinatura='ATIVA',
            assinatura_fim=timezone.now() + timedelta(days=30)
        )
        self.user = User.objects.create_user(username='gestor_simulador', password='password123')
        self.perfil = UserProfile.objects.create(user=self.user, empresa=self.empresa, e_dono=True)
        self.client.force_login(self.user)

        self.produto = Produto.objects.create(
            empresa=self.empresa,
            nome='Smartphone Pro Max',
            sku='PHONE-001',
            disponivel_venda=True,
            preco_venda=Decimal('2500.00')
        )
        self.lote = Lote.objects.create(
            produto=self.produto,
            numero_lote='LT-PHONE-01',
            preco_compra=Decimal('1000.00'),
            quantidade_inicial=10,
            quantidade_atual=10,
            status='ATIVO'
        )

        self.aliq_icms = AliquotaImposto.objects.create(
            empresa=self.empresa,
            nome='ICMS',
            percentual=Decimal('18.00')
        )
        self.aliq_pis = AliquotaImposto.objects.create(
            empresa=self.empresa,
            nome='PIS',
            percentual=Decimal('1.65')
        )
        self.aliq_cofins = AliquotaImposto.objects.create(
            empresa=self.empresa,
            nome='COFINS',
            percentual=Decimal('7.60')
        )

    def test_simulador_view_renderiza_multi_impostos(self):
        """Garante que a tela do simulador de preços carrega os elementos de seleção múltipla de impostos"""
        resp = self.client.get('/simulador/', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'containerListaImpostos')
        self.assertContains(resp, 'badgeCargaTributariaTotal')
        self.assertContains(resp, 'btnLimparImpostos')
        self.assertContains(resp, 'ICMS')
        self.assertContains(resp, 'PIS')
        self.assertContains(resp, 'COFINS')

    def test_criar_e_excluir_aliquota_api(self):
        """Testa criação e exclusão de alíquotas via API AJAX"""
        resp_cria = self.client.post('/api/aliquotas/criar/', {
            'nome': 'ISSQN Serviços',
            'percentual': '5.00'
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest', HTTP_HOST='localhost')
        self.assertEqual(resp_cria.status_code, 200)
        data = resp_cria.json()
        self.assertEqual(data['status'], 'success')
        aliq_id = data['id']

        aliq = AliquotaImposto.objects.get(id=aliq_id, empresa=self.empresa)
        self.assertEqual(aliq.nome, 'ISSQN Serviços')
        self.assertEqual(float(aliq.percentual), 5.0)

        # Excluir
        resp_del = self.client.post(f'/api/aliquotas/excluir/{aliq_id}/', HTTP_X_REQUESTED_WITH='XMLHttpRequest', HTTP_HOST='localhost')
        self.assertEqual(resp_del.status_code, 200)
        self.assertFalse(AliquotaImposto.objects.filter(id=aliq_id).exists())

    def test_salvar_simulacao_com_multiplos_impostos(self):
        """Testa salvar simulação no banco com múltiplos impostos agregados"""
        payload = {
            'produto_id': self.produto.id,
            'preco_custo': 100.00,
            'quantidade_estoque': 10,
            'preco_custo_futuro': '',
            'quantidade_futura': '',
            'frete_valor': 10.00,
            'tipo_frete': 'valor',
            'outros_valor': 0,
            'tipo_outros': 'valor',
            'aliquota_nome': 'ICMS (18.00%) + PIS (1.65%) + COFINS (7.60%)',
            'aliquota_percentual': 27.25,
            'margem_desejada': 20.00,
            'metodo': 'inside',
            'preco_sugerido': 208.53,
            'preco_praticado': 210.00,
            'lucro_liquido': 42.78,
            'margem_realizada': 20.37
        }

        resp = self.client.post(
            '/api/simulacoes/salvar/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            HTTP_HOST='localhost'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'success')

        simulacao = SimulacaoPreco.objects.get(id=data['id'], empresa=self.empresa)
        self.assertEqual(simulacao.produto, self.produto)
        self.assertEqual(simulacao.aliquota_nome, 'ICMS (18.00%) + PIS (1.65%) + COFINS (7.60%)')
        self.assertEqual(float(simulacao.aliquota_percentual), 27.25)
        self.assertEqual(float(simulacao.preco_praticado), 210.00)

    def test_simulador_pdf_com_multiplos_impostos(self):
        """Testa geração de relatório PDF com detalhamento de múltiplos impostos"""
        aliquotas_ids = f"{self.aliq_icms.id},{self.aliq_pis.id},{self.aliq_cofins.id}"
        url = (
            f"/simulador/pdf/?produto_id={self.produto.id}"
            f"&preco_custo=100.00&quantidade_estoque=10"
            f"&frete_valor=0&tipo_frete=valor&outros_valor=0&tipo_outros=valor"
            f"&aliquotas_ids={aliquotas_ids}&margem_desejada=20"
            f"&metodo=inside&preco_praticado=200.00"
        )
        resp = self.client.get(url, HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'ICMS')
        self.assertContains(resp, 'PIS')
        self.assertContains(resp, 'COFINS')
        self.assertContains(resp, 'Total de Impostos')
        self.assertContains(resp, '27,25%')
        self.assertContains(resp, 'Markup Realizado')

    def test_regras_matematicas_precificacao_negocio(self):
        """
        Validação matemática rigorosa das fórmulas comerciais:
        1. Custo Efetivo: C = 100.00
        2. Impostos Acumulados (ICMS 18% + PIS 1.65% + COFINS 7.60%): I = 27.25%
        3. Margem Desejada: M = 20.00%
        """
        custo = 100.00
        imposto_pct = 27.25
        margem_pct = 20.00

        # MARKUP DIVISOR (Inside - Margem sobre Faturamento Bruto)
        # Preço Sugerido = Custo / (1 - (I% + M%)) = 100 / (1 - 0.4725) = 100 / 0.5275 = 189.57
        divisor_divisor = (100 - (imposto_pct + margem_pct)) / 100
        preco_sugerido_divisor = round(custo / divisor_divisor, 2)
        self.assertEqual(preco_sugerido_divisor, 189.57)

        # Se praticar 189.57:
        imposto_val = round(preco_sugerido_divisor * (imposto_pct / 100), 2)
        receita_liquida = round(preco_sugerido_divisor - imposto_val, 2)
        lucro_liquido = round(receita_liquida - custo, 2)
        margem_realizada = round((lucro_liquido / preco_sugerido_divisor) * 100, 2)
        # 189.57 * 0.2725 = 51.66
        # Receita Líquida = 189.57 - 51.66 = 137.91
        # Lucro = 137.91 - 100.00 = 37.91
        # Margem = 37.91 / 189.57 = 19.998% (~20.0%)
        self.assertAlmostEqual(margem_realizada, 20.0, places=1)

        # MARKUP MULTIPLICADOR (Sobre Custo com Gross-Up Tributário)
        # Preço Sugerido = (Custo * (1 + M%)) / (1 - I%) = (100 * 1.20) / (1 - 0.2725) = 120 / 0.7275 = 164.95
        divisor_multiplicador = (100 - imposto_pct) / 100
        preco_sugerido_multiplicador = round((custo * (1 + margem_pct / 100)) / divisor_multiplicador, 2)
        self.assertEqual(preco_sugerido_multiplicador, 164.95)

        # Se praticar 164.95:
        imposto_val_mult = round(preco_sugerido_multiplicador * (imposto_pct / 100), 2)
        receita_liquida_mult = round(preco_sugerido_multiplicador - imposto_val_mult, 2)
        lucro_liquido_mult = round(receita_liquida_mult - custo, 2)
        markup_realizado = round((lucro_liquido_mult / custo) * 100, 2)
        # 164.95 * 0.2725 = 44.95
        # Receita Líquida = 164.95 - 44.95 = 120.00
        # Lucro = 120.00 - 100.00 = 20.00
        # Markup = 20.00 / 100.00 = 20.0%
        self.assertEqual(markup_realizado, 20.0)

        # PONTO DE EQUILÍBRIO (Preço Mínimo para Lucro = 0)
        # Preço Mínimo = Custo / (1 - I%) = 100 / 0.7275 = 137.46
        preco_equilibrio = round(custo / divisor_multiplicador, 2)
        self.assertEqual(preco_equilibrio, 137.46)
        imposto_eq = round(preco_equilibrio * (imposto_pct / 100), 2)
        receita_liq_eq = round(preco_equilibrio - imposto_eq, 2)
        lucro_eq = round(receita_liq_eq - custo, 2)
        self.assertEqual(lucro_eq, 0.0)


class BackupSystemTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_superuser(
            username='admin_backup',
            email='admin@backup.com',
            password='AdminPassword123!'
        )
        self.empresa = Empresa.objects.create(
            nome='Empresa Backup Teste',
            status_assinatura='ATIVA',
            assinatura_fim=timezone.now() + timedelta(days=30)
        )
        self.user_comum = User.objects.create_user(
            username='usuario_comum',
            email='comum@backup.com',
            password='Password123!'
        )
        self.perfil = UserProfile.objects.create(
            user=self.user_comum,
            empresa=self.empresa,
            e_dono=False
        )

    def test_bloqueio_acesso_painel_backups_usuario_nao_superadmin(self):
        self.client.force_login(self.user_comum)
        resp = self.client.get('/backups/', HTTP_HOST='localhost')
        self.assertRedirects(resp, '/dashboard/')

    def test_acesso_liberado_painel_backups_superadmin(self):
        self.client.force_login(self.superadmin)
        resp = self.client.get('/backups/', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Gerenciador de Backups')
        self.assertContains(resp, 'Restaurar Backup do Computador')

    def test_criar_backup_requer_superadmin(self):
        self.client.force_login(self.user_comum)
        resp = self.client.post('/backups/criar/', HTTP_HOST='localhost')
        self.assertRedirects(resp, '/dashboard/')

    def test_restaurar_backup_upload_bloqueio_nao_superadmin(self):
        self.client.force_login(self.user_comum)
        arquivo = SimpleUploadedFile("backup.json", b"[]", content_type="application/json")
        resp = self.client.post('/backups/restaurar-upload/', {'arquivo_backup': arquivo}, HTTP_HOST='localhost')
        self.assertRedirects(resp, '/dashboard/')

    def test_restaurar_backup_upload_rejeita_arquivo_invalido(self):
        self.client.force_login(self.superadmin)
        # 1. Arquivo não .json
        arquivo_txt = SimpleUploadedFile("backup.txt", b"conteudo de texto", content_type="text/plain")
        resp = self.client.post('/backups/restaurar-upload/', {'arquivo_backup': arquivo_txt}, HTTP_HOST='localhost')
        self.assertRedirects(resp, '/backups/')

        # 2. JSON malformado
        arquivo_corrompido = SimpleUploadedFile("backup.json", b"{corrompido: true", content_type="application/json")
        resp2 = self.client.post('/backups/restaurar-upload/', {'arquivo_backup': arquivo_corrompido}, HTTP_HOST='localhost')
        self.assertRedirects(resp2, '/backups/')

    def test_restaurar_backup_upload_valido_sucesso(self):
        self.client.force_login(self.superadmin)
        # Cria uma fixture JSON válida do Django para uma categoria
        fixture_data = [
            {
                "model": "estoque.categoria",
                "pk": 8888,
                "fields": {
                    "empresa": self.empresa.id,
                    "nome": "Categoria Restaurada Via Upload"
                }
            }
        ]
        conteudo = json.dumps(fixture_data).encode('utf-8')
        arquivo_valido = SimpleUploadedFile("backup_valido.json", conteudo, content_type="application/json")

        resp = self.client.post('/backups/restaurar-upload/', {'arquivo_backup': arquivo_valido}, HTTP_HOST='localhost')
        self.assertRedirects(resp, '/backups/')

        # Confirma que a categoria foi restaurada no banco
        self.assertTrue(Categoria.objects.filter(id=8888, nome="Categoria Restaurada Via Upload").exists())


class MercadoPagoRequisitosHomologacaoTestCase(TestCase):
    """
    Testes unitários para validar todos os requisitos e recomendações
    do Checklist de Homologação e Qualidade do Mercado Pago.
    """
    def setUp(self):
        self.user = User.objects.create_user(
            username='comprador_teste',
            first_name='Carlos',
            last_name='Silva',
            email='carlos.silva@teste.com'
        )
        self.empresa = Empresa.objects.create(
            nome='JG Comércio e TI',
            cnpj='12.345.678/0001-99'
        )
        UserProfile.objects.create(
            user=self.user,
            empresa=self.empresa,
            e_dono=True
        )

    @patch('mercadopago.SDK')
    def test_preference_payload_completo_requisitos(self, mock_sdk_class):
        from django.test import RequestFactory
        from estoque.mercadopago_service import criar_preferencia_assinatura

        mock_sdk_instance = MagicMock()
        mock_sdk_class.return_value = mock_sdk_instance
        mock_pref = MagicMock()
        mock_sdk_instance.preference.return_value = mock_pref
        mock_pref.create.return_value = {
            'status': 201,
            'response': {
                'id': '3707862372-test-pref-id',
                'init_point': 'https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=3707862372-test-pref-id',
                'sandbox_init_point': 'https://sandbox.mercadopago.com.br/checkout/v1/redirect?pref_id=3707862372-test-pref-id'
            }
        }

        rf = RequestFactory()
        request = rf.get('/minha-assinatura/', SERVER_NAME='localhost')
        request.user = self.user

        resultado = criar_preferencia_assinatura(self.empresa, request)

        self.assertFalse(resultado['simulacao'])
        self.assertEqual(resultado['id'], '3707862372-test-pref-id')
        self.assertEqual(resultado['init_point'], 'https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=3707862372-test-pref-id')

        # Verifica chamada ao SDK
        mock_pref.create.assert_called_once()
        payload_enviado = mock_pref.create.call_args[0][0]

        # 1. Config / Statement Descriptor (+12 pontos)
        self.assertEqual(payload_enviado['statement_descriptor'], 'JGTECH')
        self.assertEqual(payload_enviado['config']['statement_descriptor'], 'JGTECH')

        # 2. Payer: Nome (+5 pts) e Sobrenome (+5 pts)
        self.assertEqual(payload_enviado['payer']['first_name'], 'Carlos')
        self.assertEqual(payload_enviado['payer']['last_name'], 'Silva')
        self.assertEqual(payload_enviado['payer']['email'], 'carlos.silva@teste.com')

        # 3. Payer: Identificação (+5 pts)
        self.assertIn('identification', payload_enviado['payer'])
        self.assertEqual(payload_enviado['payer']['identification']['type'], 'CNPJ')
        self.assertEqual(payload_enviado['payer']['identification']['number'], '12345678000199')

        # 4. Payer: Telefone (Boa prática)
        self.assertIn('phone', payload_enviado['payer'])
        self.assertIn('area_code', payload_enviado['payer']['phone'])
        self.assertIn('number', payload_enviado['payer']['phone'])

        # 5. Additional Info Antifraude: data_reg (+1 pt), primeira_compra, auth_type
        self.assertIn('additional_info', payload_enviado)
        self.assertIn('payer', payload_enviado['additional_info'])
        add_payer = payload_enviado['additional_info']['payer']
        self.assertIn('registration_date', add_payer)
        self.assertTrue(add_payer['is_first_purchase_online'])
        self.assertEqual(add_payer['authentication_type'], 'native')

        # 6. Items: category_id (+2 pts), description (+5 pts), external_code
        item = payload_enviado['items'][0]
        self.assertEqual(item['category_id'], 'services')
        self.assertEqual(item['external_code'], f'ASSINATURA-JGTECH-{self.empresa.id}')
        self.assertIn('JGTECH', item['description'])

        # 7. Exclusão de boleto (apenas Pix e Cartões)
        excluidos = [x['id'] for x in payload_enviado['payment_methods']['excluded_payment_types']]
        self.assertIn('ticket', excluidos)

    @patch('mercadopago.SDK')
    def test_gerar_order_homologacao_mp_via_sdk(self, mock_sdk_class):
        mock_sdk_instance = MagicMock()
        mock_sdk_class.return_value = mock_sdk_instance
        mock_order = MagicMock()
        mock_sdk_instance.order.return_value = mock_order

        mock_order.create.return_value = {
            'status': 201,
            'response': {
                'id': 'ORDTST01MTESTE123',
                'checkout_url': 'https://www.mercadopago.com.br/checkout/v1/redirect?order_id=ORDTST01MTESTE123'
            }
        }

        from estoque.mercadopago_service import gerar_order_homologacao_mp
        res = gerar_order_homologacao_mp(self.empresa)
        self.assertIsNotNone(res)
        self.assertEqual(res['id'], 'ORDTST01MTESTE123')
        self.assertIn('ORDTST01MTESTE123', res['checkout_url'])

        mock_order.create.assert_called_once()
        payload = mock_order.create.call_args[0][0]
        self.assertEqual(payload['config']['statement_descriptor'], 'JGTECH')
        self.assertEqual(payload['items'][0]['category_id'], 'services')

    def test_salvar_order_id_pagamento_superadmin(self):
        """Garante que o superadmin consegue salvar o Order ID completo no pagamento"""
        superuser = User.objects.create_superuser('admin_saas', 'admin@teste.com', 'pass1234')
        pag = PagamentoAssinatura.objects.create(
            empresa=self.empresa,
            valor=Decimal('50.00'),
            metodo='MERCADO_PAGO',
            status='PENDENTE',
            mp_preference_id='PREF-TEMP-123'
        )
        self.assertIsNone(pag.mp_order_id)
        self.assertIsNone(pag.order_id_exibicao)

        url = f"/superadmin/pagamento/{pag.id}/salvar-order-id/"
        full_order_id = "ORDTST01M3A2C8WFYB52ARVXW4G3Y6D5"

        # Usuário comum não pode salvar (404)
        self.client.force_login(self.user)
        resp_comum = self.client.post(url, {'order_id': full_order_id})
        self.assertEqual(resp_comum.status_code, 404)

        # Superuser salva o Order ID no formato completo
        self.client.force_login(superuser)
        resp = self.client.post(url, {'order_id': full_order_id})
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, '/superadmin/assinaturas/')

        pag.refresh_from_db()
        self.assertEqual(pag.mp_order_id, full_order_id)
        self.assertEqual(pag.order_id_exibicao, full_order_id)

    def test_processar_aprovacao_persiste_mp_order_id(self):
        """Garante que processar_aprovacao_assinatura salva o Order ID informado"""
        from estoque.mercadopago_service import processar_aprovacao_assinatura
        order_id_teste = "ORDTST01M3A2C8WFYB52ARVXW4G3Y6D5"
        pag = processar_aprovacao_assinatura(
            empresa=self.empresa,
            payment_id="179671490547",
            preference_id=order_id_teste,
            order_id=order_id_teste,
            metodo='MERCADO_PAGO',
            valor=Decimal('50.00')
        )
        self.assertEqual(pag.mp_order_id, order_id_teste)
        self.assertEqual(pag.order_id_exibicao, order_id_teste)
        self.assertEqual(pag.mp_payment_id, "179671490547")
