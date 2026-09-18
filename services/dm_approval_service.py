"""
Serviço de Mensagens Diretas (DM Privada) para Aprovação Executiva e Contingência.
"""

import os
import logging
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger("dm_approval_service")

USE_MOCK_USERS = os.environ.get("USE_MOCK_USERS", "true").lower() == "true"


def send_dm_approval_cards(client, ticket: Dict[str, Any], current_user_id: str):
    """
    Envia cards executivos individuais de aprovação na DM privada de cada aprovador.
    No modo de teste (mock), se o aprovador não tiver ID do Slack, envia para o usuário
    atual (testador) com indicação do papel para que ele possa validar a experiência completa.
    """
    ticket_key = ticket["key"]
    escola = ticket.get("escola", "Escola")
    approvals = ticket.get("approvals", {})
    permalink = ticket.get("thread_permalink") or "#"

    for key, apprv in approvals.items():
        if apprv.get("status") == "approved":
            continue

        approver_id = apprv.get("approver_id")
        approver_name = apprv.get("approver_name", "Aprovador")
        role_title = apprv.get("role_title", "Aprovação")
        short_label = apprv.get("short_label", "Aprovação")

        is_mock_target = False
        target_user_id = None

        if approver_id and approver_id.startswith(("U", "W")):
            target_user_id = approver_id
        elif USE_MOCK_USERS and current_user_id:
            target_user_id = current_user_id
            is_mock_target = True

        if not target_user_id:
            logger.warning(f"Aprovador '{approver_name}' ({key}) não possui ID de Slack e mock está desativado.")
            continue

        try:
            test_badge = f"🧪 *[MODO DE TESTE]* Simulando envio para: *@{approver_name}*\n" if is_mock_target else ""

            header_text = f"🔔 *Nova Solicitação de Aprovação - Ciclo CE 2027*\n{test_badge}"
            body_text = (
                f"*Escola:* {escola}\n"
                f"*Alçada Designada:* {role_title}\n"
                f"*Status Atual:* ⏳ Aguardando sua decisão\n\n"
                f"Você foi acionado para deliberar sobre esta solicitação comercial. "
                f"Avalie os dados e clique em uma das opções abaixo para registrar sua decisão instantaneamente."
            )

            blocks = [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": header_text}
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": body_text}
                },
                {
                    "type": "actions",
                    "block_id": f"dm_actions_{ticket_key}_{key}",
                    "elements": [
                        {
                            "type": "button",
                            "action_id": "btn_dm_aprovar",
                            "value": f"{ticket_key}:{key}",
                            "text": {"type": "plain_text", "text": f"✅ Aprovar {short_label}", "emoji": True},
                            "style": "primary",
                        },
                        {
                            "type": "button",
                            "action_id": "btn_dm_rejeitar",
                            "value": f"{ticket_key}:{key}",
                            "text": {"type": "plain_text", "text": "❌ Reprovar", "emoji": True},
                            "style": "danger",
                        },
                    ]
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"🔗 <{permalink}|Ver detalhes completos na thread do canal de negociação>"
                        }
                    ]
                }
            ]

            # Envia diretamente para o ID do usuário (Slack resolve a DM automaticamente com chat:write)
            msg_resp = client.chat_postMessage(
                channel=target_user_id,
                text=f"Aprovação solicitada para {escola} ({role_title})",
                blocks=blocks,
            )

            dm_channel_id = msg_resp.get("channel", target_user_id)
            apprv["dm_channel_id"] = dm_channel_id
            apprv["dm_msg_ts"] = msg_resp["ts"]
            logger.info(f"Card de aprovação via DM enviado com sucesso para {target_user_id} ({key}) no canal {dm_channel_id}")

        except Exception as e:
            logger.error(f"Erro ao enviar DM de aprovação para {target_user_id}: {e}")

    try:
        from services.ticket_service import save_tickets, load_tickets
        all_t = load_tickets()
        all_t[ticket_key] = ticket
        save_tickets(all_t)
    except Exception as e:
        logger.warning(f"Erro ao persistir DM ts no ticket: {e}")


def send_dm_substitute_card(
    client,
    ticket: Dict[str, Any],
    approval_key: str,
    current_user_id: str,
):
    """
    Envia card específico para o novo aprovador substituto designado pela @triagem.
    """
    ticket_key = ticket["key"]
    escola = ticket.get("escola", "Escola")
    apprv = ticket.get("approvals", {}).get(approval_key, {})
    permalink = ticket.get("thread_permalink") or "#"

    approver_id = apprv.get("approver_id")
    approver_name = apprv.get("approver_name", "Aprovador Substituto")
    role_title = apprv.get("role_title", "Aprovação")
    short_label = apprv.get("short_label", "Aprovação")
    orig_name = apprv.get("original_approver_name", "Titular")
    until_date = apprv.get("substitute_until", "")

    target_user_id = None
    is_mock_target = False

    if approver_id and approver_id.startswith(("U", "W")):
        target_user_id = approver_id
    elif USE_MOCK_USERS and current_user_id:
        target_user_id = current_user_id
        is_mock_target = True

    if not target_user_id:
        logger.warning(f"Substituto '{approver_name}' não possui ID de Slack e mock está desativado.")
        return

    try:
        test_badge = f"🧪 *[MODO DE TESTE]* Simulando envio para substituto: *@{approver_name}*\n" if is_mock_target else ""

        header_text = f"🔄 *Designação de Aprovador Substituto - Ciclo CE 2027*\n{test_badge}"
        body_text = (
            f"*Escola:* {escola}\n"
            f"*Alçada Designada:* {role_title}\n"
            f"*Titular Ausente:* @{orig_name}\n"
            f"*Vigência da Substituição:* Válido até *{until_date}*\n\n"
            f"A equipe de *@triagem* designou você para deliberar sobre esta solicitação comercial durante a ausência do titular. "
            f"Avalie a negociação e registre sua decisão abaixo."
        )

        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": header_text}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": body_text}
            },
            {
                "type": "actions",
                "block_id": f"dm_actions_{ticket_key}_{approval_key}",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "btn_dm_aprovar",
                        "value": f"{ticket_key}:{approval_key}",
                        "text": {"type": "plain_text", "text": f"✅ Aprovar {short_label}", "emoji": True},
                        "style": "primary",
                    },
                    {
                        "type": "button",
                        "action_id": "btn_dm_rejeitar",
                        "value": f"{ticket_key}:{approval_key}",
                        "text": {"type": "plain_text", "text": "❌ Reprovar", "emoji": True},
                        "style": "danger",
                    },
                ]
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"🔗 <{permalink}|Ver detalhes completos na thread do canal de negociação>"
                    }
                ]
            }
        ]

        msg_resp = client.chat_postMessage(
            channel=target_user_id,
            text=f"Aprovação solicitada como substituto para {escola} ({role_title})",
            blocks=blocks,
        )

        dm_channel_id = msg_resp.get("channel", target_user_id)
        apprv["dm_channel_id"] = dm_channel_id
        apprv["dm_msg_ts"] = msg_resp["ts"]
        logger.info(f"Card de substituição via DM enviado para {target_user_id} ({approval_key}) no canal {dm_channel_id}")

        try:
            from services.ticket_service import save_tickets, load_tickets
            all_t = load_tickets()
            all_t[ticket_key] = ticket
            save_tickets(all_t)
        except Exception as e:
            logger.warning(f"Erro ao persistir substituição DM ts no ticket: {e}")

    except Exception as e:
        logger.error(f"Erro ao enviar DM de substituição para {target_user_id}: {e}")
