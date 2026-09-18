"""
Serviço de Mensagens Diretas (DM Privada) para Aprovação Executiva e Contingência.
Implementa o 'Card de Decisão em 3 Segundos' com grid 2x2, escopo específico e links de contexto.
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
    Utiliza arquitetura de escaneabilidade rápida:
    - Cabeçalho claro
    - Grid 2x2 com Escola, Consultor, ACV e Marcas
    - Destaque em citação do escopo específico daquela alçada
    - Botões de ação em 1 clique
    """
    ticket_key = ticket["key"]
    escola = ticket.get("escola", "Escola")
    consultor_name = ticket.get("consultor_name", "Consultor")
    acv = ticket.get("acv") or ticket.get("extra_data", {}).get("acv") or "Não informado"
    marcas = ticket.get("marcas") or ticket.get("extra_data", {}).get("marcas") or "Não informada"
    approvals = ticket.get("approvals", {})
    permalink = ticket.get("thread_permalink") or "#"

    for key, apprv in approvals.items():
        if apprv.get("status") == "approved":
            continue

        approver_id = apprv.get("approver_id")
        approver_name = apprv.get("approver_name", "Aprovador")
        role_title = apprv.get("role_title", "Aprovação")
        short_label = apprv.get("short_label", "Aprovação")
        scope_reason = apprv.get("scope_reason") or "Aprovação necessária conforme governança do ciclo comercial."

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
            header_text = f"🔔 Solicitação de Aprovação: {short_label[:100]}"

            blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": header_text, "emoji": True}
                }
            ]

            if is_mock_target:
                blocks.append({
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"🧪 *[MODO DE TESTE]* Simulando envio para: *@{approver_name}* ({role_title})"}
                    ]
                })

            # Grid 2x2 com os dados essenciais da negociação
            blocks.append({
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*🏫 Escola:*\n{escola}"},
                    {"type": "mrkdwn", "text": f"*👤 Consultor:*\n{consultor_name}"},
                    {"type": "mrkdwn", "text": f"*💵 Contrato (ACV):*\n{acv}"},
                    {"type": "mrkdwn", "text": f"*📦 Marcas:*\n{marcas}"},
                ]
            })

            # Bloco em destaque com a razão específica da deliberação
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*📌 O que requer sua aprovação ({short_label}):*\n> {scope_reason}"
                }
            })

            # Botões de ação em 1 clique
            blocks.append({
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
            })

            # Contexto e link direto para a thread do canal
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"🔗 <{permalink}|Ver negociação completa no canal> • ⏱️ *Decisão rápida em 1 clique*"
                    }
                ]
            })

            # Envia diretamente para o usuário
            msg_resp = client.chat_postMessage(
                channel=target_user_id,
                text=f"Aprovação solicitada para {escola} ({short_label})",
                blocks=blocks,
            )

            dm_channel_id = str(msg_resp.get("channel", target_user_id)) if hasattr(msg_resp, "get") else str(target_user_id)
            msg_ts = msg_resp.get("ts", "") if hasattr(msg_resp, "get") else ""
            apprv["dm_channel_id"] = str(dm_channel_id)
            apprv["dm_msg_ts"] = str(msg_ts)
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
    Envia card específico para o novo aprovador substituto designado pela @triagem,
    com badge de substituição, grid 2x2 e contextualização da ausência.
    """
    ticket_key = ticket["key"]
    escola = ticket.get("escola", "Escola")
    consultor_name = ticket.get("consultor_name", "Consultor")
    acv = ticket.get("acv") or ticket.get("extra_data", {}).get("acv") or "Não informado"
    marcas = ticket.get("marcas") or ticket.get("extra_data", {}).get("marcas") or "Não informada"
    apprv = ticket.get("approvals", {}).get(approval_key, {})
    permalink = ticket.get("thread_permalink") or "#"

    approver_id = apprv.get("approver_id")
    approver_name = apprv.get("approver_name", "Aprovador Substituto")
    role_title = apprv.get("role_title", "Aprovação")
    short_label = apprv.get("short_label", "Aprovação")
    orig_name = apprv.get("original_approver_name", "Titular")
    until_date = apprv.get("substitute_until", "")
    sub_reason = apprv.get("substitution_reason", "Ausência temporária")
    scope_reason = apprv.get("scope_reason") or "Aprovação necessária conforme governança do ciclo comercial."

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
        header_text = f"🔄 Designação de Substituto: {short_label[:90]}"

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": header_text, "emoji": True}
            }
        ]

        if is_mock_target:
            blocks.append({
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"🧪 *[MODO DE TESTE]* Simulando envio para substituto: *@{approver_name}*"}
                ]
            })

        # Alerta de designação pela triagem
        motivo_txt = f" (Motivo: _{sub_reason}_)" if sub_reason else ""
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"🔄 *Você foi designado pela @triagem como Aprovador Substituto*\n"
                    f"• *Titular Ausente:* @{orig_name}\n"
                    f"• *Vigência da Substituição:* Válido até *{until_date}*{motivo_txt}"
                )
            }
        })

        # Grid 2x2 com os dados da negociação
        blocks.append({
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*🏫 Escola:*\n{escola}"},
                {"type": "mrkdwn", "text": f"*👤 Consultor:*\n{consultor_name}"},
                {"type": "mrkdwn", "text": f"*💵 Contrato (ACV):*\n{acv}"},
                {"type": "mrkdwn", "text": f"*📦 Marcas:*\n{marcas}"},
            ]
        })

        # Citação com escopo de aprovação
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*📌 O que requer sua aprovação (em substituição a @{orig_name}):*\n> {scope_reason}"
            }
        })

        # Botões de deliberação
        blocks.append({
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
        })

        # Link de contexto
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"🔗 <{permalink}|Ver negociação completa na thread do canal> • ⏱️ *Decisão rápida em 1 clique*"
                }
            ]
        })

        msg_resp = client.chat_postMessage(
            channel=target_user_id,
            text=f"Aprovação solicitada como substituto para {escola} ({short_label})",
            blocks=blocks,
        )

        dm_channel_id = str(msg_resp.get("channel", target_user_id)) if hasattr(msg_resp, "get") else str(target_user_id)
        msg_ts = msg_resp.get("ts", "") if hasattr(msg_resp, "get") else ""
        apprv["dm_channel_id"] = str(dm_channel_id)
        apprv["dm_msg_ts"] = str(msg_ts)
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
