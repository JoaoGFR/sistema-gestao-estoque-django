from .models import ConfiguracaoEmpresa

def modulos_empresa(request):
    """
    Injeta os status dos módulos ativos da empresa do usuário logado no contexto de todos os templates.
    Permite checagens dinâmicas simples e elegantes:
        {% if not modulos or modulos.modulo_vendas_pdv %}
        {% if not modulos or modulos.modulo_emprestimos %}
        {% if not modulos or modulos.modulo_clientes_crediario %}
        {% if not modulos or modulos.modulo_simulador_precos %}
    """
    if hasattr(request, 'user') and request.user.is_authenticated:
        try:
            userprofile = getattr(request.user, 'userprofile', None)
            if userprofile and userprofile.empresa:
                return {'modulos': userprofile.empresa.configuracao}
        except Exception:
            pass
    return {'modulos': None}
