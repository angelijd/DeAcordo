"""
Mapeamento de Canal → Tipo de Fluxo (Crescimento ou Renovação).

Permite que o bot detecte automaticamente qual formulário abrir (Crescimento
ou Renovação) com base no canal Slack de onde a solicitação foi iniciada
(slash command ou botão fixo no canal).

Configure via .env:
  CHANNEL_ID_CRESCIMENTO=C0123456789
  CHANNEL_ID_RENOVACAO=C0987654321

Se o canal de origem não estiver mapeado (ou não puder ser recuperado), o
bot não assume um tipo por padrão: o modal pede que o consultor escolha
manualmente o Tipo de Solicitação antes de ver o restante do formulário.
"""

import os
from typing import Dict, Optional

FLUXO_CRESCIMENTO = "crescimento"
FLUXO_RENOVACAO = "renovacao"

_channel_crescimento = os.environ.get("CHANNEL_ID_CRESCIMENTO", "").strip()
_channel_renovacao = os.environ.get("CHANNEL_ID_RENOVACAO", "").strip()

FLOW_BY_CHANNEL: Dict[str, str] = {}
if _channel_crescimento:
    FLOW_BY_CHANNEL[_channel_crescimento] = FLUXO_CRESCIMENTO
if _channel_renovacao:
    FLOW_BY_CHANNEL[_channel_renovacao] = FLUXO_RENOVACAO


def resolver_tipo_fluxo(channel_id: Optional[str]) -> Optional[str]:
    """
    Resolve o tipo de fluxo (crescimento/renovacao) a partir do canal de
    origem. Retorna None se o canal não estiver mapeado ou for inválido -
    nesse caso o modal deve pedir a escolha manual ao consultor.
    """
    if not channel_id:
        return None
    return FLOW_BY_CHANNEL.get(channel_id)
