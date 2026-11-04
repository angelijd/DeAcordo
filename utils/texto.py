"""Neutraliza texto livre digitado pelo usuário antes de ir para mensagens do Slack."""

from typing import Any


def neutralizar_mrkdwn(valor: Any) -> Any:
    """Troca < e > por &lt; e &gt; (padrão do Slack), em strings, listas e dicts.

    Sem isso, um texto como <!channel> ou <https://site|Simulador> vira menção ou link
    disfarçado na thread. Pode ser aplicado mais de uma vez sem duplicar o escape.
    """
    if isinstance(valor, str):
        return valor.replace("<", "&lt;").replace(">", "&gt;")
    if isinstance(valor, list):
        return [neutralizar_mrkdwn(v) for v in valor]
    if isinstance(valor, dict):
        return {k: neutralizar_mrkdwn(v) for k, v in valor.items()}
    return valor
