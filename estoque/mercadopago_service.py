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
    Cria uma preferência de pagamento no Mercado Pago para assinatura mensal de R$ 50,00.
    Retorna um dicionário com preference_id, init_point e sandbox.
    Se não houver token configurado, retorna modo de simulação local.
    """
    access_token = getattr(settings, 'MERCADO_PAGO_ACCESS_TOKEN', '').strip()
    
    # Se não houver credencial configurada no .env, ativa o modo de demonstração / simulação
    if not access_token:
        logger.info(f"[MercadoPago Service] Token não configurado. Modo de simulação para empresa {empresa.id}.")
        sim_url = request.build_absolute_uri(f"/assinatura/simular-pagamento/?empresa_id={empresa.id}")
        return {
            'simulacao': True,
            'id': f"SIM-PREF-{empresa.id}-{int(timezone.now().timestamp())}",
            'init_point': sim_url,
            'sandbox_init_point': sim_url,
        }

    # Dados do comprador
    dono = empresa.dono or (request.user if request.user.is_authenticated else None)
    email_comprador = dono.email if dono and dono.email else f"empresa{empresa.id}@sistema.local"
    nome_comprador = dono.get_full_name() if dono and dono.get_full_name() else empresa.nome

    # URLs de Retorno
    back_url_sucesso = request.build_absolute_uri('/minha-assinatura/?status_mp=aprovado')
    back_url_falha = request.build_absolute_uri('/minha-assinatura/?status_mp=falha')
    back_url_pendente = request.build_absolute_uri('/minha-assinatura/?status_mp=pendente')
    webhook_url = request.build_absolute_uri('/api/mercadopago/webhook/')

    # -------------------------------------------------------------------------
    # 1. API DE ORDERS (v1/orders) - Padrão Checkout Pro com checkout_url
    # -------------------------------------------------------------------------
    order_headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Idempotency-Key": str(uuid.uuid4())
    }
    order_payload = {
        "type": "online",
        "processing_mode": "manual",
        "total_amount": f"{VALOR_ASSINATURA_PADRAO:.2f}",
        "external_reference": str(empresa.id),
        "payer": {
            "email": email_comprador
        },
        "items": [
            {
                "title": f"Assinatura JGTECH Estoque - {empresa.nome}",
                "unit_price": f"{VALOR_ASSINATURA_PADRAO:.2f}",
                "quantity": 1
            }
        ],
        "config": {
            "payment_method": {
                "not_allowed_types": ["ticket"],  # Exclui Boleto Bancário (apenas Pix e Cartões)
                "max_installments": 12
            },
            "online": {
                "success_url": back_url_sucesso,
                "failure_url": back_url_falha,
                "pending_url": back_url_pendente
            }
        }
    }
    if back_url_sucesso.startswith("https://"):
        order_payload["config"]["online"]["auto_return"] = "approved"

    try:
        order_response = requests.post(
            f"{MERCADO_PAGO_API_URL}/v1/orders",
            json=order_payload,
            headers=order_headers,
            timeout=15
        )
        if order_response.status_code in (200, 201):
            dados_order = order_response.json()
            checkout_url = dados_order.get('checkout_url')
            if checkout_url:
                return {
                    'simulacao': False,
                    'id': dados_order.get('id'),
                    'init_point': checkout_url,
                    'sandbox_init_point': checkout_url
                }
        else:
            logger.warning(f"[MercadoPago Orders API] Status {order_response.status_code}: Falha ao gerar checkout order.")
    except Exception as e:
        logger.warning(f"[MercadoPago Orders API Exception] {str(e)}")

    # -------------------------------------------------------------------------
    # 2. FALLBACK: PREFERENCES API (/checkout/preferences)
    # -------------------------------------------------------------------------
    payload = {
        "items": [
            {
                "id": f"assinatura-{empresa.id}",
                "title": f"Assinatura JGTECH Estoque - {empresa.nome}",
                "description": "Mensalidade do sistema de gestão de estoque, vendas PDV e crediário (30 dias)",
                "quantity": 1,
                "currency_id": "BRL",
                "unit_price": float(VALOR_ASSINATURA_PADRAO)
            }
        ],
        "payer": {
            "name": nome_comprador,
            "email": email_comprador
        },
        "back_urls": {
            "success": back_url_sucesso,
            "failure": back_url_falha,
            "pending": back_url_pendente
        },
        "external_reference": str(empresa.id),
        "statement_descriptor": "JGTECH ASSINATURA",
        "payment_methods": {
            "excluded_payment_types": [
                {"id": "ticket"}  # Exclui Boleto Bancário (apenas Pix, Cartão de Crédito e Débito)
            ],
            "installments": 12
        }
    }

    # auto_return só é aceito pela API do Mercado Pago se a URL de retorno for HTTPS pública
    if back_url_sucesso.startswith("https://"):
        payload["auto_return"] = "approved"

    # notification_url de webhook só deve ser enviada se for HTTPS pública
    if webhook_url.startswith("https://"):
        payload["notification_url"] = webhook_url

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
            return {
                'simulacao': False,
                'id': dados.get('id'),
                'init_point': dados.get('init_point'),
                'sandbox_init_point': dados.get('sandbox_init_point', dados.get('init_point'))
            }
        else:
            logger.error(f"[MercadoPago Preferences Error] Status {response.status_code}: Falha ao gerar preferência de pagamento.")
    except Exception as e:
        logger.exception(f"[MercadoPago Preferences Exception] Erro ao criar preferência: {str(e)}")

    # Fallback para simulação caso a chamada da API do MP falhe
    sim_url = request.build_absolute_uri(f"/assinatura/simular-pagamento/?empresa_id={empresa.id}")
    return {
        'simulacao': True,
        'id': f"FALLBACK-{empresa.id}-{int(timezone.now().timestamp())}",
        'init_point': sim_url,
        'sandbox_init_point': sim_url,
    }


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
    Consulta os detalhes de uma Order diretamente na API v1/orders do Mercado Pago.
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
        response = requests.get(f"{MERCADO_PAGO_API_URL}/v1/orders/{order_id_str}", headers=headers, timeout=15)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.exception(f"[MercadoPago Exception] Erro ao consultar order {order_id_str}: {str(e)}")
    return None


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
def processar_aprovacao_assinatura(empresa, payment_id=None, preference_id=None, metodo='MERCADO_PAGO', valor=None, dias=30, observacoes=''):
    """
    Aprova ou renova a assinatura da empresa por 'dias' dias (padrão 30 dias).
    Garante idempotência estrita com trava transacional no banco de dados (select_for_update):
    se uma transação com payment_id ou preference_id já foi aprovada anteriormente,
    não duplica a concessão de dias nem o registro.
    """
    from django.db.models import Q
    if valor is None:
        valor = VALOR_ASSINATURA_PADRAO

    # Trava no banco de dados para eliminar race conditions de Webhooks concorrentes
    empresa = Empresa.objects.select_for_update().get(id=empresa.id)

    agora = timezone.now()
    payment_id_str = str(payment_id).strip() if payment_id else ''
    preference_id_str = str(preference_id).strip() if preference_id else ''

    # 1. Verifica se já existe um pagamento APROVADO com qualquer um dos IDs desta transação
    filtro_duplicado = Q()
    if payment_id_str:
        filtro_duplicado |= Q(mp_payment_id=payment_id_str) | Q(mp_preference_id=payment_id_str)
    if preference_id_str:
        filtro_duplicado |= Q(mp_preference_id=preference_id_str) | Q(mp_payment_id=preference_id_str)

    if filtro_duplicado:
        ja_aprovado = PagamentoAssinatura.objects.filter(filtro_duplicado, status='APROVADO').first()
        if ja_aprovado:
            # Vincula ambos os IDs para garantir rastreabilidade completa
            campos_atualizar = []
            if payment_id_str and ja_aprovado.mp_payment_id != payment_id_str:
                ja_aprovado.mp_payment_id = payment_id_str
                campos_atualizar.append('mp_payment_id')
            if preference_id_str and ja_aprovado.mp_preference_id != preference_id_str:
                ja_aprovado.mp_preference_id = preference_id_str
                campos_atualizar.append('mp_preference_id')
            if campos_atualizar:
                ja_aprovado.save(update_fields=campos_atualizar)

            logger.info(f"[Assinatura] Pagamento já aprovado previamente ({payment_id_str} / {preference_id_str}). Ignorando duplicação.")
            return ja_aprovado

    # 2. Se a empresa já tiver assinatura válida no futuro, soma os 30 dias a partir da data futura
    if empresa.status_assinatura == 'ATIVA' and empresa.assinatura_fim and empresa.assinatura_fim > agora:
        nova_data_fim = empresa.assinatura_fim + timedelta(days=dias)
    else:
        nova_data_fim = agora + timedelta(days=dias)

    empresa.status_assinatura = 'ATIVA'
    empresa.assinatura_fim = nova_data_fim
    empresa.ativo = True
    empresa.save(update_fields=['status_assinatura', 'assinatura_fim', 'ativo'])

    # 3. Se havia um registro PENDENTE para esta transação, atualiza-o em vez de criar outro
    pag_pendente = None
    if filtro_duplicado:
        pag_pendente = PagamentoAssinatura.objects.filter(filtro_duplicado, status='PENDENTE').first()

    if pag_pendente:
        pag_pendente.status = 'APROVADO'
        if payment_id_str:
            pag_pendente.mp_payment_id = payment_id_str
        if preference_id_str:
            pag_pendente.mp_preference_id = preference_id_str
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
            mp_payment_id=payment_id_str or f"MANUAL-{int(agora.timestamp())}-{empresa.id}",
            mp_preference_id=preference_id_str or '',
            dias_concedidos=dias,
            data_confirmacao=agora,
            observacoes=observacoes or f"Assinatura aprovada. Vigência prorrogada até {nova_data_fim.strftime('%d/%m/%Y')}."
        )

    logger.info(f"[Assinatura] Empresa {empresa.nome} (ID: {empresa.id}) ativada até {nova_data_fim}.")
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

    qs = PagamentoAssinatura.objects.filter(status='PENDENTE', metodo='MERCADO_PAGO')
    if empresa:
        qs = qs.filter(empresa=empresa)

    atualizados = 0
    for pag in qs.order_by('-data_criacao')[:30]:
        identificador = pag.mp_preference_id or pag.mp_payment_id
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
                        metodo='MERCADO_PAGO',
                        valor=pag.valor,
                        dias=pag.dias_concedidos,
                        observacoes=f"Aprovado via reconciliação automática Mercado Pago (Status: {status})"
                    )
                    atualizados += 1
        else:
            dados = consultar_pagamento_mp(identificador)
            if dados:
                status = dados.get('status')
                if status == 'approved':
                    real_id = str(dados.get('id', identificador))
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

    return atualizados
