import json
import logging
import re
from decimal import Decimal
from datetime import timedelta
import uuid
import hmac
import hashlib
import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from .models import Empresa, PagamentoAssinatura

logger = logging.getLogger(__name__)

MERCADO_PAGO_API_URL = "https://api.mercadopago.com"
VALOR_ASSINATURA_PADRAO = Decimal('50.00')


def is_mercadopago_configured():
    token = getattr(settings, 'MERCADO_PAGO_ACCESS_TOKEN', '')
    return bool(token and token.strip())


def criar_preferencia_assinatura(empresa, request):
    """
    Cria uma preferência de pagamento oficial no Mercado Pago Checkout Pro
    para a assinatura mensal de R$ 50,00, estritamente conforme a documentação oficial:
    https://www.mercadopago.com.br/developers/pt/reference/preferences/_checkout_preferences/post
    Retorna um dicionário com {'id': preference_id, 'init_point': url_de_pagamento, 'simulacao': False}.
    """
    access_token = getattr(settings, 'MERCADO_PAGO_ACCESS_TOKEN', '').strip()
    if not access_token:
        logger.info(f"[MercadoPago Service] Token de acesso não configurado para empresa {empresa.id}.")
        sim_url = request.build_absolute_uri(f"/assinatura/simular-pagamento/?empresa_id={empresa.id}") if request else ""
        return {
            'simulacao': True,
            'id': f"SIM-PREF-{empresa.id}-{int(timezone.now().timestamp())}",
            'init_point': sim_url,
            'sandbox_init_point': sim_url,
        }

    # 1. Dados do comprador e identificação
    dono = empresa.dono or (request.user if request and request.user.is_authenticated else None)
    email_comprador = dono.email if dono and dono.email else f"empresa{empresa.id}@sistema.local"
    
    nome_completo = ""
    if dono:
        nome_completo = dono.get_full_name() or dono.first_name or dono.username
    if not nome_completo:
        nome_completo = empresa.nome

    partes_nome = nome_completo.strip().split(maxsplit=1)
    primeiro_nome = partes_nome[0] if partes_nome else "Cliente"
    sobrenome = partes_nome[1] if len(partes_nome) > 1 else (empresa.nome if empresa.nome != primeiro_nome else "JGTECH")

    payer = {
        "name": primeiro_nome,
        "surname": sobrenome,
        "first_name": primeiro_nome,
        "last_name": sobrenome,
        "email": email_comprador,
    }

    # Telefone do comprador (DDD + número)
    tel_raw = re.sub(r'\D', '', getattr(empresa, 'telefone', '') or '')
    if not tel_raw and dono:
        tel_raw = re.sub(r'\D', '', getattr(dono, 'telefone', '') or '')
    if len(tel_raw) >= 10:
        area_code = tel_raw[:2]
        tel_num = tel_raw[2:]
    else:
        area_code = "11"
        tel_num = "987654321"

    payer["phone"] = {
        "area_code": area_code,
        "number": tel_num
    }

    # Documento de identificação (apenas se CPF ou CNPJ válido fornecido)
    doc_limpo = re.sub(r'\D', '', empresa.cnpj or '')
    if doc_limpo and len(doc_limpo) in (11, 14):
        tipo_doc = 'CNPJ' if len(doc_limpo) == 14 else 'CPF'
        payer["identification"] = {
            "type": tipo_doc,
            "number": doc_limpo
        }

    # 2. URLs de Retorno (Back URLs) e Webhook
    if request:
        back_url_sucesso = request.build_absolute_uri('/minha-assinatura/?status_mp=aprovado')
        back_url_falha = request.build_absolute_uri('/minha-assinatura/?status_mp=falha')
        back_url_pendente = request.build_absolute_uri('/minha-assinatura/?status_mp=pendente')
        webhook_local = request.build_absolute_uri('/api/mercadopago/webhook/')
        notification_url = webhook_local if webhook_local.startswith("https://") else "https://estoque-ruby-five.vercel.app/api/mercadopago/webhook/"
    else:
        back_url_sucesso = "https://estoque-ruby-five.vercel.app/minha-assinatura/?status_mp=aprovado"
        back_url_falha = "https://estoque-ruby-five.vercel.app/minha-assinatura/?status_mp=falha"
        back_url_pendente = "https://estoque-ruby-five.vercel.app/minha-assinatura/?status_mp=pendente"
        notification_url = "https://estoque-ruby-five.vercel.app/api/mercadopago/webhook/"

    # 3. Informações adicionais para antifraude (Antifraud & Scoring)
    agora = timezone.now()
    data_reg = empresa.data_criacao if empresa.data_criacao else agora
    primeira_compra = not PagamentoAssinatura.objects.filter(empresa=empresa, status='APROVADO').exists()

    payer_additional = {
        "registration_date": data_reg.strftime('%Y-%m-%dT%H:%M:%S.000-03:00'),
        "is_first_purchase_online": primeira_compra,
        "authentication_type": "native"
    }

    # 4. Payload Oficial da API de Preferências do Mercado Pago (Checkout Pro)
    payload = {
        "items": [
            {
                "id": f"assinatura-{empresa.id}",
                "external_code": f"ASSINATURA-JGTECH-{empresa.id}",
                "title": f"Assinatura JGTECH Estoque - {empresa.nome}",
                "description": "Mensalidade do sistema de gestão de estoque JGTECH (30 dias)",
                "category_id": "services",
                "quantity": 1,
                "currency_id": "BRL",
                "unit_price": float(VALOR_ASSINATURA_PADRAO)
            }
        ],
        "payer": payer,
        "additional_info": {
            "payer": payer_additional
        },
        "statement_descriptor": "JGTECH",
        "config": {
            "statement_descriptor": "JGTECH"
        },
        "external_reference": str(empresa.id),
        "payment_methods": {
            "excluded_payment_types": [
                {"id": "ticket"}  # Exclui Boleto Bancário (apenas Pix e Cartões)
            ],
            "installments": 12
        },
        "back_urls": {
            "success": back_url_sucesso,
            "failure": back_url_falha,
            "pending": back_url_pendente
        }
    }

    # Redirecionamento automático após aprovação (requer HTTPS)
    if back_url_sucesso.startswith("https://"):
        payload["auto_return"] = "approved"

    # Notificação via Webhook IPN (requer HTTPS)
    if notification_url and notification_url.startswith("https://"):
        payload["notification_url"] = notification_url

    # 4. Criação via SDK oficial do Mercado Pago
    try:
        import mercadopago
        sdk = mercadopago.SDK(access_token)
        req_opt = mercadopago.config.RequestOptions()
        req_opt.custom_headers = {'x-idempotency-key': str(uuid.uuid4())}

        # 4.1 Tenta criar via Orders API (/v1/orders) para gerar Order ID oficial (ORDTST... / ORD...)
        # Esse formato é o exigido pelo painel de "Qualidade da Integração" do Mercado Pago
        try:
            order_payload = {
                "type": "online",
                "processing_mode": "manual",
                "external_reference": str(empresa.id),
                "total_amount": f"{VALOR_ASSINATURA_PADRAO:.2f}",
                "payer": {
                    "first_name": primeiro_nome,
                    "last_name": sobrenome,
                    "email": email_comprador,
                    "phone": {
                        "area_code": area_code,
                        "number": tel_num
                    }
                },
                "items": [
                    {
                        "external_code": f"ASSINATURA-JGTECH-{empresa.id}",
                        "title": f"Assinatura JGTECH Estoque - {empresa.nome}",
                        "description": "Mensalidade do sistema de gestao de estoque JGTECH (30 dias)",
                        "category_id": "services",
                        "unit_price": f"{VALOR_ASSINATURA_PADRAO:.2f}",
                        "quantity": 1
                    }
                ],
                "additional_info": {
                    "payer.registration_date": (empresa.data_criacao or agora).strftime('%Y-%m-%dT%H:%M:%S.000-03:00'),
                    "payer.is_first_purchase_online": not PagamentoAssinatura.objects.filter(empresa=empresa, status='APROVADO').exists(),
                    "payer.authentication_type": "WEB"
                },
                "config": {
                    "statement_descriptor": "JGTECH",
                    "online": {
                        "success_url": back_url_sucesso,
                        "failure_url": back_url_falha,
                        "pending_url": back_url_pendente
                    },
                    "payment_method": {
                        "not_allowed_types": ["ticket"],
                        "max_installments": 12
                    }
                }
            }
            if doc_limpo and len(doc_limpo) in (11, 14):
                order_payload["payer"]["identification"] = {
                    "type": 'CNPJ' if len(doc_limpo) == 14 else 'CPF',
                    "number": doc_limpo
                }

            order_resp = sdk.order().create(order_payload, request_options=req_opt)
            st_order = order_resp.get('status')
            dados_order = order_resp.get('response', {})
            if st_order in (200, 201) and dados_order.get('id') and dados_order.get('checkout_url'):
                order_id = dados_order.get('id')
                checkout_url = dados_order.get('checkout_url')
                logger.info(f"[MercadoPago Orders API] Order criada com sucesso ID {order_id} para empresa {empresa.id}.")
                return {
                    'simulacao': False,
                    'id': order_id,
                    'order_id': order_id,
                    'init_point': checkout_url,
                    'sandbox_init_point': checkout_url
                }
            else:
                logger.info(f"[MercadoPago Orders API] Status {st_order}. Recorrendo a Preferences API...")
        except Exception as e_ord:
            logger.info(f"[MercadoPago Orders API Exception] {str(e_ord)}. Recorrendo a Preferences API...")

        # 4.2 Fallback para Preferences API clássica (/checkout/preferences)
        pref_response = sdk.preference().create(payload)
        status_code = pref_response.get('status')
        dados = pref_response.get('response', {})
        if status_code in (200, 201) and dados.get('id'):
            logger.info(f"[MercadoPago SDK] Preferência criada com sucesso ID {dados.get('id')} para empresa {empresa.id}.")
            return {
                'simulacao': False,
                'id': dados.get('id'),
                'init_point': dados.get('init_point'),
                'sandbox_init_point': dados.get('sandbox_init_point', dados.get('init_point'))
            }
        else:
            logger.warning(f"[MercadoPago SDK Warning] Status {status_code}: {dados}. Tentando fallback HTTP...")
    except ImportError:
        logger.info("[MercadoPago Service] SDK mercadopago não disponível no ambiente, usando fallback HTTP direto.")
    except Exception as e:
        logger.warning(f"[MercadoPago SDK Exception] {str(e)}. Tentando fallback HTTP...")

    # 5. Fallback direto via HTTP REST oficial
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(
            f"{MERCADO_PAGO_API_URL}/checkout/preferences",
            json=payload,
            headers=headers,
            timeout=15
        )
        if response.status_code in (200, 201):
            dados = response.json()
            logger.info(f"[MercadoPago Preferences] Sucesso ao criar preferência ID {dados.get('id')} para empresa {empresa.id}.")
            return {
                'simulacao': False,
                'id': dados.get('id'),
                'init_point': dados.get('init_point'),
                'sandbox_init_point': dados.get('sandbox_init_point', dados.get('init_point'))
            }
        else:
            logger.error(f"[MercadoPago Preferences Error] Status {response.status_code}: {response.text}")
    except Exception as e:
        logger.exception(f"[MercadoPago Preferences Exception] Erro ao criar preferência: {str(e)}")

    return None




def gerar_order_homologacao_mp(empresa, request=None):
    """
    Função utilitária para gerar Orders diretamente na API /v1/orders do Mercado Pago,
    com todos os parâmetros de homologação e antifraude (gera IDs com prefixo ORDTST).
    """
    access_token = getattr(settings, 'MERCADO_PAGO_ACCESS_TOKEN', '').strip()
    if not access_token:
        return None

    agora = timezone.now()
    data_reg = empresa.data_criacao if empresa.data_criacao else agora
    primeira_compra = not PagamentoAssinatura.objects.filter(empresa=empresa, status='APROVADO').exists()

    order_headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Idempotency-Key": str(uuid.uuid4())
    }

    doc_limpo = re.sub(r'\D', '', empresa.cnpj or '')
    if doc_limpo and len(doc_limpo) >= 11:
        tipo_doc = 'CNPJ' if len(doc_limpo) > 11 else 'CPF'
    else:
        tipo_doc = 'CPF'
        doc_limpo = '11144477735'

    order_payload = {
        "type": "online",
        "processing_mode": "manual",
        "external_reference": str(empresa.id),
        "total_amount": f"{VALOR_ASSINATURA_PADRAO:.2f}",
        "payer": {
            "first_name": "Carlos",
            "last_name": "Silva",
            "email": "carlos.silva@teste.com",
            "phone": {
                "area_code": "11",
                "number": "987654321"
            },
            "identification": {
                "type": tipo_doc,
                "number": doc_limpo
            }
        },
        "items": [
            {
                "external_code": f"ASSINATURA-JGTECH-{empresa.id}",
                "title": f"Assinatura JGTECH Estoque - {empresa.nome}",
                "description": "Mensalidade do sistema de gestao de estoque, vendas PDV e crediario JGTECH (30 dias)",
                "category_id": "services",
                "unit_price": f"{VALOR_ASSINATURA_PADRAO:.2f}",
                "quantity": 1
            }
        ],
        "additional_info": {
            "payer.registration_date": data_reg.strftime('%Y-%m-%dT%H:%M:%S.000-03:00'),
            "payer.is_first_purchase_online": primeira_compra,
            "payer.authentication_type": "WEB"
        },
        "config": {
            "statement_descriptor": "JGTECH",
            "online": {
                "success_url": "https://estoque-ruby-five.vercel.app/minha-assinatura/?status_mp=aprovado",
                "failure_url": "https://estoque-ruby-five.vercel.app/minha-assinatura/?status_mp=falha",
                "pending_url": "https://estoque-ruby-five.vercel.app/minha-assinatura/?status_mp=pendente"
            },
            "payment_method": {
                "not_allowed_types": ["ticket"],
                "max_installments": 12
            }
        }
    }

    # Criação via SDK oficial do Mercado Pago (pontuação "SDK do backend")
    try:
        import mercadopago
        sdk = mercadopago.SDK(access_token)
        req_opt = mercadopago.config.RequestOptions()
        req_opt.custom_headers = {'x-idempotency-key': str(uuid.uuid4())}

        sdk_resp = sdk.order().create(order_payload, request_options=req_opt)
        status_code = sdk_resp.get('status')
        dados = sdk_resp.get('response', {})
        if status_code in (200, 201) and dados.get('id'):
            order_id = dados.get('id')
            PagamentoAssinatura.objects.create(
                empresa=empresa,
                valor=VALOR_ASSINATURA_PADRAO,
                metodo='MERCADO_PAGO',
                status='PENDENTE',
                mp_order_id=order_id,
                mp_preference_id=order_id,
                mp_init_point=dados.get('checkout_url'),
                observacoes="Order de homologação gerada no Mercado Pago"
            )
            logger.info(f"[MercadoPago SDK Order] Sucesso ao criar order ID {order_id} para empresa {empresa.id}.")
            return {
                'id': order_id,
                'checkout_url': dados.get('checkout_url')
            }
        else:
            logger.warning(f"[MercadoPago SDK Order Warning] Status {status_code}: {dados}. Tentando fallback HTTP...")
    except ImportError:
        logger.info("[MercadoPago Service] SDK mercadopago não disponível no ambiente para Order, usando fallback HTTP direto.")
    except Exception as e:
        logger.warning(f"[MercadoPago SDK Order Exception] {str(e)}. Tentando fallback HTTP...")

    # Fallback direto via HTTP REST caso o SDK falhe
    try:
        resp = requests.post(f"{MERCADO_PAGO_API_URL}/v1/orders", json=order_payload, headers=order_headers, timeout=15)
        if resp.status_code in (200, 201):
            dados = resp.json()
            order_id = dados.get('id')
            PagamentoAssinatura.objects.create(
                empresa=empresa,
                valor=VALOR_ASSINATURA_PADRAO,
                metodo='MERCADO_PAGO',
                status='PENDENTE',
                mp_order_id=order_id,
                mp_preference_id=order_id,
                mp_init_point=dados.get('checkout_url'),
                observacoes="Order de homologação gerada no Mercado Pago"
            )
            return {
                'id': order_id,
                'checkout_url': dados.get('checkout_url')
            }
        else:
            logger.error(f"[MercadoPago Order Homologação Error] Status {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.exception(f"[MercadoPago Order Homologação Exception] {str(e)}")
    return None


def consultar_pagamento_mp(payment_id):
    """
    Consulta os detalhes de um pagamento diretamente na API do Mercado Pago.
    Aplica sanitização estrita para prevenir Path Traversal, SSRF e injeção de parâmetros.
    """
    access_token = getattr(settings, 'MERCADO_PAGO_ACCESS_TOKEN', '').strip()
    if not access_token:
        return None

    payment_id_str = str(payment_id).strip() if payment_id else ''
    if not payment_id_str or not re.match(r'^[a-zA-Z0-9_\-\.]{1,80}$', payment_id_str):
        logger.warning(f"[MercadoPago Sanitizer] Tentativa de consulta com payment_id inválido ou suspeito.")
        return None

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.get(f"{MERCADO_PAGO_API_URL}/v1/payments/{payment_id_str}", headers=headers, timeout=15)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.exception(f"[MercadoPago Exception] Erro ao consultar pagamento {payment_id_str}: {str(e)}")
    return None


def consultar_order_mp(order_id):
    """
    Consulta os detalhes de uma Order diretamente na API do Mercado Pago.
    Suporta tanto a API de Merchant Orders (padrão Checkout Pro) quanto a v1/orders.
    Aplica sanitização estrita para prevenir Path Traversal, SSRF e injeção de parâmetros.
    """
    access_token = getattr(settings, 'MERCADO_PAGO_ACCESS_TOKEN', '').strip()
    if not access_token:
        return None

    order_id_str = str(order_id).strip() if order_id else ''
    if not order_id_str or not re.match(r'^[a-zA-Z0-9_\-\.]{1,80}$', order_id_str):
        logger.warning(f"[MercadoPago Sanitizer] Tentativa de consulta com order_id inválido ou suspeito.")
        return None

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    try:
        # 1. Consulta em Merchant Orders (padrão do Checkout Pro)
        response_mo = requests.get(f"{MERCADO_PAGO_API_URL}/merchant_orders/{order_id_str}", headers=headers, timeout=15)
        if response_mo.status_code == 200:
            return response_mo.json()

        # 2. Fallback para v1/orders
        response_v1 = requests.get(f"{MERCADO_PAGO_API_URL}/v1/orders/{order_id_str}", headers=headers, timeout=15)
        if response_v1.status_code == 200:
            return response_v1.json()
    except Exception as e:
        logger.exception(f"[MercadoPago Exception] Erro ao consultar order {order_id_str}: {str(e)}")
    return None


def extrair_detalhes_transacao_mp(dados_order=None, dados_payment=None):
    """
    Normaliza e extrai identificadores correlacionados (order_id, payment_id, preference_id, status, valor, external_reference)
    a partir dos retornos da API do Mercado Pago (Merchant Orders, Orders v1 ou Payments v1).
    Garante a unificação de IDs para prevenir duplicação de pagamentos e concessão indevida de dias.
    """
    res = {
        'order_id': None,
        'payment_id': None,
        'preference_id': None,
        'status': None,
        'valor': None,
        'external_reference': None
    }
    if dados_order:
        res['order_id'] = str(dados_order.get('id') or '') or None
        res['preference_id'] = str(dados_order.get('preference_id') or '') or None
        res['external_reference'] = str(dados_order.get('external_reference') or '') or None
        res['status'] = dados_order.get('status')
        res['valor'] = dados_order.get('total_amount')

        # Merchant Orders usa 'payments', v1/orders usa 'transactions.payments'
        payments = dados_order.get('payments') or dados_order.get('transactions', {}).get('payments') or []
        p_aprovado = None
        for p in payments:
            st = p.get('status')
            if st in ('approved', 'accredited'):
                p_aprovado = p
                break
        if not p_aprovado and payments:
            p_aprovado = payments[0]

        if p_aprovado:
            res['payment_id'] = str(p_aprovado.get('id') or p_aprovado.get('reference_id') or '') or None
            if p_aprovado.get('transaction_amount'):
                res['valor'] = p_aprovado.get('transaction_amount')
            if p_aprovado.get('status'):
                res['status'] = p_aprovado.get('status')

    if dados_payment:
        res['payment_id'] = str(dados_payment.get('id') or '') or res['payment_id']
        order_found = dados_payment.get('order', {}).get('id')
        if order_found:
            res['order_id'] = str(order_found)
        if dados_payment.get('external_reference'):
            res['external_reference'] = str(dados_payment.get('external_reference'))
        if dados_payment.get('status'):
            res['status'] = dados_payment.get('status')
        if dados_payment.get('transaction_amount'):
            res['valor'] = dados_payment.get('transaction_amount')

    return res


def verificar_assinatura_webhook(request, secret):
    """
    Valida a assinatura x-signature enviada pelo Mercado Pago via HMAC-SHA256,
    conforme documentação oficial de Webhooks do Mercado Pago.
    """
    if not secret:
        return True

    x_signature = request.headers.get("x-signature", "")
    x_request_id = request.headers.get("x-request-id", "")
    data_id = (request.GET.get("data.id", "") or "").lower()

    if not x_signature:
        return False

    ts = None
    hash_value = None
    for part in x_signature.split(","):
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "ts":
            ts = value
        elif key == "v1":
            hash_value = value

    if not ts or not hash_value:
        return False

    parts = []
    if data_id:
        parts.append(f"id:{data_id}")
    if x_request_id:
        parts.append(f"request-id:{x_request_id}")
    parts.append(f"ts:{ts}")
    manifest = ";".join(parts) + ";"

    computed = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, hash_value)


@transaction.atomic
def processar_aprovacao_assinatura(empresa, payment_id=None, preference_id=None, metodo='MERCADO_PAGO', valor=None, dias=30, observacoes='', order_id=None):
    """
    Aprova ou renova a assinatura da empresa por 'dias' dias (padrão 30 dias).
    Garante idempotência estrita com trava transacional no banco de dados (select_for_update):
    - Se uma transação com payment_id, preference_id ou order_id já foi aprovada anteriormente,
      ou se um pagamento Mercado Pago foi aprovado nos últimos 15 minutos para esta mesma empresa,
      unifica os dados no mesmo registro e NÃO duplica a concessão de dias nem o registro.
    - Se houver pagamento PENDENTE para a empresa iniciado recentemente, atualiza-o para APROVADO.
    - Salva o Order ID completo e Payment ID no modelo PagamentoAssinatura.
    """
    from django.db.models import Q
    if metodo in ('MANUAL_ADMIN', 'SIMULACAO', 'CORTESIA'):
        valor = Decimal('0.00')
    elif valor is None:
        valor = VALOR_ASSINATURA_PADRAO
    else:
        valor = Decimal(str(valor))

    # Trava no banco de dados para eliminar race conditions de Webhooks concorrentes
    empresa = Empresa.objects.select_for_update().get(id=empresa.id)

    agora = timezone.now()
    payment_id_str = str(payment_id).strip() if payment_id else ''
    preference_id_str = str(preference_id).strip() if preference_id else ''
    order_id_str = str(order_id).strip() if order_id else ''

    # Auto-detecta Order ID se fornecido no payment_id ou preference_id
    if not order_id_str:
        if payment_id_str.startswith('ORD'):
            order_id_str = payment_id_str
        elif preference_id_str.startswith('ORD'):
            order_id_str = preference_id_str

    # 1. Verifica se já existe um pagamento APROVADO com qualquer um dos IDs desta transação
    filtro_duplicado = Q()
    ids_busca = [i for i in [payment_id_str, preference_id_str, order_id_str] if i]
    if ids_busca:
        for ident in ids_busca:
            filtro_duplicado |= (
                Q(mp_payment_id=ident) |
                Q(mp_preference_id=ident) |
                Q(mp_order_id=ident)
            )

    ja_aprovado = None
    if filtro_duplicado:
        ja_aprovado = PagamentoAssinatura.objects.filter(filtro_duplicado, status='APROVADO').first()

    # Janela de debounce: Se um pagamento APROVADO via Mercado Pago já foi registrado nos últimos 15 minutos
    # para esta mesma empresa, trata-se do mesmo checkout (concorrência de Webhook Merchant Order + Payment + Back URL)
    if not ja_aprovado and metodo == 'MERCADO_PAGO':
        ja_aprovado = PagamentoAssinatura.objects.filter(
            empresa=empresa,
            status='APROVADO',
            metodo='MERCADO_PAGO',
            data_confirmacao__gte=agora - timedelta(minutes=15)
        ).order_by('-data_confirmacao').first()

    if ja_aprovado:
        # Vincula todos os IDs para garantir rastreabilidade completa e unificada
        campos_atualizar = []
        if payment_id_str:
            if not ja_aprovado.mp_payment_id:
                ja_aprovado.mp_payment_id = payment_id_str
                campos_atualizar.append('mp_payment_id')
            elif ja_aprovado.mp_payment_id == ja_aprovado.mp_order_id and payment_id_str != ja_aprovado.mp_order_id:
                # Corrige se o payment_id havia sido salvo temporariamente com o order_id
                ja_aprovado.mp_payment_id = payment_id_str
                campos_atualizar.append('mp_payment_id')

        if preference_id_str and not ja_aprovado.mp_preference_id:
            ja_aprovado.mp_preference_id = preference_id_str
            campos_atualizar.append('mp_preference_id')

        if order_id_str and not ja_aprovado.mp_order_id:
            ja_aprovado.mp_order_id = order_id_str
            campos_atualizar.append('mp_order_id')

        if campos_atualizar:
            ja_aprovado.save(update_fields=campos_atualizar)

        logger.info(f"[Assinatura] Pagamento já aprovado previamente (ID {ja_aprovado.id}). Evitando duplicação e mantendo vigência correta.")
        return ja_aprovado

    # 2. Se havia um registro PENDENTE para esta transação, atualiza-o em vez de criar outro
    pag_pendente = None
    if filtro_duplicado:
        pag_pendente = PagamentoAssinatura.objects.filter(filtro_duplicado, status='PENDENTE').first()

    if not pag_pendente and metodo == 'MERCADO_PAGO':
        # Busca o pagamento PENDENTE mais recente criado nas últimas 2 horas para esta empresa
        pag_pendente = PagamentoAssinatura.objects.filter(
            empresa=empresa,
            status='PENDENTE',
            metodo='MERCADO_PAGO',
            data_criacao__gte=agora - timedelta(hours=2)
        ).order_by('-data_criacao').first()

    # 3. Calcula vigência: se já estava ativa no futuro, soma a partir da data de fim; senão, a partir de agora
    if empresa.status_assinatura == 'ATIVA' and empresa.assinatura_fim and empresa.assinatura_fim > agora:
        nova_data_fim = empresa.assinatura_fim + timedelta(days=dias)
    else:
        nova_data_fim = agora + timedelta(days=dias)

    empresa.status_assinatura = 'ATIVA'
    empresa.assinatura_fim = nova_data_fim
    empresa.ativo = True
    empresa.save(update_fields=['status_assinatura', 'assinatura_fim', 'ativo'])

    if pag_pendente:
        pag_pendente.status = 'APROVADO'
        if payment_id_str:
            pag_pendente.mp_payment_id = payment_id_str
        if preference_id_str:
            pag_pendente.mp_preference_id = preference_id_str
        if order_id_str:
            pag_pendente.mp_order_id = order_id_str
        pag_pendente.data_confirmacao = agora
        pag_pendente.dias_concedidos = dias
        pag_pendente.valor = valor
        pag_pendente.observacoes = observacoes or f"Assinatura aprovada. Vigência prorrogada até {nova_data_fim.strftime('%d/%m/%Y')}."
        pag_pendente.save()
        pagamento = pag_pendente
    else:
        pagamento = PagamentoAssinatura.objects.create(
            empresa=empresa,
            valor=valor,
            metodo=metodo,
            status='APROVADO',
            mp_order_id=order_id_str or None,
            mp_payment_id=payment_id_str or f"MANUAL-{int(agora.timestamp())}-{empresa.id}",
            mp_preference_id=preference_id_str or '',
            dias_concedidos=dias,
            data_confirmacao=agora,
            observacoes=observacoes or f"Assinatura aprovada. Vigência prorrogada até {nova_data_fim.strftime('%d/%m/%Y')}."
        )

    logger.info(f"[Assinatura] Empresa {empresa.nome} (ID: {empresa.id}) ativada até {nova_data_fim} (Order: {order_id_str}, Pay: {payment_id_str}).")
    return pagamento


def sincronizar_pagamentos_pendentes(empresa=None):
    """
    Varre os pagamentos pendentes recentes e consulta o status na API do Mercado Pago.
    Se o pagamento tiver sido aprovado/creditado no Mercado Pago (ex: comprador não clicou
    em 'Voltar à loja' ou webhook ainda não configurado), ativa a assinatura automaticamente.
    Retorna a quantidade de pagamentos atualizados.
    """
    if not is_mercadopago_configured():
        return 0

    try:
        qs = PagamentoAssinatura.objects.filter(status='PENDENTE', metodo='MERCADO_PAGO')
        if empresa:
            qs = qs.filter(empresa=empresa)

        atualizados = 0
        for pag in qs.order_by('-data_criacao')[:30]:
            identificador = pag.mp_order_id or pag.mp_preference_id or pag.mp_payment_id
            if not identificador:
                continue

            dados = None
            if identificador.startswith('ORD'):
                dados = consultar_order_mp(identificador)
                if dados:
                    status = dados.get('status')
                    status_detail = dados.get('status_detail')
                    if status in ('processed', 'closed', 'paid', 'approved') or status_detail in ('accredited', 'approved'):
                        real_payment_id = identificador
                        if dados.get('transactions', {}).get('payments'):
                            first_pay = dados['transactions']['payments'][0]
                            real_payment_id = str(first_pay.get('reference_id') or first_pay.get('id') or identificador)

                        processar_aprovacao_assinatura(
                            empresa=pag.empresa,
                            payment_id=real_payment_id,
                            preference_id=identificador,
                            order_id=identificador,
                            metodo='MERCADO_PAGO',
                            valor=pag.valor,
                            dias=pag.dias_concedidos,
                            observacoes=f"Aprovado via reconciliação automática Mercado Pago (Status: {status})"
                        )
                        atualizados += 1
            elif pag.mp_payment_id:
                dados = consultar_pagamento_mp(pag.mp_payment_id)
                if dados:
                    status = dados.get('status')
                    if status == 'approved':
                        real_id = str(dados.get('id', pag.mp_payment_id))
                        processar_aprovacao_assinatura(
                            empresa=pag.empresa,
                            payment_id=real_id,
                            preference_id=pag.mp_preference_id or '',
                            metodo='MERCADO_PAGO',
                            valor=pag.valor,
                            dias=pag.dias_concedidos,
                            observacoes=f"Aprovado via reconciliação automática Mercado Pago (Status: {status})"
                        )
                        atualizados += 1
            elif pag.mp_preference_id:
                # Reconciliação para Checkout Pro: busca a Merchant Order pela Preference ID
                access_token = getattr(settings, 'MERCADO_PAGO_ACCESS_TOKEN', '').strip()
                headers = {'Authorization': f'Bearer {access_token}'}
                try:
                    r_mo = requests.get(
                        f"{MERCADO_PAGO_API_URL}/merchant_orders?preference_id={pag.mp_preference_id}",
                        headers=headers,
                        timeout=10
                    )
                    if r_mo.status_code == 200:
                        elements = r_mo.json().get('elements', [])
                        aprovado_encontrado = False
                        for mo in elements:
                            for p in mo.get('payments', []):
                                if p.get('status') == 'approved':
                                    real_id = str(p.get('id'))
                                    valor_pago = Decimal(str(p.get('transaction_amount', pag.valor)))
                                    processar_aprovacao_assinatura(
                                        empresa=pag.empresa,
                                        payment_id=real_id,
                                        preference_id=pag.mp_preference_id,
                                        order_id=str(mo.get('id') or ''),
                                        metodo='MERCADO_PAGO',
                                        valor=valor_pago,
                                        dias=pag.dias_concedidos,
                                        observacoes=f"Aprovado via reconciliação automática Checkout Pro (Order {mo.get('id')})"
                                    )
                                    atualizados += 1
                                    aprovado_encontrado = True
                                    break
                            if aprovado_encontrado:
                                break
                except Exception as e:
                    logger.warning(f"[MercadoPago Reconciliação Preference] {str(e)}")

        return atualizados
    except Exception as e:
        logger.warning(f"[MercadoPago Reconciliação] Erro ao sincronizar pagamentos pendentes: {e}")
        return 0
