"""
Aba Início (App Home) do bot: uma visão por perfil, montada sob demanda para
cada pessoa que abre a aba (consultor, aprovador, @triagem, ou combinações).
"""

import logging
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from config.triagem_config import is_user_triagem
from services.painel_service import calcular_metricas
from services.ticket_service import _is_sla_vencido, load_tickets

logger = logging.getLogger(__name__)

MAX_ITENS_POR_SECAO = 15


def _secao_aprovador(pendentes: List[Tuple[Dict[str, Any], Dict[str, Any]]]) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": "✅ Para você decidir", "emoji": True}}
    ]
    for ticket, apprv in pendentes[:MAX_ITENS_POR_SECAO]:
        rotulo = apprv.get("checklist_label") or apprv.get("short_label") or apprv.get("role_title", "Alçada")
        aviso = "\n🚨 *SLA vencido*" if _is_sla_vencido(apprv) else ""
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{ticket.get('escola', 'Escola')}*\n{rotulo}{aviso}"},
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Decidir"},
                "action_id": "home_btn_decidir",
                "value": ticket["key"],
            },
        })
    if len(pendentes) > MAX_ITENS_POR_SECAO:
        restante = len(pendentes) - MAX_ITENS_POR_SECAO
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"+{restante} outra(s) pendência(s)."}]})
    blocks.append({"type": "divider"})
    return blocks


def _secao_consultor(meus_pedidos: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": "📋 Meus pedidos", "emoji": True}}
    ]
    for status, titulo in (("pending", "⏳ Pendentes"), ("completed", "✅ Aprovados"), ("rejected", "❌ Reprovados (precisam de ajuste)")):
        itens = meus_pedidos.get(status) or []
        if not itens:
            continue
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*{titulo}* ({len(itens)})"}})
        for ticket in itens[:MAX_ITENS_POR_SECAO]:
            permalink = ticket.get("thread_permalink")
            link = f" — <{permalink}|abrir thread>" if permalink else ""
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"• {ticket.get('escola', 'Escola')}{link}"}})
    blocks.append({"type": "divider"})
    return blocks


def _secao_triagem() -> List[Dict[str, Any]]:
    m = calcular_metricas()
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "🗂️ Fila geral (@triagem)", "emoji": True}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Na fila:*\n{m['na_fila']} solicitação(ões)"},
                {"type": "mrkdwn", "text": f"*SLAs vencidos:*\n{m['alcadas_vencidas']} alçada(s) em {m['tickets_vencidos']} pedido(s)"},
            ],
        },
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "Use `/postar-painel` ou `!painel` no canal para o painel completo e sempre atualizado."}]},
        {"type": "divider"},
    ]


def build_home_view(user_id: str, check_approval_authorization: Callable[[Dict[str, Any], str], Tuple[bool, bool]]) -> Dict[str, Any]:
    """Monta a view da aba Início de `user_id`, de acordo com o(s) perfil(is) que ele tem nos tickets ativos."""
    tickets = load_tickets()
    pendentes_aprovar: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    meus_pedidos: Dict[str, List[Dict[str, Any]]] = {"pending": [], "completed": [], "rejected": []}

    for ticket in tickets.values():
        if ticket.get("consultor_id") == user_id:
            meus_pedidos.setdefault(ticket.get("status", "pending"), []).append(ticket)

        if ticket.get("status") in ("completed", "rejected"):
            continue
        for apprv in ticket.get("approvals", {}).values():
            if apprv.get("status") != "pending":
                continue
            try:
                autorizado, _ = check_approval_authorization(apprv, user_id)
            except Exception as e:
                logger.warning(f"Erro ao checar autorização na aba Início: {e}")
                autorizado = False
            if autorizado:
                pendentes_aprovar.append((ticket, apprv))

    is_aprovador = bool(pendentes_aprovar)
    is_consultor = any(meus_pedidos.values())
    is_triagem = is_user_triagem(user_id)

    blocks: List[Dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Bem-vindo(a) ao DeAcordo* :handshake:\nAqui você acompanha suas aprovações pendentes e seus pedidos."}},
        {"type": "divider"},
    ]

    if is_aprovador:
        blocks += _secao_aprovador(pendentes_aprovar)
    if is_consultor:
        blocks += _secao_consultor(meus_pedidos)
    if is_triagem:
        blocks += _secao_triagem()

    if not (is_aprovador or is_consultor or is_triagem):
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Nenhuma pendência por aqui agora. Quando você tiver uma solicitação como consultor(a) "
                        "ou uma alçada para aprovar, elas aparecem nesta aba.",
            },
        })

    return {"type": "home", "blocks": blocks}


def _usuarios_envolvidos(ticket: Dict[str, Any], extra_user_ids: Optional[Iterable[str]] = None) -> List[str]:
    user_ids = set()
    consultor_id = ticket.get("consultor_id") or ""
    if consultor_id.startswith(("U", "W")):
        user_ids.add(consultor_id)
    for apprv in ticket.get("approvals", {}).values():
        candidatos = [apprv.get("approver_id"), apprv.get("original_approver_id")] + (apprv.get("approver_ids") or [])
        for uid in candidatos:
            if uid and str(uid).startswith(("U", "W")):
                user_ids.add(uid)
    for uid in extra_user_ids or []:
        if uid:
            user_ids.add(uid)
    return list(user_ids)


def atualizar_home_dos_usuarios(
    client,
    ticket: Dict[str, Any],
    check_approval_authorization: Callable[[Dict[str, Any], str], Tuple[bool, bool]],
    extra_user_ids: Optional[Iterable[str]] = None,
) -> None:
    """Republica a aba Início de quem está diretamente envolvido no ticket (consultor e aprovadores atuais/anteriores)."""
    for uid in _usuarios_envolvidos(ticket, extra_user_ids):
        try:
            client.views_publish(user_id=uid, view=build_home_view(uid, check_approval_authorization))
        except Exception as e:
            logger.warning(f"Não foi possível atualizar a aba Início de {uid}: {e}")
