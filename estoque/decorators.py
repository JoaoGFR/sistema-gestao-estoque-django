from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages

NOMES_MODULOS_AMIGAVEIS = {
    'modulo_emprestimos': 'Empréstimos & Cautelas',
    'modulo_vendas_pdv': 'Vendas / PDV',
    'modulo_clientes_crediario': 'Clientes & Crediário',
    'modulo_simulador_precos': 'Preços & Simulações',
    'modulo_controle_lotes': 'Controle de Lotes & Validades',
}

def requer_modulo(*nomes_campos_modulo, modo='any'):
    """
    Decorator para views vinculadas a módulos opcionais da empresa.
    Suporta um ou múltiplos módulos (ex: requer_modulo('modulo_vendas_pdv', 'modulo_simulador_precos', modo='any')).
    Se os módulos estiverem desativados pela empresa, impede o acesso direto via URL e
    redireciona para o dashboard com aviso explicativo.
    Superusuários mantêm acesso para suporte técnico.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('landing_page')

            # Superusuários têm acesso irrestrito para auditoria e suporte
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)

            userprofile = getattr(request.user, 'userprofile', None)
            if not userprofile or not userprofile.empresa:
                return redirect('dashboard')

            empresa = userprofile.empresa
            config = empresa.configuracao

            status_modulos = [getattr(config, campo, True) for campo in nomes_campos_modulo]
            if modo == 'any':
                autorizado = any(status_modulos)
            else:
                autorizado = all(status_modulos)

            if not autorizado:
                nomes = [NOMES_MODULOS_AMIGAVEIS.get(c, c) for c in nomes_campos_modulo]
                nomes_str = " ou ".join(nomes) if modo == 'any' else " e ".join(nomes)
                messages.warning(
                    request,
                    f"O módulo de {nomes_str} está desativado para a sua empresa. "
                    f"O administrador pode reativá-lo a qualquer momento em 'Gerenciamento > Módulos do Sistema'."
                )
                return redirect('dashboard')

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
