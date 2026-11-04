"""
Serviço de troca de aprovadores pela @triagem (provisória com data de corte ou permanente).
Persiste as trocas em substitutions_state.json.
"""

import os
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

FUSO_BRASILIA = ZoneInfo("America/Sao_Paulo")
from typing import Dict, Any, List, Optional

logger = logging.getLogger("substitution_service")

# Mesmo DATA_DIR usado por services/ticket_service.py - ver comentário lá.
DATA_DIR = os.environ.get("DATA_DIR") or os.path.dirname(os.path.dirname(__file__))
SUBSTITUTIONS_FILE = os.path.join(DATA_DIR, "substitutions_state.json")


def _load_substitutions_state() -> Dict[str, Any]:
    if not os.path.exists(SUBSTITUTIONS_FILE):
        return {"substitutions": []}
    try:
        with open(SUBSTITUTIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        # Não devolve estado vazio: o próximo salvamento apagaria todas as trocas registradas.
        logger.error(f"Erro ao ler substitutions_state.json: {e}")
        raise


def _save_substitutions_state(state: Dict[str, Any]):
    try:
        os.makedirs(os.path.dirname(SUBSTITUTIONS_FILE) or ".", exist_ok=True)
        tmp = SUBSTITUTIONS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp, SUBSTITUTIONS_FILE)
    except Exception as e:
        logger.error(f"Erro ao salvar substitutions_state.json: {e}")
        raise


def registrar_substituicao(
    ticket_key: str,
    approval_key: str,
    role_title: str,
    original_approver_id: str,
    original_approver_name: str,
    new_approver_id: str,
    new_approver_name: str,
    until_date: str,
    reason: str,
    triagem_user_id: str,
) -> Dict[str, Any]:
    """
    Registra uma troca de aprovador. until_date vazio = troca permanente.
    """
    state = _load_substitutions_state()
    record = {
        "id": f"SUB-{int(datetime.now().timestamp())}",
        "ticket_key": ticket_key,
        "approval_key": approval_key,
        "role_title": role_title,
        "original_approver_id": original_approver_id,
        "original_approver_name": original_approver_name,
        "new_approver_id": new_approver_id,
        "new_approver_name": new_approver_name,
        "until_date": until_date,
        "reason": reason or "",
        "substituted_by": triagem_user_id,
        "created_at": datetime.now(FUSO_BRASILIA).strftime("%d/%m/%Y às %H:%M"),
    }
    state.setdefault("substitutions", []).append(record)
    _save_substitutions_state(state)
    logger.info(f"Substituição registrada: {original_approver_name} -> {new_approver_name} até {until_date} no ticket {ticket_key}")
    return record


def get_substitutions_for_ticket(ticket_key: str) -> List[Dict[str, Any]]:
    """Retorna o histórico de substituições de um ticket específico."""
    state = _load_substitutions_state()
    return [s for s in state.get("substitutions", []) if s.get("ticket_key") == ticket_key]


def get_active_substitute(original_approver_name: str, check_date_str: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Verifica se há um substituto ativo para o aprovador na data indicada.
    check_date_str no formato YYYY-MM-DD. Se omitido, usa a data de hoje.
    """
    if not original_approver_name:
        return None
        
    state = _load_substitutions_state()
    today_str = check_date_str or datetime.now(FUSO_BRASILIA).strftime("%Y-%m-%d")

    # Percorre as substituições mais recentes primeiro
    for s in reversed(state.get("substitutions", [])):
        if s.get("original_approver_name", "").lower() == original_approver_name.lower():
            until = s.get("until_date") or ""
            if not until or until >= today_str:
                return s

    return None
