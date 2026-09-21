import os
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional

logger = logging.getLogger("ticket_service")

TICKETS_FILE = os.path.join(os.path.dirname(__file__), "..", "tickets_state.json")

BR_TZ = ZoneInfo("America/Sao_Paulo")

# Aprovadores com SLA diferenciado (2 dias úteis em vez do padrão de 24h)
SLA_2_DIAS_UTEIS_APPROVERS = {"Rafael Bae"}


def _add_business_days(start: datetime, business_days: int) -> datetime:
    """Soma dias úteis (seg-sex) a um datetime, preservando o horário."""
    current = start
    added = 0
    while added < business_days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # 0=seg ... 4=sex
            added += 1
    return current


def _compute_sla_due_at(approver_name: str) -> str:
    """
    Calcula o prazo (SLA) de resposta de um aprovador a partir de agora:
    - 2 dias úteis para aprovadores da lista SLA_2_DIAS_UTEIS_APPROVERS (ex: Rafael Bae)
    - 24h corridas (padrão) para os demais
    Retorna timestamp ISO em horário de Brasília.
    """
    now_br = datetime.now(BR_TZ)
    if approver_name in SLA_2_DIAS_UTEIS_APPROVERS:
        due = _add_business_days(now_br, 2)
    else:
        due = now_br + timedelta(hours=24)
    return due.isoformat()


def _is_sla_vencido(approval: Dict[str, Any]) -> bool:
    """Verifica se o prazo de SLA de uma alçada pendente já venceu."""
    due_str = approval.get("sla_due_at")
    if not due_str:
        return False
    try:
        due = datetime.fromisoformat(due_str)
    except ValueError:
        return False
    return datetime.now(BR_TZ) >= due


def _dentro_da_janela_de_cobranca() -> bool:
    """Só permite disparo de cobrança entre 08h e 17h no horário de Brasília."""
    hora_atual = datetime.now(BR_TZ).hour
    return 8 <= hora_atual < 17

def load_tickets() -> Dict[str, Any]:
    """Carrega o arquivo de estado dos tickets"""
    if not os.path.exists(TICKETS_FILE):
        return {}
    try:
        with open(TICKETS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Erro ao carregar tickets_state.json: {e}")
        return {}


def save_tickets(tickets: Dict[str, Any]):
    """Salva os tickets de forma persistente"""
    try:
        with open(TICKETS_FILE, "w", encoding="utf-8") as f:
            json.dump(tickets, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Erro ao salvar tickets_state.json: {e}")


def create_ticket(
    channel_id: str,
    thread_ts: str,
    escola: str,
    consultor_id: str,
    consultor_name: str,
    details_text: str,
    approvals_list: List[Dict[str, Any]],
    main_text_base: str = "",
    thread_permalink: Optional[str] = None,
    extra_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Registra um novo ticket com a lista de aprovadores individuais.
    Cada aprovador possui uma alçada, id do usuário esperado e status.
    """
    tickets = load_tickets()
    ticket_key = f"{channel_id}_{thread_ts}"

    approvals = {}
    for apprv in approvals_list:
        key = apprv["key"]  # ex: comercial, ops, n3
        orig_name = apprv["approver_name"]
        orig_id = apprv.get("approver_id") or ""

        # Verifica se há substituição temporária ativa cadastrada pela @triagem
        active_sub = None
        try:
            from services.substitution_service import get_active_substitute
            active_sub = get_active_substitute(orig_name)
        except Exception as e:
            logger.warning(f"Erro ao verificar substituição ativa para {orig_name}: {e}")

        if active_sub:
            eff_name = active_sub["new_approver_name"]
            eff_id = active_sub["new_approver_id"]
            is_sub = True
            sub_until = active_sub.get("until_date")
            sub_reason = active_sub.get("reason", "Ausência temporária")
        else:
            eff_name = orig_name
            eff_id = orig_id
            is_sub = False
            sub_until = None
            sub_reason = None

        approvals[key] = {
            "key": key,
            "role_title": apprv["role_title"],
            "short_label": apprv["short_label"],
            "approver_id": eff_id,
            "approver_name": eff_name,
            "scope_reason": apprv.get("scope_reason") or "Aprovação necessária conforme governança do ciclo comercial.",
            "status": "pending",  # pending | approved | rejected
            "approved_by_id": None,
            "approved_by_name": None,
            "approved_at": None,
            "sla_due_at": _compute_sla_due_at(eff_name),
            "is_substituted": is_sub,
            "original_approver_name": orig_name if is_sub else None,
            "original_approver_id": orig_id if is_sub else None,
            "substitute_until": sub_until,
            "substitution_reason": sub_reason,
        }

    ticket = {
        "key": ticket_key,
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "card_msg_ts": None,
        "escola": escola,
        "consultor_id": consultor_id,
        "consultor_name": consultor_name,
        "details_text": details_text,
        "main_text_base": main_text_base,
        "thread_permalink": thread_permalink,
        "status": "pending",  # pending | completed
        "created_at": datetime.now().strftime("%d/%m/%Y às %H:%M"),
        "approvals": approvals,
        "extra_data": extra_data or {},
        "acv": (extra_data or {}).get("acv") or "-",
        "marcas": (extra_data or {}).get("marcas") or "-",
        "cnpj": (extra_data or {}).get("cnpj") or "-",
        "inep": (extra_data or {}).get("inep") or "-",
        "valor_divida": (extra_data or {}).get("valor_divida"),
        "tem_divida_alta": (extra_data or {}).get("tem_divida_alta", False),
        "marcas_com_inviab": bool((extra_data or {}).get("marcas_com_inviab")),
    }

    tickets[ticket_key] = ticket
    save_tickets(tickets)
    logger.info(f"Ticket {ticket_key} criado para '{escola}' com {len(approvals)} alçada(s).")
    return ticket


def get_ticket(ticket_key: str) -> Optional[Dict[str, Any]]:
    tickets = load_tickets()
    return tickets.get(ticket_key)


def update_ticket_card_ts(ticket_key: str, card_msg_ts: str):
    tickets = load_tickets()
    if ticket_key in tickets:
        tickets[ticket_key]["card_msg_ts"] = card_msg_ts
        save_tickets(tickets)


def approve_step(
    ticket_key: str,
    approval_key: str,
    user_id: str,
    user_name: str,
) -> Dict[str, Any]:
    """
    Registra a aprovação de uma alçada individual e verifica se o ticket foi concluído.
    """
    tickets = load_tickets()
    ticket = tickets.get(ticket_key)
    if not ticket:
        return {"success": False, "error": "Ticket não encontrado."}

    approval = ticket["approvals"].get(approval_key)
    if not approval:
        return {"success": False, "error": "Alçada de aprovação não encontrada."}

    if approval["status"] == "approved":
        return {"success": True, "already_approved": True, "ticket": ticket}

    now_str = datetime.now().strftime("%d/%m às %Hh%M")
    approval["status"] = "approved"
    approval["approved_by_id"] = user_id
    approval["approved_by_name"] = user_name
    approval["approved_at"] = now_str

    # Verifica se todas as alçadas foram aprovadas
    all_completed = all(a["status"] == "approved" for a in ticket["approvals"].values())
    if all_completed:
        ticket["status"] = "completed"
        ticket["completed_at"] = now_str

    tickets[ticket_key] = ticket
    save_tickets(tickets)

    return {
        "success": True,
        "already_approved": False,
        "all_completed": all_completed,
        "ticket": ticket,
        "approval": approval,
    }


def reject_step(
    ticket_key: str,
    approval_key: str,
    user_id: str,
    user_name: str,
    reason_key: str,
    reason_label: str,
    details: str = "",
) -> Dict[str, Any]:
    """
    Registra a reprovação de uma alçada individual e encerra o ticket imediatamente como reprovado.
    """
    tickets = load_tickets()
    ticket = tickets.get(ticket_key)
    if not ticket:
        return {"success": False, "error": "Ticket não encontrado."}

    approval = ticket["approvals"].get(approval_key)
    if not approval:
        return {"success": False, "error": "Alçada não encontrada."}

    now_str = datetime.now().strftime("%d/%m às %Hh%M")
    approval["status"] = "rejected"
    approval["rejected_by_id"] = user_id
    approval["rejected_by_name"] = user_name
    approval["rejected_at"] = now_str
    approval["reason_key"] = reason_key
    approval["reason_label"] = reason_label
    approval["details"] = details

    # Marca todo o ticket como reprovado e encerrado
    ticket["status"] = "rejected"
    ticket["completed_at"] = now_str
    ticket["rejection_reason_key"] = reason_key
    ticket["rejection_reason_label"] = reason_label
    ticket["rejection_details"] = details
    ticket["rejected_by_id"] = user_id
    ticket["rejected_by_name"] = user_name
    ticket["rejected_role"] = approval.get("role_title", "Alçada")

    tickets[ticket_key] = ticket
    save_tickets(tickets)

    return {
        "success": True,
        "ticket": ticket,
        "approval": approval,
    }


def substitute_approver(
    ticket_key: str,
    approval_key: str,
    new_approver_id: str,
    new_approver_name: str,
    until_date: str,
    reason: str,
    triagem_user_id: str,
) -> Dict[str, Any]:
    """
    Atualiza o aprovador responsável de uma alçada pendente por motivo de ausência temporária.
    """
    tickets = load_tickets()
    ticket = tickets.get(ticket_key)
    if not ticket:
        return {"success": False, "error": "Ticket não encontrado."}

    approval = ticket["approvals"].get(approval_key)
    if not approval:
        return {"success": False, "error": "Alçada não encontrada."}

    original_name = approval.get("approver_name", "Aprovador")
    original_id = approval.get("approver_id", "")

    approval["approver_id"] = new_approver_id
    approval["approver_name"] = new_approver_name
    approval["is_substituted"] = True
    approval["original_approver_name"] = original_name
    approval["original_approver_id"] = original_id
    approval["substitute_until"] = until_date
    approval["substitution_reason"] = reason
    approval["substituted_by"] = triagem_user_id
    approval["substituted_at"] = datetime.now().strftime("%d/%m às %Hh%M")

    tickets[ticket_key] = ticket
    save_tickets(tickets)

    return {
        "success": True,
        "ticket": ticket,
        "approval": approval,
        "original_approver_name": original_name,
        "original_approver_id": original_id,
    }


def build_approval_blocks(ticket: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Gera os blocos do Block Kit para o card de status na thread.
    Exibe botões de Aprovar e Reprovar lado a lado, indicador de substituto por ausência
    e botão administrativo restrito da @triagem.
    """
    blocks = [
        {"type": "divider"},
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "📋 Status das Aprovações do Ticket", "emoji": True}
        }
    ]

    # Badges operacionais de destaque para a Triagem
    badges = []
    tem_divida_alta = ticket.get("tem_divida_alta") or ticket.get("extra_data", {}).get("tem_divida_alta")
    if tem_divida_alta:
        div_val = ticket.get("valor_divida") or ticket.get("extra_data", {}).get("valor_divida") or "> 50k"
        badges.append(f"🚨 *DÍVIDA CRÍTICA (R$ {div_val})*")

    tem_inviab = ticket.get("marcas_com_inviab") or ticket.get("extra_data", {}).get("marcas_com_inviab")
    if tem_inviab:
        badges.append("⚠️ *INVIABILIDADE DETECTADA*")

    if any(a.get("is_substituted") for a in ticket.get("approvals", {}).values()):
        badges.append("🔄 *SUBSTITUTO ATIVO*")

    if badges:
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "📌 *Alertas Operacionais (@triagem):* " + " • ".join(badges)
                }
            ]
        })

    is_rejected = (ticket.get("status") == "rejected")
    all_approved = (ticket.get("status") == "completed")
    approvals = ticket.get("approvals", {})

    # Se o ticket foi reprovado, estampa o banner de encerramento no topo
    if is_rejected:
        reprovador = ticket.get("rejected_by_name") or "Aprovador"
        motivo = ticket.get("rejection_reason_label") or "Solicitação Reprovada"
        detalhes = ticket.get("rejection_details") or "Sem detalhes adicionais."
        reprov_at = ticket.get("completed_at") or datetime.now().strftime("%d/%m às %Hh%M")
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"🚨 *SOLICITAÇÃO REPROVADA ({reprov_at})*\n"
                    f"• *Reprovado por:* @{reprovador} ({ticket.get('rejected_role', 'Alçada')})\n"
                    f"• *Motivo:* *{motivo}*\n"
                    f"• *Justificativa:* _{detalhes}_\n\n"
                    f"⚠️ *Status:* *Ticket encerrado.* Para dar andamento na negociação, "
                    f"o consultor deve realizar as adequações necessárias e submeter um novo formulário."
                )
            }
        })
        blocks.append({"type": "divider"})

    for key, apprv in approvals.items():
        role_title = apprv["role_title"]
        approver_name = apprv["approver_name"]
        status = apprv["status"]

        # Detalhe de substituição ativa por ausência
        substitute_badge = ""
        if apprv.get("is_substituted"):
            sub_until = apprv.get("substitute_until", "")
            orig_name = apprv.get("original_approver_name", "")
            substitute_badge = f"\n_🔄 Substituto temporário até {sub_until} (Titular ausente: @{orig_name})_"

        if status == "pending":
            if is_rejected:
                # Ticket cancelado por reprovação em outra alçada
                blocks.append({
                    "type": "section",
                    "block_id": f"approval_section_{key}",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{role_title}:* @{approver_name}{substitute_badge}\n*Status:* ⏹️ *Encerrado (Ticket Reprovado)*"
                    }
                })
            else:
                # Alçada pendente com botões de Aprovar e Reprovar
                blocks.append({
                    "type": "section",
                    "block_id": f"approval_section_{key}",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{role_title}:* @{approver_name}{substitute_badge}\n*Status:* ⏳ *Aguardando deliberação*"
                    }
                })
                blocks.append({
                    "type": "actions",
                    "block_id": f"approval_actions_{key}",
                    "elements": [
                        {
                            "type": "button",
                            "action_id": f"btn_aprovar_{key}",
                            "value": f"{ticket['key']}:{key}",
                            "text": {"type": "plain_text", "text": f"✅ Aprovar {apprv['short_label']}", "emoji": True},
                            "style": "primary"
                        },
                        {
                            "type": "button",
                            "action_id": f"btn_reprovar_{key}",
                            "value": f"{ticket['key']}:{key}",
                            "text": {"type": "plain_text", "text": "❌ Reprovar", "emoji": True},
                            "style": "danger"
                        }
                    ]
                })

        elif status == "approved":
            approved_at = apprv.get("approved_at", "Concluído")
            approver_display = apprv.get("approved_by_name") or approver_name
            blocks.append({
                "type": "section",
                "block_id": f"approval_section_{key}",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{role_title}:* @{approver_display}{substitute_badge}\n*Status:* ✅ *Aprovado em {approved_at}*"
                }
            })

        elif status == "rejected":
            rejected_at = apprv.get("rejected_at", "Reprovado")
            approver_display = apprv.get("rejected_by_name") or approver_name
            motivo_label = apprv.get("reason_label") or "Reprovado"
            blocks.append({
                "type": "section",
                "block_id": f"approval_section_{key}",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{role_title}:* @{approver_display}{substitute_badge}\n*Status:* ❌ *Reprovado em {rejected_at}* (Motivo: {motivo_label})"
                }
            })

    if all_approved:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "🎉 *TODAS AS ALÇADAS FORAM APROVADAS! Solicitação encerrada e liberada para emissão de contrato.*"
            }
        })
    elif not is_rejected:
        # Ações administrativas e de segurança apenas se o ticket ainda estiver pendente
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "🔒 *Validação de Identidade:* Apenas os aprovadores indicados podem aprovar/reprovar suas respectivas alçadas."
                }
            ]
        })
        blocks.append({
            "type": "actions",
            "block_id": "triagem_actions_block",
            "elements": [
                {
                    "type": "button",
                    "action_id": "btn_triagem_substituicao",
                    "value": ticket["key"],
                    "text": {"type": "plain_text", "text": "🔄 Substituir Aprovador por Ausência", "emoji": True}
                },
                {
                    "type": "button",
                    "action_id": "btn_triagem_cobrar_ticket",
                    "value": ticket["key"],
                    "text": {"type": "plain_text", "text": "🔔 Cobrar Pendências Deste Ticket", "emoji": True}
                }
            ]
        })

    blocks.append({"type": "divider"})
    return blocks


def build_thread_blocks(ticket: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Gera os blocos para a mensagem única do ticket no canal,
    unindo todos os dados do workflow no formato idêntico ao original e os botões interativos de deliberação.
    """
    blocks = []
    text = ticket.get("details_text") or ticket.get("main_text_base") or ""
    if text:
        # Divide com segurança se exceder o limite de 3000 caracteres do Slack por seção
        if len(text) > 2800:
            lines = text.split("\n")
            chunk = ""
            for line in lines:
                if len(chunk) + len(line) + 1 > 2800:
                    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk.strip()}})
                    chunk = line + "\n"
                else:
                    chunk += line + "\n"
            if chunk.strip():
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk.strip()}})
        else:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text.strip()
                }
            })
    blocks.extend(build_approval_blocks(ticket))
    return blocks


def build_main_post_blocks(ticket: Dict[str, Any], permalink: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retorna a mesma estrutura unificada para que tudo viva em 1 mensagem só.
    """
    return build_thread_blocks(ticket)


def get_pending_tickets() -> List[Dict[str, Any]]:
    """Retorna todos os tickets que ainda possuem alçadas pendentes"""
    tickets = load_tickets()
    pending = []
    for t in tickets.values():
        if t.get("status") == "pending":
            pending.append(t)
    return pending


def executar_cobranca_pendencias(client) -> int:
    """
    Varre os tickets ativos e cobra, apenas via DM, os aprovadores cujo prazo de SLA
    já venceu (24h padrão, ou 2 dias úteis para aprovadores com SLA diferenciado).
    Só dispara dentro da janela 08h-17h (horário de Brasília).
    Retorna o total de lembretes enviados.
    """
    if not _dentro_da_janela_de_cobranca():
        logger.info("Cobrança inteligente ignorada: fora da janela permitida (08h-17h, horário de Brasília).")
        return 0

    pending_tickets = get_pending_tickets()
    total_cobrados = 0

    for t in pending_tickets:
        escola = t.get("escola", "Escola")

        aprovados = [
            a["short_label"] for a in t.get("approvals", {}).values() if a["status"] != "pending"
        ]
        aprovados_str = ", ".join(aprovados) if aprovados else "nenhuma alçada ainda"

        for p in t.get("approvals", {}).values():
            if p["status"] != "pending":
                continue
            if not _is_sla_vencido(p):
                continue

            approver_id = p.get("approver_id")
            approver_name = p.get("approver_name")
            if not (approver_id and approver_id.startswith(("U", "W"))):
                logger.warning(f"Cobrança de SLA ignorada para {approver_name}: sem ID de Slack válido para DM.")
                continue

            if aprovados:
                msg = f"🔔 *Lembrete (SLA vencido):* o {aprovados_str} já aprovaram. Falta apenas o seu clique de *{p['short_label']}* para liberar o contrato da *{escola}*!"
            else:
                msg = f"🔔 *Lembrete (SLA vencido):* a solicitação da *{escola}* aguarda sua aprovação de *{p['short_label']}* e o prazo já venceu."

            try:
                client.chat_postMessage(
                    channel=approver_id,
                    text=msg
                )
                total_cobrados += 1
            except Exception as e:
                logger.error(f"Erro ao enviar cobrança por DM para {approver_name}: {e}")

    logger.info(f"Cobrança inteligente concluída: {total_cobrados} lembrete(s) enviado(s) por DM.")
    return total_cobrados


def cobrar_pendencias_de_ticket(client, ticket_key: str, requested_by_user: str) -> Dict[str, Any]:
    """
    Dispara cobrança pontual focada nas alçadas pendentes deste ticket específico,
    postando alerta com menções na thread e disparando lembrete nas DMs dos aprovadores.
    """
    tickets = load_tickets()
    ticket = tickets.get(ticket_key)
    if not ticket:
        return {"success": False, "message": "⚠️ Ticket não encontrado no histórico ativo."}

    if ticket.get("status") in ("completed", "rejected"):
        return {"success": False, "message": f"⚠️ Este ticket já foi concluído como *{ticket.get('status')}*."}

    pendentes = [a for a in ticket.get("approvals", {}).values() if a.get("status") == "pending"]
    if not pendentes:
        return {"success": False, "message": "ℹ️ Não há alçadas pendentes para este ticket."}

    channel_id = ticket["channel_id"]
    thread_ts = ticket["thread_ts"]
    escola = ticket.get("escola", "Escola")

    mentions = []
    labels = []
    for p in pendentes:
        approver_id = p.get("approver_id")
        approver_name = p.get("approver_name", "Aprovador")
        if approver_id and approver_id.startswith(("U", "W")):
            mentions.append(f"<@{approver_id}>")
        else:
            mentions.append(f"@{approver_name}")
        labels.append(p.get("short_label", p.get("role_title", "Alçada")))

    mentions_str = ", ".join(mentions)
    labels_str = ", ".join(labels)

    thread_msg = (
        f"🔔 *Cobrança Operacional de Pendências (@triagem por <@{requested_by_user}>)*\n"
        f"Atenção {mentions_str}: a solicitação da escola *{escola}* ainda aguarda sua deliberação de *{labels_str}* para liberação de contrato."
    )

    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=thread_msg
        )
    except Exception as e:
        logger.error(f"Erro ao postar cobrança na thread: {e}")

    # Envia lembrete amigável nas DMs dos aprovadores pendentes
    from services.dm_approval_service import USE_MOCK_USERS
    total_dms = 0
    for p in pendentes:
        target_id = p.get("approver_id")
        is_mock = False
        if not (target_id and target_id.startswith(("U", "W"))) and USE_MOCK_USERS:
            target_id = requested_by_user
            is_mock = True

        if target_id:
            try:
                test_badge = f"🧪 *[MODO DE TESTE]* Cobrança para: *@{p.get('approver_name')}*\n" if is_mock else ""
                client.chat_postMessage(
                    channel=target_id,
                    text=f"🔔 Lembrete de Pendência: {escola} ({p.get('short_label')})",
                    blocks=[
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": (
                                    f"🔔 *Lembrete de Pendência de Aprovação*\n{test_badge}"
                                    f"• *Escola:* {escola}\n"
                                    f"• *Sua Alçada:* {p.get('role_title')}\n\n"
                                    f"A equipe de *@triagem* solicitou prioridade na deliberação deste ticket. "
                                    f"Por favor, verifique seu card de aprovação para dar seu parecer."
                                )
                            }
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": f"🔗 <{ticket.get('thread_permalink') or '#'}|Acessar thread do canal de negociação>"
                                }
                            ]
                        }
                    ]
                )
                total_dms += 1
            except Exception as e:
                logger.warning(f"Erro ao enviar DM de cobrança: {e}")

    return {
        "success": True,
        "total_pendentes": len(pendentes),
        "message": f"✅ Cobrança disparada com sucesso na thread e via DM para {len(pendentes)} alçada(s) pendente(s)!"
    }
