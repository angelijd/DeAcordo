import json
import os
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from services.ticket_service import DATA_DIR, BR_TZ, load_tickets, _is_sla_vencido
from utils.currency_words import parse_currency_str, format_real_input

logger = logging.getLogger(__name__)

PAINEL_FILE = os.path.join(DATA_DIR, "painel_state.json")


def _load_painel() -> Dict[str, Any]:
    try:
        with open(PAINEL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_painel(state: Dict[str, Any]) -> None:
    with open(PAINEL_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def calcular_metricas(tickets: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    tickets = load_tickets() if tickets is None else tickets
    pendentes = [t for t in tickets.values() if t.get("status") == "pending"]
    valor_fila = 0.0
    for t in pendentes:
        valor_fila += parse_currency_str((t.get("extra_data") or {}).get("acv")) or 0.0
    alcadas_vencidas = 0
    tickets_vencidos = 0
    for t in pendentes:
        vencidas = [a for a in (t.get("approvals") or {}).values() if a.get("status") == "pending" and _is_sla_vencido(a)]
        alcadas_vencidas += len(vencidas)
        tickets_vencidos += 1 if vencidas else 0
    return {
        "na_fila": len(pendentes),
        "valor_fila": valor_fila,
        "alcadas_vencidas": alcadas_vencidas,
        "tickets_vencidos": tickets_vencidos,
        "aprovados": sum(1 for t in tickets.values() if t.get("status") == "completed"),
    }


def build_painel_blocks(m: Dict[str, Any]) -> List[Dict[str, Any]]:
    valor = format_real_input(f"{m['valor_fila']:.2f}".replace(".", ",")) if m["valor_fila"] else "0,00"
    agora = datetime.now(BR_TZ).strftime("%d/%m às %H:%M")
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "📊 Painel de Aprovações", "emoji": True}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*🚨 SLAs vencidos agora*\n{m['alcadas_vencidas']} alçada(s) em {m['tickets_vencidos']} solicitação(ões)"},
                {"type": "mrkdwn", "text": f"*💵 Na fila de aprovação*\nR$ {valor} em {m['na_fila']} solicitação(ões)"},
                {"type": "mrkdwn", "text": f"*✅ Aprovados (total)*\n{m['aprovados']}"},
            ],
        },
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Atualizado em {agora}"}]},
    ]


def postar_painel(client, channel_id: str) -> None:
    """Posta um novo painel no canal, tenta fixar e passa a atualizar esta mensagem."""
    blocks = build_painel_blocks(calcular_metricas())
    resp = client.chat_postMessage(channel=channel_id, text="Painel de Aprovações", blocks=blocks)
    try:
        client.pins_add(channel=channel_id, timestamp=resp["ts"])
    except Exception as e:
        logger.warning(f"Não foi possível fixar o painel automaticamente (escopo pins:write?): {e}")
    _save_painel({"channel_id": channel_id, "ts": resp["ts"], "blocks": blocks[1:2]})


def atualizar_painel(client) -> None:
    """Atualiza o painel fixado, só quando os números mudaram."""
    state = _load_painel()
    if not state.get("ts"):
        return
    blocks = build_painel_blocks(calcular_metricas())
    if state.get("blocks") == blocks[1:2]:
        return
    try:
        client.chat_update(channel=state["channel_id"], ts=state["ts"], text="Painel de Aprovações", blocks=blocks)
        state["blocks"] = blocks[1:2]
        _save_painel(state)
    except Exception as e:
        logger.warning(f"Erro ao atualizar o painel: {e}")
