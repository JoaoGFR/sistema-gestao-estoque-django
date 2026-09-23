from django.shortcuts import redirect
from django.contrib import messages
from django.utils import timezone
from django.urls import resolve, Resolver404


class AssinaturaMiddleware:
    """
    Middleware que gerencia o período de 3 dias de degustação grátis
    e a vigência das assinaturas pagas. Bloqueia o acesso a qualquer módulo
    operacional caso o teste ou a assinatura estejam vencidos.
    """

    # Rotas isentas de bloqueio
    ROTAS_ISENTAS = [
        'minha_assinatura',
        'iniciar_checkout_mercadopago',
        'simular_pagamento_mp',
        'webhook_mercadopago',
        'painel_superadmin_assinaturas',
        'prorrogar_trial_superadmin',
        'ativar_assinatura_superadmin',
        'toggle_bloqueio_empresa_superadmin',
        'landing_page',
        'cadastro_saas',
        'login',
        'logout',
    ]

    PREFIXOS_ISENTOS = [
        '/static/',
        '/media/',
        '/admin/',
        '/superadmin/',
        '/api/mercadopago/',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. Usuário anônimo ou estáticos: não processa
        path = request.path
        for prefix in self.PREFIXOS_ISENTOS:
            if path.startswith(prefix):
                return self.get_response(request)

        # 2. Verifica se a rota resolvida está na lista de isenções
        try:
            resolver_match = resolve(path)
            url_name = resolver_match.url_name
            if url_name in self.ROTAS_ISENTAS:
                return self.get_response(request)
        except Resolver404:
            pass

        # 3. Se não estiver autenticado, deixa as views/decorators tratarem
        if not request.user.is_authenticated:
            return self.get_response(request)

        # 4. Obtém a empresa vinculada ao perfil
        perfil = getattr(request.user, 'userprofile', None)
        if not perfil or not perfil.empresa:
            return self.get_response(request)

        empresa = perfil.empresa

        # 5. Se a empresa foi desativada manualmente pelo superadmin
        if not empresa.ativo:
            messages.error(request, "Sua empresa foi temporariamente desativada pelo administrador do sistema. Entre em contato com o suporte.")
            return redirect('minha_assinatura')

        # 6. Validação do Período de Testes (3 Dias) e Assinatura Ativa
        agora = timezone.now()
        
        # Caso o trial tenha expirado (ou nunca teve data de fim configurada)
        if empresa.status_assinatura == 'TRIAL':
            if not empresa.trial_fim or agora > empresa.trial_fim:
                if empresa.status_assinatura != 'VENCIDA':
                    empresa.status_assinatura = 'VENCIDA'
                    empresa.save(update_fields=['status_assinatura'])
                messages.warning(request, "Seu período de teste grátis de 3 dias expirou! Para continuar utilizando o sistema, ative sua assinatura de R$ 50,00/mês.")
                return redirect('minha_assinatura')

        # Caso a assinatura paga tenha vencido
        elif empresa.status_assinatura == 'ATIVA':
            if not empresa.assinatura_fim or agora > empresa.assinatura_fim:
                if empresa.status_assinatura != 'VENCIDA':
                    empresa.status_assinatura = 'VENCIDA'
                    empresa.save(update_fields=['status_assinatura'])
                messages.warning(request, "Sua assinatura mensal expirou. Renove sua assinatura para continuar acessando todos os recursos.")
                return redirect('minha_assinatura')

        elif empresa.status_assinatura in ('VENCIDA', 'CANCELADA'):
            messages.warning(request, "Sua assinatura está inativa. Regularize sua mensalidade para continuar utilizando o sistema.")
            return redirect('minha_assinatura')

        # 7. Verificação definitiva de garantia
        if not empresa.assinatura_valida:
            messages.warning(request, "Seu período de testes ou assinatura expirou. Regularize sua mensalidade para continuar utilizando o sistema.")
            return redirect('minha_assinatura')

        # Se estiver tudo certo, anexa as informações no request para consumo em templates
        request.info_assinatura = {
            'em_trial': empresa.em_trial,
            'dias_restantes_trial': empresa.dias_restantes_trial,
            'horas_restantes_trial': empresa.horas_restantes_trial,
            'dias_restantes_assinatura': empresa.dias_restantes_assinatura,
            'status': empresa.status_assinatura,
            'trial_fim': empresa.trial_fim,
            'assinatura_fim': empresa.assinatura_fim,
        }

        return self.get_response(request)
