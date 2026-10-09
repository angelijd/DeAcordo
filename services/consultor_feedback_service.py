"""
Serviço de Notificações e Feedback em Tempo Real para o Consultor (DM Privada).
Garante visibilidade proativa com stepper visual de alçadas, celebração de conclusão 100%
e orientações claras e empáticas em caso de reprovação comercial.
"""

import logging
from typing import Dict, Any, Tuple, Optional

from config.triagem_config import USE_MOCK_USERS

logger = logging.getLogger("consultor_feedback_service")


def _resolve_consultor_target(ticket: Dict[str, Any], fallback_user_id: str = "") -> Tuple[Optional[str], bool, str]:
    """
    Identifica o destinatário de DM do consultor.
    Se o consultor não for um ID de Slack real e estiver em modo de teste,
    utiliza o fallback_user_id (o usuário que executou a ação) para validação visual.
    """
    consultor_id = ticket.get("consultor_id")
    consultor_name = ticket.get("consultor_name", "Consultor")

    if consultor_id and consultor_id.startswith(("U", "W")):
        return consultor_id, False, consultor_name
    elif USE_MOCK_USERS and fallback_user_id:
        return fallback_user_id, True, consultor_name

    return None, False, consultor_name


def _arroba(nome: str) -> str:
    """Nome do consultor com @, sem duplicar quando já é uma menção do Slack (<@U...>)."""
    nome = nome or "Consultor"
    return nome if nome.startswith(("<@", "@")) else f"@{nome}"


def _resumo_ajustes(ticket: Dict[str, Any]) -> str:
    linhas = []
    for a in ticket.get("approvals", {}).values():
        if a.get("status") != "rejected":
            continue
        rotulo = a.get("checklist_label") or a.get("short_label") or a.get("role_title", "Alçada")
        detalhe = f": _{a['details']}_" if a.get("details") else ""
        linhas.append(f"• *{rotulo}* · {a.get('reason_label') or 'Reprovado'}{detalhe}")
    return "\n".join(linhas)


def send_consultor_progress_dm(
    client,
    ticket: Dict[str, Any],
    last_approval_key: str,
    actor_id: str,
    actor_name: str,
):
    """
    Envia uma notificação em tempo real na DM privada do consultor informando sobre o avanço
    das aprovações de sua solicitação, com checklist / stepper visual do pipeline.
    Se 100% concluído, envia a celebração formal de liberação de contrato.
    """
    target_id, is_mock, consultor_name = _resolve_consultor_target(ticket, actor_id)
    if not target_id:
        logger.warning(f"Consultor '{consultor_name}' sem ID de Slack e mock desativado. Notificação DM ignorada.")
        return

    escola = ticket.get("escola", "Escola")
    permalink = ticket.get("thread_permalink") or "#"
    approvals = ticket.get("approvals", {})
    total_count = len(approvals)
    approved_count = sum(1 for a in approvals.values() if a.get("status") == "approved")
    all_completed = (ticket.get("status") == "completed") or (approved_count == total_count and total_count > 0)
    reprovadas = [a.get("short_label", "Exceção") for a in approvals.values() if a.get("parcial") and a.get("status") == "rejected"]
    parcial = bool(reprovadas)

    # Constrói o Stepper visual com ícones e status
    stepper_lines = []
    for idx, (k, a) in enumerate(approvals.items(), 1):
        status = a.get("status")
        label = a.get("short_label", a.get("role_title", "Alçada"))
        if status == "approved":
            apprv_by = a.get("approved_by_name") or a.get("approver_name") or "Aprovador"
            apprv_at = a.get("approved_at", "")
            time_info = f" ({apprv_at})" if apprv_at else ""
            stepper_lines.append(f"✅ *{idx}. {label}:* Aprovado por @{apprv_by}{time_info}")
        elif status == "rejected":
            rej_by = a.get("rejected_by_name") or a.get("approver_name") or "Aprovador"
            stepper_lines.append(f"❌ *{idx}. {label}:* Reprovado por @{rej_by}")
        else:
            pending_name = a.get("approver_name") or "Aprovador"
            sub_note = " _(Substituto ativo)_" if a.get("is_substituted") else ""
            stepper_lines.append(f"⏳ *{idx}. {label}:* Aguardando @{pending_name}{sub_note}")

    stepper_text = "\n".join(stepper_lines)

    if ticket.get("status") == "rejected":
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "❌ Solicitação Reprovada (ajustes necessários)", "emoji": True}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{_arroba(consultor_name)}, todas as alçadas da escola *{escola}* deliberaram. Ajustes pedidos:\n"
                        f"{_resumo_ajustes(ticket)}\n\n"
                        f"*Pipeline ({approved_count}/{total_count} aprovadas):*\n{stepper_text}"
                    )[:2900],
                },
            },
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"🔗 <{permalink}|Ver os apontamentos na thread do canal>"}]},
        ]
        msg_text = f"❌ Sua solicitação para {escola} precisa de ajustes."
    elif all_completed:
        if parcial:
            abertura = (
                f"{_arroba(consultor_name)}, todas as alçadas da escola *{escola}* deliberaram. "
                f"Exceções reprovadas, que ficam fora do contrato: *{', '.join(reprovadas)}*.\n\n"
            )
        else:
            abertura = f"Parabéns, {_arroba(consultor_name)}! Todas as alçadas necessárias deram o aceite para a escola *{escola}*!\n\n"
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🟡 Solicitação Concluída (aprovação parcial)" if parcial else "🎉 Solicitação 100% Aprovada!", "emoji": True}
            }
        ]
        if is_mock:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"🧪 *[MODO DE TESTE]* Simulando feedback para o Consultor: *{_arroba(consultor_name)}*"}]
            })
        blocks.extend([
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        abertura
                        + f"*Pipeline de Aprovação Concluído ({approved_count}/{total_count}):*\n{stepper_text}\n\n"
                        + ("📄 *Próximo Passo:* Você pode acessar as deliberações na thread."
                           if parcial else
                           "📄 *Próximo Passo:* O ticket foi formalmente concluído no canal de negociações e a proposta está 100% liberada para emissão e assinatura de contrato.")
                    )
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"🔗 <{permalink}|Ver encerramento e auditoria na thread do canal>"
                    }
                ]
            }
        ])
        msg_text = f"🟡 Sua solicitação para {escola} foi concluída com aprovação parcial." if parcial else f"🎉 Parabéns! Sua solicitação para {escola} foi 100% aprovada!"
    else:
        # Notificação de Progresso Incremental
        last_apprv = approvals.get(last_approval_key, {})
        last_label = last_apprv.get("role_title") or last_apprv.get("short_label") or "Alçada"

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"📋 Atualização: {escola[:110]}", "emoji": True}
            }
        ]
        if is_mock:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"🧪 *[MODO DE TESTE]* Simulando feedback para o Consultor: *{_arroba(consultor_name)}*"}]
            })
        blocks.extend([
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"Olá {_arroba(consultor_name)}, uma nova etapa foi aprovada em sua solicitação!\n"
                        f"• *Alçada Aprovada:* *{last_label}* por @{actor_name}\n\n"
                        f"*Andamento das Alçadas ({approved_count}/{total_count}):*\n{stepper_text}"
                    )
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"🔗 <{permalink}|Acompanhar negociação em tempo real na thread>"
                    }
                ]
            }
        ])
        msg_text = f"📋 Progresso da solicitação para {escola}: {last_label} aprovada."

    try:
        client.chat_postMessage(unfurl_links=False, unfurl_media=False,
            channel=target_id,
            text=msg_text,
            blocks=blocks
        )
        logger.info(f"Feedback de progresso enviado com sucesso para o consultor {target_id} ({escola})")
    except Exception as e:
        logger.error(f"Erro ao enviar DM de feedback para o consultor {target_id}: {e}")


def send_consultor_rejection_dm(
    client,
    ticket: Dict[str, Any],
    rejection_data: Dict[str, Any],
    fallback_user_id: str = "",
):
    """
    Envia card estruturado, empático e com orientações na DM privada do consultor
    quando a solicitação comercial for reprovada por qualquer alçada.
    """
    target_id, is_mock, consultor_name = _resolve_consultor_target(ticket, fallback_user_id)
    if not target_id:
        logger.warning(f"Consultor '{consultor_name}' sem ID de Slack e mock desativado. Notificação DM de reprovação ignorada.")
        return

    escola = ticket.get("escola", "Escola")
    permalink = ticket.get("thread_permalink") or "#"
    role_title = rejection_data.get("role_title", "Alçada")
    rejected_by_name = rejection_data.get("rejected_by_name", "Aprovador")
    reason_label = rejection_data.get("reason_label", "Solicitação Reprovada")
    details = (rejection_data.get("details") or "").strip() or "Sem justificativa detalhada registrada."
    parcial = bool(rejection_data.get("parcial"))
    if ticket.get("status") == "rejected":
        proximos_passos = (
            "Todas as alçadas já decidiram. Ajustes pedidos:\n" + _resumo_ajustes(ticket)
        )
    elif ticket.get("status") == "completed":
        proximos_passos = (
            "Todas as alçadas já decidiram. Verifique os pareceres na thread."
        )
    elif parcial:
        proximos_passos = (
            "Essa exceção sai do pedido e as demais alçadas seguem normalmente. "
            "Se quiser rediscutir a exceção, alinhe os ajustes com o aprovador."
        )
    else:
        proximos_passos = (
            "As demais alçadas seguem analisando. "
            "Quando todos decidirem, você recebe o resumo aqui."
        )

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "❌ Solicitação Reprovada (ajustes necessários)" if ticket.get("status") == "rejected" else ("❌ Exceção Reprovada" if parcial else "❌ Alçada Reprovada"), "emoji": True}
        }
    ]
    if is_mock:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"🧪 *[MODO DE TESTE]* Simulando feedback para o Consultor: *{_arroba(consultor_name)}*"}]
        })

    blocks.extend([
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*🏫 Escola:*\n{escola}"},
                {"type": "mrkdwn", "text": f"*📋 Alçada:*\n{role_title}"},
                {"type": "mrkdwn", "text": f"*👤 Decisor:*\n@{rejected_by_name}"},
                {"type": "mrkdwn", "text": f"*Motivo Formal:*\n{reason_label}"},
            ]
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*📌 Justificativa / Apontamentos do Aprovador:*\n> \"_{details}_\""
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "💡 *Orientações & Próximos Passos:*\n" + proximos_passos
                )
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"🔗 <{permalink}|Ver histórico completo e apontamentos na thread do canal>"
                }
            ]
        }
    ])

    try:
        client.chat_postMessage(unfurl_links=False, unfurl_media=False,
            channel=target_id,
            text=f"❌ Atenção: {role_title} reprovada por @{rejected_by_name} ({escola}).",
            blocks=blocks
        )
        logger.info(f"Notificação de reprovação enviada com sucesso para o consultor {target_id} ({escola})")
    except Exception as e:
        logger.error(f"Erro ao enviar DM de reprovação para o consultor {target_id}: {e}")
