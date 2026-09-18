"""
Configuração e Regras de Acesso para o Perfil de @triagem.
Permite definir quais usuários do Slack têm autorização para:
- Substituir aprovadores por ausência
- Alterar alçadas em contingência
"""

import os
from typing import List

# ⚠️ Nunca default para "true": liberaria @triagem e aprovação para qualquer usuário do
# Slack. Defina como "true" apenas via .env em ambiente de desenvolvimento/homologação.
USE_MOCK_USERS = os.environ.get("USE_MOCK_USERS", "false").lower() == "true"
TEST_ALLOW_SELF_APPROVAL = os.environ.get("TEST_ALLOW_SELF_APPROVAL", "false").lower() == "true"

# Lista de IDs de usuários Slack com perfil oficial de @triagem
# Pode ser configurada via .env como: TRIAGEM_USER_IDS="U0123...,U0456..."
_raw_triagem_ids = os.environ.get("TRIAGEM_USER_IDS", "")
TRIAGEM_USER_IDS: List[str] = [uid.strip() for uid in _raw_triagem_ids.split(",") if uid.strip()]

# Nomes de aprovadores que pertencem à triagem na governança Arco
TRIAGEM_MEMBERS_NAMES = [
    "Rafael Martinez",
    "Rafael Bae",
    "Aline Del Pezzo",
]


def is_user_triagem(user_id: str, user_name: str = "") -> bool:
    """
    Verifica se o usuário possui permissão de @triagem.
    Em modo de teste (USE_MOCK_USERS ou TEST_ALLOW_SELF_APPROVAL),
    permite a ação do usuário testador para validação fluida.
    """
    if not user_id:
        return False

    # Em ambiente de teste / homologação com mock, o testador é autorizado
    if USE_MOCK_USERS or TEST_ALLOW_SELF_APPROVAL:
        return True

    # Verifica se o ID está cadastrado na lista explícita de Triagem
    if user_id in TRIAGEM_USER_IDS:
        return True

    # Fallback transitório por nome, enquanto TRIAGEM_USER_IDS não está com os IDs reais
    # preenchidos. Não checa mais o substring genérico "triagem": qualquer usuário poderia
    # se autopromover apenas incluindo a palavra no próprio nome/username do Slack.
    u_lower = (user_name or "").lower()
    for m in TRIAGEM_MEMBERS_NAMES:
        if m.lower() in u_lower:
            return True

    return False
