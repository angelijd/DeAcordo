import os
import re
import csv
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional

from config.triagem_config import USE_MOCK_USERS

logger = logging.getLogger("ticket_service")

# DATA_DIR permite apontar os arquivos de estado para um disco persistente
# (ex.: um Volume no Railway) em vez da pasta do projeto, que normalmente é
# apagada a cada novo deploy. Sem DATA_DIR configurado, mantém o comportamento
# de sempre (arquivo na raiz do projeto).
DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(os.path.dirname(__file__), "..")
TICKETS_FILE = os.path.join(DATA_DIR, "tickets_state.json")

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


def _sla_cumprido_em(approval: Dict[str, Any], decidido_em: datetime) -> Optional[bool]:
    """
    Compara o momento da decisão (aprovação/reprovação) com o prazo de SLA da
    alçada. Calculado no momento da decisão porque approved_at/rejected_at são
    guardados só como texto de exibição (sem ano/fuso), não comparáveis depois.
    Retorna None se a alçada não tinha sla_due_at (ex.: criada antes dessa
    funcionalidade existir).
    """
    due_str = approval.get("sla_due_at")
    if not due_str:
        return None
    try:
        due = datetime.fromisoformat(due_str)
    except ValueError:
        return None
    return decidido_em <= due


def _nominal_approver_name(approval: Dict[str, Any]) -> str:
    """
    Nome do titular nominal da alçada (quem a governança designou), mesmo que
    um substituto tenha sido quem efetivamente decidiu.
    """
    if approval.get("is_substituted") and approval.get("original_approver_name"):
        return approval["original_approver_name"]
    return approval.get("approver_name") or "Aprovador"


def _dentro_da_janela_de_cobranca() -> bool:
    """Só permite disparo de cobrança entre 08h e 17h (inclusive) no horário de Brasília."""
    hora_atual = datetime.now(BR_TZ).hour
    return 8 <= hora_atual <= 17

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
        os.makedirs(os.path.dirname(TICKETS_FILE) or ".", exist_ok=True)
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
            "approver_ids": [] if is_sub else (apprv.get("approver_ids") or []),
            "approver_name": eff_name,
            "scope_reason": apprv.get("scope_reason") or "Aprovação necessária conforme governança do ciclo comercial.",
            "checklist_label": apprv.get("checklist_label") or "",
            # parcial=True: reprovar esta alçada (uma exceção) não encerra o pedido
            "parcial": bool(apprv.get("parcial")),
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
        "ano": datetime.now(BR_TZ).year,
        "is_test": USE_MOCK_USERS,
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
    _sync_sheet(ticket_key)
    return ticket


def _sync_sheet(ticket_key: str) -> None:
    """Espelha o ticket na planilha do Google, se configurada. Nunca levanta erro."""
    try:
        from services.sheets_service import sincronizar_ticket
        sincronizar_ticket(ticket_key)
    except Exception as e:
        logger.warning(f"Planilha não sincronizada para {ticket_key}: {e}")


def get_ticket(ticket_key: str) -> Optional[Dict[str, Any]]:
    tickets = load_tickets()
    return tickets.get(ticket_key)


def update_ticket_card_ts(ticket_key: str, card_msg_ts: str):
    tickets = load_tickets()
    if ticket_key in tickets:
        tickets[ticket_key]["card_msg_ts"] = card_msg_ts
        save_tickets(tickets)


def _concluir_se_todas_decididas(ticket: Dict[str, Any], now_str: str) -> bool:
    """
    Conclui o ticket quando todas as alçadas decidiram. Nenhuma reprovação encerra o pedido antes
    disso: as demais alçadas seguem para o consultor receber todos os ajustes de uma vez.
    - Alguma alçada obrigatória reprovada -> ticket "rejected" (precisa de ajustes e novo formulário).
    - Só exceções reprovadas -> "completed" com aprovação parcial.
    """
    approvals = list(ticket["approvals"].values())
    if any(a["status"] == "pending" for a in approvals):
        return False

    ticket["completed_at"] = now_str
    obrigatorias_reprovadas = [a for a in approvals if a["status"] == "rejected" and not a.get("parcial")]
    if obrigatorias_reprovadas:
        primeira = obrigatorias_reprovadas[0]
        ticket["status"] = "rejected"
        ticket["resultado"] = "reprovado"
        ticket["rejection_reason_key"] = primeira.get("reason_key")
        ticket["rejection_reason_label"] = primeira.get("reason_label")
        ticket["rejection_details"] = primeira.get("details")
        ticket["rejected_by_id"] = primeira.get("rejected_by_id")
        ticket["rejected_by_name"] = primeira.get("rejected_by_name")
        ticket["rejected_role"] = primeira.get("role_title", "Alçada")
    else:
        ticket["status"] = "completed"
        ticket["resultado"] = "parcial" if any(a["status"] == "rejected" for a in approvals) else "total"
    return True


def reprovacoes(ticket: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Todas as alçadas reprovadas (exceções e obrigatórias), na ordem do pedido."""
    return [a for a in ticket.get("approvals", {}).values() if a.get("status") == "rejected"]


def reacao_conclusao(ticket: Dict[str, Any]) -> str:
    return "x" if ticket.get("status") == "rejected" else "white_check_mark"


def excecoes_reprovadas(ticket: Dict[str, Any]) -> List[str]:
    return [
        a.get("short_label") or a.get("role_title", "Exceção")
        for a in ticket.get("approvals", {}).values()
        if a.get("parcial") and a.get("status") == "rejected"
    ]


def _linha_reprovacao(a: Dict[str, Any]) -> str:
    rotulo = a.get("checklist_label") or a.get("short_label") or a.get("role_title", "Alçada")
    quem = f"<@{a['rejected_by_id']}>" if str(a.get("rejected_by_id") or "").startswith(("U", "W")) else f"@{a.get('rejected_by_name') or 'Aprovador'}"
    detalhe = f": _{a['details']}_" if a.get("details") else ""
    return f"• *{rotulo}* ({quem}) · {a.get('reason_label') or 'Reprovado'}{detalhe}"


def mensagem_conclusao(ticket: Dict[str, Any]) -> str:
    if ticket.get("status") == "rejected":
        linhas = "\n".join(_linha_reprovacao(a) for a in reprovacoes(ticket))
        return (
            "❌ *SOLICITAÇÃO REPROVADA.* Todos os decisores deliberaram. Ajustes pedidos:\n"
            f"{linhas}\n"
            "O consultor ajusta a proposta e envia um novo formulário."
        )
    reprovadas = excecoes_reprovadas(ticket)
    if reprovadas:
        return (
            "✅ *SOLICITAÇÃO CONCLUÍDA COM APROVAÇÃO PARCIAL.* Todos os decisores deliberaram. "
            f"Fora do contrato (exceções reprovadas): {', '.join(reprovadas)}. "
            "O restante está liberado para emissão de contrato."
        )
    return (
        "🎉 *SOLICITAÇÃO 100% APROVADA E CONCLUÍDA!* Todos os decisores de alçada deliberaram. "
        "Ticket formalmente encerrado e liberado para emissão de contrato."
    )


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

    if approval["status"] in ("approved", "rejected"):
        return {"success": True, "already_approved": True, "ticket": ticket}

    agora_br = datetime.now(BR_TZ)
    now_str = agora_br.strftime("%d/%m às %Hh%M")
    approval["status"] = "approved"
    approval["approved_by_id"] = user_id
    approval["approved_by_name"] = user_name
    approval["approved_at"] = now_str
    approval["sla_cumprido"] = _sla_cumprido_em(approval, agora_br)

    all_completed = _concluir_se_todas_decididas(ticket, now_str)

    tickets[ticket_key] = ticket
    save_tickets(tickets)
    _sync_sheet(ticket_key)

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
    Registra a reprovação de uma alçada. O ticket só fecha quando todas as alçadas decidirem.
    """
    tickets = load_tickets()
    ticket = tickets.get(ticket_key)
    if not ticket:
        return {"success": False, "error": "Ticket não encontrado."}

    approval = ticket["approvals"].get(approval_key)
    if not approval:
        return {"success": False, "error": "Alçada não encontrada."}

    agora_br = datetime.now(BR_TZ)
    now_str = agora_br.strftime("%d/%m às %Hh%M")
    approval["status"] = "rejected"
    approval["sla_cumprido"] = _sla_cumprido_em(approval, agora_br)
    approval["rejected_by_id"] = user_id
    approval["rejected_by_name"] = user_name
    approval["rejected_at"] = now_str
    approval["reason_key"] = reason_key
    approval["reason_label"] = reason_label
    approval["details"] = details

    # Nenhuma reprovação encerra o pedido na hora: as demais alçadas seguem decidindo
    all_completed = _concluir_se_todas_decididas(ticket, now_str)
    tickets[ticket_key] = ticket
    save_tickets(tickets)
    _sync_sheet(ticket_key)
    return {
        "success": True,
        "parcial": bool(approval.get("parcial")),
        "all_completed": all_completed,
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
    approval["approver_ids"] = []
    approval["approver_name"] = new_approver_name
    approval["sla_due_at"] = _compute_sla_due_at(new_approver_name)
    approval["is_substituted"] = True
    approval["original_approver_name"] = original_name
    approval["original_approver_id"] = original_id
    approval["substitute_until"] = until_date
    approval["substitution_reason"] = reason
    approval["substituted_by"] = triagem_user_id
    approval["substituted_at"] = datetime.now().strftime("%d/%m às %Hh%M")

    tickets[ticket_key] = ticket
    save_tickets(tickets)
    _sync_sheet(ticket_key)

    return {
        "success": True,
        "ticket": ticket,
        "approval": approval,
        "original_approver_name": original_name,
        "original_approver_id": original_id,
    }


def _mencao_aprovador(apprv: Dict[str, Any]) -> str:
    """Menção clicável quando há Slack ID real; senão o nome em texto."""
    approver_id = apprv.get("approver_id") or ""
    if approver_id.startswith(("U", "W")):
        return f"<@{approver_id}>"
    return f"@{apprv.get('approver_name') or 'Aprovador'}"



# =========================================================================
# POST NO CANAL (layout escaneável: status no topo + checklist de alçadas)
# =========================================================================

def modo_botoes_post() -> str:
    """
    POST_BOTOES no .env:
    - "unico" (padrão): um botão "Decidir minhas aprovações" abre uma janela só com as alçadas de quem clicou.
    - "por_alcada": bloco de aprovações no formato anterior, com Aprovar e Reprovar em cada alçada.
    """
    valor = (os.environ.get("POST_BOTOES") or "unico").strip().lower()
    return "por_alcada" if valor in ("por_alcada", "b") else "unico"


def rotulo_checklist(key: str, short_label: str, nomes_excecoes: Dict[str, str], marcas_n3: Dict[str, str]) -> str:
    """Rótulo curto de cada alçada na checklist do post (ex.: "Exceção 1 (Operações) · Kit Professor")."""
    partes = key.split("_")
    if key == "comercial":
        return "Comercial (Líder)"
    if key == "aprovador_simulador":
        return "Simulador"
    if key.startswith("aprovador_n3_"):
        marcas = marcas_n3.get(key)
        return f"N3 {marcas}" if marcas else "N3"
    if key.startswith("excecao_") and len(partes) >= 3:
        numero = partes[1]
        nome = (nomes_excecoes.get(numero) or "")[:70]
        if partes[2] == "ops":
            papel = " (Operações)"
        elif partes[2] == "n3":
            papel = " (N3)"
        elif "Diretoria" in (short_label or ""):
            papel = " (Diretoria)"
        else:
            papel = ""
        return f"Exceção {numero}{papel}" + (f" · {nome}" if nome else "")
    return short_label or key


def _mencao_id(user_id: Optional[str]) -> str:
    return f"<@{user_id}>" if user_id and str(user_id).startswith(("U", "W")) else ""


def _quem_pendente(apprv: Dict[str, Any]) -> str:
    """Menção do aprovador sem o sufixo de equipe (ex.: "@Rafael Bae (@triagem--contratos psc)" -> "@Rafael Bae")."""
    return re.sub(r"\s*\(@[^)]*\)", "", _mencao_aprovador(apprv))


def _juntar_nomes(nomes: List[str]) -> str:
    if len(nomes) <= 1:
        return "".join(nomes)
    return ", ".join(nomes[:-1]) + " e " + nomes[-1]


def _emoji_status_ticket(ticket: Dict[str, Any]) -> str:
    status = ticket.get("status")
    if status == "rejected":
        return "❌"
    if status == "completed":
        return "🟡" if excecoes_reprovadas(ticket) else "✅"
    return "⏳"


def _linha_status(ticket: Dict[str, Any]) -> str:
    approvals = list(ticket.get("approvals", {}).values())
    status = ticket.get("status")

    if status == "rejected":
        linhas = "\n".join(_linha_reprovacao(a) for a in reprovacoes(ticket))
        return f"*Reprovada* · ajustes pedidos:\n{linhas}\nPara seguir, o consultor ajusta a proposta e envia um novo formulário."

    if status == "completed":
        reprovadas = excecoes_reprovadas(ticket)
        if reprovadas:
            return f"*Concluída com aprovação parcial* · fora do contrato: {', '.join(reprovadas)}"
        return "*Concluída* · liberada para emissão de contrato"

    aprovadas = sum(1 for a in approvals if a.get("status") == "approved")
    pendentes = [a for a in approvals if a.get("status") == "pending"]
    faltam = list(dict.fromkeys(_quem_pendente(a) for a in pendentes))
    linha = f"*{aprovadas} de {len(approvals)} aprovadas*"
    if faltam:
        linha += f" · falta{'m' if len(faltam) > 1 else ''} {_juntar_nomes(faltam)}"
    reprovadas = [(a.get("checklist_label") or a.get("short_label") or "Alçada").split(" · ")[0] for a in reprovacoes(ticket)]
    if reprovadas:
        linha += f" · reprovad{'as' if len(reprovadas) > 1 else 'a'}: {', '.join(reprovadas)}"
    return linha


def _linha_alcada(apprv: Dict[str, Any], ticket_reprovado: bool) -> str:
    rotulo = apprv.get("checklist_label") or apprv.get("short_label") or apprv.get("role_title") or "Alçada"
    status = apprv.get("status")
    if status == "approved":
        quem = _mencao_id(apprv.get("approved_by_id")) or f"@{apprv.get('approved_by_name') or apprv.get('approver_name')}"
        quando = f" · _{apprv['approved_at']}_" if apprv.get("approved_at") else ""
        return f"✅ {rotulo} · {quem}{quando}"
    if status == "rejected":
        quem = _mencao_id(apprv.get("rejected_by_id")) or f"@{apprv.get('rejected_by_name') or apprv.get('approver_name')}"
        motivo = f" · _{apprv['reason_label']}_" if apprv.get("reason_label") else ""
        return f"❌ {rotulo} · {quem}{motivo}"
    sub = ""
    if apprv.get("is_substituted"):
        sub = f" _(no lugar de {apprv.get('original_approver_name')} até {apprv.get('substitute_until')})_"
    return f"{'⏹️' if ticket_reprovado else '⏳'} {rotulo} · {_quem_pendente(apprv)}{sub}"


def _secoes_de_linhas(linhas: List[str]) -> List[Dict[str, Any]]:
    """Agrupa linhas em seções de até ~2900 caracteres (limite do Slack é 3000)."""
    blocos, atual = [], ""
    for linha in linhas:
        if atual and len(atual) + len(linha) + 1 > 2900:
            blocos.append({"type": "section", "text": {"type": "mrkdwn", "text": atual}})
            atual = ""
        atual = f"{atual}\n{linha}" if atual else linha
    if atual:
        blocos.append({"type": "section", "text": {"type": "mrkdwn", "text": atual}})
    return blocos


def _menu_triagem(ticket_key: str) -> Dict[str, Any]:
    return {
        "type": "overflow",
        "action_id": "triagem_menu",
        "options": [
            {"text": {"type": "plain_text", "text": "🔄 Substituir aprovador (triagem)", "emoji": True}, "value": f"sub:{ticket_key}"},
            {"text": {"type": "plain_text", "text": "🔔 Cobrar pendências (triagem)", "emoji": True}, "value": f"cob:{ticket_key}"},
        ],
    }


def build_post_blocks(ticket: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Post da solicitação no canal: título com status, resumo numa linha e checklist de alçadas."""
    pv = ticket["extra_data"]["post_view"]
    status = ticket.get("status")
    reprovado = status == "rejected"
    pendente = status not in ("completed", "rejected")
    approvals = ticket.get("approvals", {})

    blocks: List[Dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{_emoji_status_ticket(ticket)} {pv['fluxo']} · {pv['escola']}"[:150], "emoji": True},
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": _linha_status(ticket)[:2900]}},
    ]
    if pv.get("resumo") or pv.get("simulador_url"):
        resumo = {"type": "section", "text": {"type": "mrkdwn", "text": (pv.get("resumo") or " ")[:2900]}}
        if pv.get("simulador_url"):
            resumo["accessory"] = {
                "type": "button",
                "action_id": "btn_abrir_simulador",
                "text": {"type": "plain_text", "text": "📎 Simulador", "emoji": True},
                "url": pv["simulador_url"],
            }
        blocks.append(resumo)
    if pv.get("pessoas"):
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": pv["pessoas"][:2900]}]})
    alertas = list(pv.get("extras") or [])
    if alertas:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "  ·  ".join(alertas)[:2900]}]})

    if modo_botoes_post() == "por_alcada":
        # Opção B: bloco de aprovações no formato anterior (seção + botões por alçada, botões da triagem)
        blocks.extend(build_approval_blocks(ticket))
        blocks.extend(_secoes_de_linhas(list(pv.get("excecoes_sem_alcada") or [])))
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "Contexto, CNPJ e INEP estão na thread."}]})
        return blocks

    blocks.append({"type": "divider"})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "*Aprovações*"}]})

    por_alcada = False
    linhas_soltas: List[str] = []
    for key, apprv in approvals.items():
        linha = _linha_alcada(apprv, reprovado)
        if por_alcada and apprv.get("status") == "pending":
            blocks.extend(_secoes_de_linhas(linhas_soltas))
            linhas_soltas = []
            blocks.append({"type": "section", "block_id": f"approval_section_{key}", "text": {"type": "mrkdwn", "text": linha[:2900]}})
            blocks.append({
                "type": "actions",
                "block_id": f"approval_actions_{key}",
                "elements": [
                    {"type": "button", "action_id": f"btn_aprovar_{key}", "value": f"{ticket['key']}:{key}",
                     "text": {"type": "plain_text", "text": "✅ Aprovar", "emoji": True}, "style": "primary"},
                    {"type": "button", "action_id": f"btn_reprovar_{key}", "value": f"{ticket['key']}:{key}",
                     "text": {"type": "plain_text", "text": "❌ Reprovar", "emoji": True}, "style": "danger"},
                ],
            })
        else:
            linhas_soltas.append(linha)
    linhas_soltas.extend(pv.get("excecoes_sem_alcada") or [])
    blocks.extend(_secoes_de_linhas(linhas_soltas))

    if pendente:
        elementos: List[Dict[str, Any]] = []
        if not por_alcada:
            elementos.append({
                "type": "button",
                "action_id": "btn_decidir_minhas",
                "value": ticket["key"],
                "text": {"type": "plain_text", "text": "Decidir minhas aprovações", "emoji": True},
                "style": "primary",
            })
        elementos.append(_menu_triagem(ticket["key"]))
        blocks.append({"type": "actions", "block_id": "post_actions", "elements": elementos})

    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "Contexto, CNPJ e INEP estão na thread."}]})
    return blocks


def alcadas_do_usuario(ticket: Dict[str, Any], user_id: str, autorizado) -> List[Dict[str, Any]]:
    """Alçadas pendentes que `user_id` pode decidir (autorizado = check_approval_authorization)."""
    if ticket.get("status") in ("completed", "rejected"):
        return []
    minhas = []
    for apprv in ticket.get("approvals", {}).values():
        if apprv.get("status") != "pending":
            continue
        ok, _ = autorizado(apprv, user_id)
        if ok:
            minhas.append(apprv)
    return minhas


def build_decidir_modal(ticket: Dict[str, Any], user_id: str, autorizado) -> Dict[str, Any]:
    """Janela com as alçadas pendentes de quem clicou em "Decidir minhas aprovações"."""
    pv = (ticket.get("extra_data") or {}).get("post_view") or {}
    minhas = alcadas_do_usuario(ticket, user_id, autorizado)
    decididas_agora = [
        a for a in ticket.get("approvals", {}).values()
        if a.get("status") in ("approved", "rejected") and user_id in (a.get("approved_by_id"), a.get("rejected_by_id"))
    ]

    blocks: List[Dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{ticket.get('escola', 'Escola')}*\n{pv.get('resumo', '')}"[:2900]}},
    ]
    if ticket.get("thread_permalink"):
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"🔗 <{ticket['thread_permalink']}|Abrir a thread com o contexto>"}]})
    blocks.append({"type": "divider"})

    for apprv in minhas:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{apprv.get('checklist_label') or apprv.get('short_label')}*\n{apprv.get('scope_reason', '')}"[:2900]},
        })
        blocks.append({
            "type": "actions",
            "elements": [
                {"type": "button", "action_id": "decidir_aprovar", "value": f"{ticket['key']}:{apprv['key']}",
                 "text": {"type": "plain_text", "text": "✅ Aprovar", "emoji": True}, "style": "primary"},
                {"type": "button", "action_id": "decidir_reprovar", "value": f"{ticket['key']}:{apprv['key']}",
                 "text": {"type": "plain_text", "text": "❌ Reprovar", "emoji": True}, "style": "danger"},
            ],
        })
    if decididas_agora:
        blocks.extend(_secoes_de_linhas([_linha_alcada(a, False) for a in decididas_agora]))
    if not minhas:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "Você não tem mais aprovações pendentes nesta solicitação. 🙌"}})

    return {
        "type": "modal",
        "callback_id": "modal_decidir_minhas",
        "private_metadata": ticket["key"],
        "title": {"type": "plain_text", "text": "Minhas aprovações"},
        "close": {"type": "plain_text", "text": "Fechar"},
        "blocks": blocks[:100],
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
        reprov_at = ticket.get("completed_at") or datetime.now().strftime("%d/%m às %Hh%M")
        linhas = "\n".join(_linha_reprovacao(a) for a in reprovacoes(ticket))
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"🚨 *SOLICITAÇÃO REPROVADA ({reprov_at})*\n"
                    f"*Ajustes pedidos:*\n{linhas}\n\n"
                    f"⚠️ *Status:* *Ticket encerrado.* Para dar andamento na negociação, "
                    f"o consultor deve realizar as adequações necessárias e submeter um novo formulário."
                )[:2900]
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
                        "text": f"*{role_title}:* {_mencao_aprovador(apprv)}{substitute_badge}\n*Status:* ⏹️ *Encerrado (Ticket Reprovado)*"
                    }
                })
            else:
                # Alçada pendente com botões de Aprovar e Reprovar
                blocks.append({
                    "type": "section",
                    "block_id": f"approval_section_{key}",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{role_title}:* {_mencao_aprovador(apprv)}{substitute_badge}\n*Status:* ⏳ *Aguardando deliberação*"
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
            "text": {"type": "mrkdwn", "text": mensagem_conclusao(ticket)}
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
    post_view = (ticket.get("extra_data") or {}).get("post_view")
    if post_view and post_view.get("fluxo"):
        return build_post_blocks(ticket)
    if post_view:
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": post_view["titulo"][:150], "emoji": True},
        })
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": post_view["subtitulo"]}],
        })
        campos = post_view.get("campos") or []
        for i in range(0, len(campos), 10):
            blocks.append({
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*{label}*\n{valor or '-'}"[:2000]}
                    for label, valor in campos[i:i + 10]
                ],
            })
        if post_view.get("links"):
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": post_view["links"]}],
            })
        if post_view.get("excecoes"):
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Exceções* (contexto na thread)\n" + "\n".join(post_view["excecoes"])},
            })
        blocks.extend(build_approval_blocks(ticket))
        return blocks

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

        permalink = t.get("thread_permalink")
        link = f"\n🔗 <{permalink}|Abrir a thread da solicitação>" if permalink else ""

        for p in t.get("approvals", {}).values():
            if p["status"] != "pending":
                continue
            if not _is_sla_vencido(p):
                continue

            approver_id = p.get("approver_id")
            approver_name = p.get("approver_name")
            if not (approver_id and approver_id.startswith(("U", "W"))):
                # Cobrança é só por DM: sem ID de Slack não há para quem mandar.
                logger.warning(f"Cobrança de SLA para {approver_name}: sem ID de Slack válido, lembrete não enviado.")
                continue

            msg = (
                f"🔔 *Lembrete (SLA vencido):* Falta a sua análise na *{p['short_label']}* "
                f"para liberar o contrato da *{escola}*!{link}"
            )
            try:
                client.chat_postMessage(channel=approver_id, text=msg, unfurl_links=False, unfurl_media=False)
                total_cobrados += 1
            except Exception as e:
                logger.error(f"Erro ao enviar cobrança por DM para {approver_name}: {e}")

    logger.info(f"Cobrança inteligente concluída: {total_cobrados} lembrete(s) enviado(s).")
    return total_cobrados


def cobrar_pendencias_de_ticket(client, ticket_key: str, requested_by_user: str) -> Dict[str, Any]:
    """
    Dispara cobrança pontual focada nas alçadas pendentes deste ticket específico,
    enviando lembrete só na DM de cada aprovador (a thread não recebe cobrança).
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

    escola = ticket.get("escola", "Escola")

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
                                    f"• *Sua Alçada:* {p.get('short_label') or p.get('role_title')}\n\n"
                                    f"A equipe de *@triagem* solicitou a deliberação deste contrato. "
                                    f"Por favor, verifique seu card de aprovação para dar seu parecer."
                                )
                            }
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": f"🔗 <{ticket.get('thread_permalink') or '#'}|Abrir a thread da solicitação>"
                                }
                            ]
                        }
                    ]
                )
                total_dms += 1
            except Exception as e:
                logger.warning(f"Erro ao enviar DM de cobrança: {e}")

    sem_dm = len(pendentes) - total_dms
    aviso = f" ⚠️ {sem_dm} sem ID de Slack, não cobrada(s)." if sem_dm else ""
    return {
        "success": True,
        "total_pendentes": len(pendentes),
        "message": f"✅ Lembrete enviado por DM para {total_dms} alçada(s) pendente(s).{aviso}"
    }


# =========================================================================
# EXPORTAÇÃO TABULAR (preparo para banco/planilha - ex.: BigQuery, Sheets)
# =========================================================================
# As funções abaixo só achatam o JSON já persistido em linhas de tabela;
# não escrevem em nenhum destino externo. Servem para ter os dados prontos
# no formato tabular antes de decidir onde eles vão ser carregados.

TICKET_ROW_FIELDS = [
    "ticket_key", "tipo_fluxo", "channel_id", "thread_ts", "thread_permalink", "escola", "cnpj", "inep",
    "consultor_id", "consultor_name", "frente", "marcas", "alunado", "acv",
    "rede_grupo", "nome_rede", "cnpjs_rede", "tem_divida_alta", "valor_divida",
    "marcas_com_inviab", "nomes_marcas_inviab", "link_sf", "simulador_link",
    "contexto_geral", "mais_excecoes", "excecao_por_marca",
    # Específicos da Renovação (vazios em tickets de Crescimento)
    "pct_reajuste_liquido", "aprovador_simulador", "aprovador_n3_renovacao",
    "status", "created_at", "completed_at",
    "rejected_by_id", "rejected_by_name", "rejection_reason_label", "rejection_details",
]

APPROVAL_ROW_FIELDS = [
    "ticket_key", "approval_key", "role_title", "short_label", "approver_id",
    "approver_name", "status", "sla_due_at",
    "approved_by_id", "approved_by_name", "approved_at",
    "rejected_by_id", "rejected_by_name", "rejected_at", "reason_key", "reason_label", "details",
    "is_substituted", "original_approver_id", "original_approver_name",
    "substitute_until", "substitution_reason", "substituted_by", "substituted_at",
]

# 1 linha por exceção selecionada no formulário (até 5 por ticket). O status é
# derivado das alçadas que essa exceção aciona (comercial e/ou operações) -
# exceções continuam sendo aprovadas em conjunto por alçada, não uma a uma;
# isso só reflete, pra leitura/relatório, em que pé cada exceção está.
EXCEPTION_ROW_FIELDS = [
    "ticket_key", "numero", "nome", "contexto",
    "aprovador_comercial", "aprovador_operacoes", "status",
]


def to_tabular_record(ticket: Dict[str, Any]) -> Dict[str, Any]:
    """
    Achata um ticket (1 linha) para um schema tabular estável, do jeito que
    qualquer banco relacional ou data warehouse (ex.: BigQuery) espera.
    Não grava em nenhum lugar - só formata o que já está em tickets_state.json.
    """
    extra = ticket.get("extra_data", {}) or {}
    return {
        "ticket_key": ticket.get("key"),
        # Tickets criados antes do suporte a 2 fluxos não têm tipo_fluxo
        # gravado - eram todos do fluxo de Crescimento, o único que existia.
        "tipo_fluxo": extra.get("tipo_fluxo") or "crescimento",
        "channel_id": ticket.get("channel_id"),
        "thread_ts": ticket.get("thread_ts"),
        "thread_permalink": ticket.get("thread_permalink"),
        "escola": ticket.get("escola"),
        "cnpj": extra.get("cnpj") or ticket.get("cnpj"),
        "inep": extra.get("inep") or ticket.get("inep"),
        "consultor_id": ticket.get("consultor_id"),
        "consultor_name": ticket.get("consultor_name"),
        "frente": extra.get("frente"),
        "marcas": extra.get("marcas") or ticket.get("marcas"),
        "alunado": extra.get("alunado"),
        "acv": extra.get("acv") or ticket.get("acv"),
        "rede_grupo": extra.get("rede_grupo"),
        "nome_rede": extra.get("nome_rede"),
        "cnpjs_rede": extra.get("cnpjs_rede"),
        "tem_divida_alta": extra.get("tem_divida_alta", ticket.get("tem_divida_alta", False)),
        "valor_divida": extra.get("valor_divida") or ticket.get("valor_divida"),
        "marcas_com_inviab": extra.get("marcas_com_inviab", ticket.get("marcas_com_inviab", False)),
        "nomes_marcas_inviab": extra.get("nomes_marcas_inviab"),
        "link_sf": extra.get("link_sf"),
        "simulador_link": extra.get("simulador_link"),
        "contexto_geral": extra.get("contexto_geral"),
        "mais_excecoes": extra.get("mais_excecoes", False),
        "excecao_por_marca": _excecao_por_marca(extra),
        "pct_reajuste_liquido": extra.get("pct_reajuste_liquido"),
        "aprovador_simulador": extra.get("aprovador_simulador"),
        "aprovador_n3_renovacao": extra.get("aprovador_n3_renovacao"),
        "status": ticket.get("status"),
        "created_at": ticket.get("created_at"),
        "completed_at": ticket.get("completed_at"),
        "rejected_by_id": ticket.get("rejected_by_id"),
        "rejected_by_name": ticket.get("rejected_by_name"),
        "rejection_reason_label": ticket.get("rejection_reason_label"),
        "rejection_details": ticket.get("rejection_details"),
    }


def _excecao_por_marca(extra: Dict[str, Any]) -> str:
    """
    Detalhe de cada exceção do ticket, repetido para cada marca selecionada
    no formulário (coluna MARCAS). Exceções são aprovadas no nível do ticket,
    não por marca individual, então todas as marcas selecionadas compartilham
    o mesmo conjunto de exceções.
    """
    excecoes = extra.get("excecoes") or []
    if not excecoes:
        return ""

    marcas_str = extra.get("marcas") or ""
    marcas = [m.strip() for m in marcas_str.split(",") if m.strip()]
    if not marcas:
        return ""

    detalhe_excecoes = "; ".join(f"{exc.get('nome')} ({exc.get('contexto')})" for exc in excecoes)
    return " | ".join(f"{marca}: {detalhe_excecoes}" for marca in marcas)


def _excecao_status(excecao: Dict[str, Any], approvals: Dict[str, Any]) -> str:
    """
    Deriva o status de 1 exceção a partir das alçadas que ela aciona.
    Uma exceção pode exigir Comercial, Operações, ambas ou nenhuma (regra "-").
    """
    relevantes = []
    numero = excecao.get("numero")
    # Tickets novos têm uma alçada por exceção (excecao_N_com / excecao_N_ops);
    # os antigos usavam "comercial" e "operacoes" compartilhadas.
    if excecao.get("aprovador_comercial") and excecao["aprovador_comercial"] != "-":
        # excecao_N_com, ou excecao_N_n3_1, _n3_2... quando a regra aponta o N3 de cada marca
        da_excecao = [
            a for k, a in approvals.items()
            if k == f"excecao_{numero}_com" or k.startswith(f"excecao_{numero}_n3_")
        ]
        for apprv in da_excecao or [approvals.get("comercial", {})]:
            relevantes.append(apprv.get("status", "pending"))
    if excecao.get("aprovador_operacoes") and excecao["aprovador_operacoes"] != "-":
        apprv = approvals.get(f"excecao_{numero}_ops") or approvals.get("operacoes", {})
        relevantes.append(apprv.get("status", "pending"))

    if not relevantes:
        return "sem_aprovacao_necessaria"
    if "rejected" in relevantes:
        return "rejected"
    if all(s == "approved" for s in relevantes):
        return "approved"
    return "pending"


def to_tabular_exception_records(ticket: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Achata as exceções selecionadas no formulário (até 5 por ticket) em linhas
    de uma tabela filha, 1 linha por exceção, pronta para join por ticket_key.
    """
    extra = ticket.get("extra_data", {}) or {}
    approvals = ticket.get("approvals", {}) or {}
    rows = []
    for exc in extra.get("excecoes", []):
        rows.append({
            "ticket_key": ticket.get("key"),
            "numero": exc.get("numero"),
            "nome": exc.get("nome"),
            "contexto": exc.get("contexto"),
            "aprovador_comercial": exc.get("aprovador_comercial"),
            "aprovador_operacoes": exc.get("aprovador_operacoes"),
            "status": _excecao_status(exc, approvals),
        })
    return rows


def to_tabular_approval_records(ticket: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Achata as alçadas de um ticket em linhas de uma tabela filha (1 linha por
    alçada), pronta para um join por (ticket_key, approval_key). Inclui o
    percentual de inviabilidade de cada marca (são valores livres do simulador,
    não entram como colunas próprias, ficam no dict inviabilidades_pct do ticket).
    """
    rows = []
    for key, a in ticket.get("approvals", {}).items():
        rows.append({
            "ticket_key": ticket.get("key"),
            "approval_key": key,
            "role_title": a.get("role_title"),
            "short_label": a.get("short_label"),
            "approver_id": a.get("approver_id"),
            "approver_name": a.get("approver_name"),
            "status": a.get("status"),
            "sla_due_at": a.get("sla_due_at"),
            "approved_by_id": a.get("approved_by_id"),
            "approved_by_name": a.get("approved_by_name"),
            "approved_at": a.get("approved_at"),
            "rejected_by_id": a.get("rejected_by_id"),
            "rejected_by_name": a.get("rejected_by_name"),
            "rejected_at": a.get("rejected_at"),
            "reason_key": a.get("reason_key"),
            "reason_label": a.get("reason_label"),
            "details": a.get("details"),
            "is_substituted": a.get("is_substituted", False),
            "original_approver_id": a.get("original_approver_id"),
            "original_approver_name": a.get("original_approver_name"),
            "substitute_until": a.get("substitute_until"),
            "substitution_reason": a.get("substitution_reason"),
            "substituted_by": a.get("substituted_by"),
            "substituted_at": a.get("substituted_at"),
        })
    return rows


def export_to_csv(out_dir: str) -> Dict[str, str]:
    """
    Exporta todos os tickets persistidos para 6 CSVs (3 por tipo de fluxo:
    tickets_crescimento.csv/tickets_renovacao.csv, approvals_*.csv e
    exceptions_*.csv), prontos para carregar em planilhas/tabelas separadas
    por tipo de solicitação (Crescimento e Renovação). O estado em
    tickets_state.json continua único - a separação acontece só aqui, na
    exportação. Retorna os caminhos de todos os arquivos gerados.
    """
    os.makedirs(out_dir, exist_ok=True)
    tickets = load_tickets()

    tickets_por_fluxo: Dict[str, list] = {"crescimento": [], "renovacao": []}
    for ticket in tickets.values():
        tipo = (ticket.get("extra_data", {}) or {}).get("tipo_fluxo") or "crescimento"
        tickets_por_fluxo.setdefault(tipo, []).append(ticket)

    paths: Dict[str, str] = {}
    for tipo, tickets_do_tipo in tickets_por_fluxo.items():
        tickets_path = os.path.join(out_dir, f"tickets_{tipo}.csv")
        approvals_path = os.path.join(out_dir, f"approvals_{tipo}.csv")
        exceptions_path = os.path.join(out_dir, f"exceptions_{tipo}.csv")

        with open(tickets_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=TICKET_ROW_FIELDS)
            writer.writeheader()
            for ticket in tickets_do_tipo:
                writer.writerow(to_tabular_record(ticket))

        with open(approvals_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=APPROVAL_ROW_FIELDS)
            writer.writeheader()
            for ticket in tickets_do_tipo:
                for row in to_tabular_approval_records(ticket):
                    writer.writerow(row)

        with open(exceptions_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=EXCEPTION_ROW_FIELDS)
            writer.writeheader()
            for ticket in tickets_do_tipo:
                for row in to_tabular_exception_records(ticket):
                    writer.writerow(row)

        paths[f"tickets_csv_{tipo}"] = tickets_path
        paths[f"approvals_csv_{tipo}"] = approvals_path
        paths[f"exceptions_csv_{tipo}"] = exceptions_path

    return paths


# =========================================================================
# RETENÇÃO DE FIM DE ANO (produtividade apenas - descarta o resto)
# =========================================================================
# Só rastreia as alçadas Comercial e Operações (decisão: as demais não
# entram por ora). "Aprovador responsável" = titular nominal da alçada,
# mesmo que um substituto tenha decidido de fato. Identificação por nome,
# não por ID. Tickets de teste/mock são excluídos da contagem.

PRODUCTIVITY_ALCADAS = ("comercial", "operacoes")


def _summary_file_path(year: int) -> str:
    """Mesma pasta de TICKETS_FILE, pra testes que redirecionam TICKETS_FILE também isolarem este arquivo."""
    return os.path.join(os.path.dirname(TICKETS_FILE), f"productivity_summary_{year}.json")


def _is_ticket_test(ticket: Dict[str, Any]) -> bool:
    """
    Indica se o ticket foi gerado em modo de teste/mock. Tickets criados
    depois dessa marcação existir já têm is_test salvo; para os anteriores,
    usa como fallback se o consultor não tem um ID real do Slack.
    """
    if "is_test" in ticket:
        return bool(ticket["is_test"])
    consultor_id = ticket.get("consultor_id") or ""
    return not consultor_id.startswith(("U", "W"))


def _ticket_year(ticket: Dict[str, Any]) -> Optional[int]:
    """Ano do ticket: usa o campo 'ano' se existir, senão extrai de created_at."""
    if ticket.get("ano"):
        return ticket["ano"]
    created_at = ticket.get("created_at") or ""
    try:
        return int(created_at.split("/")[-1].split(" ")[0])
    except (ValueError, IndexError):
        return None


def compute_productivity_summary(year: int, exclude_test: bool = True) -> Dict[str, Any]:
    """
    Agrega, para o ano informado, só o necessário para analisar produtividade:
    quantidade de contratos (por consultor) e SLA no prazo/vencido das
    alçadas Comercial e Operações (por titular nominal). Não inclui CNPJ,
    valores, texto livre nem qualquer outro dado comercial sensível.
    Não grava nada - só lê tickets_state.json e devolve o resumo.
    """
    tickets = load_tickets()

    total_contratos = 0
    por_consultor: Dict[str, int] = {}
    sla_por_alcada: Dict[str, Dict[str, Any]] = {
        alcada: {"no_prazo": 0, "vencido": 0, "por_aprovador": {}}
        for alcada in PRODUCTIVITY_ALCADAS
    }

    for ticket in tickets.values():
        if _ticket_year(ticket) != year:
            continue
        if exclude_test and _is_ticket_test(ticket):
            continue

        total_contratos += 1
        consultor = ticket.get("consultor_name") or "Desconhecido"
        por_consultor[consultor] = por_consultor.get(consultor, 0) + 1

        for alcada in PRODUCTIVITY_ALCADAS:
            approval = ticket.get("approvals", {}).get(alcada)
            if not approval or approval.get("status") not in ("approved", "rejected"):
                continue

            cumprido = approval.get("sla_cumprido")
            if cumprido is None:
                continue  # decidida antes de sla_due_at existir - não dá pra saber

            aprovador = _nominal_approver_name(approval)
            bucket = sla_por_alcada[alcada]
            chave = "no_prazo" if cumprido else "vencido"
            bucket[chave] += 1
            por_aprovador = bucket["por_aprovador"].setdefault(aprovador, {"no_prazo": 0, "vencido": 0})
            por_aprovador[chave] += 1

    return {
        "ano": year,
        "gerado_em": datetime.now(BR_TZ).isoformat(),
        "total_contratos": total_contratos,
        "contratos_por_consultor": por_consultor,
        "sla_comercial": sla_por_alcada["comercial"],
        "sla_operacoes": sla_por_alcada["operacoes"],
    }


def purge_tickets_keep_summary(year: int, confirm: bool = False) -> Dict[str, Any]:
    """
    Ação DESTRUTIVA e deliberada de fim de ano: calcula o resumo de
    produtividade do ano, grava em productivity_summary_<year>.json, e
    remove de tickets_state.json os tickets daquele ano já encerrados
    (aprovados ou reprovados) - os ainda pendentes nunca são descartados,
    independente do ano.
    Sem confirm=True só calcula e devolve o resumo, sem tocar em nada.
    """
    summary = compute_productivity_summary(year)

    if not confirm:
        return {
            "executado": False,
            "summary": summary,
            "aviso": "Nada foi descartado. Rode de novo com confirm=True pra efetivar.",
        }

    summary_path = _summary_file_path(year)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    tickets = load_tickets()
    mantidos = {}
    descartados = 0
    for key, ticket in tickets.items():
        if _ticket_year(ticket) == year and ticket.get("status") != "pending":
            descartados += 1
            continue
        mantidos[key] = ticket

    save_tickets(mantidos)
    logger.warning(
        f"Purge de {year}: {descartados} ticket(s) descartado(s) de tickets_state.json, "
        f"resumo de produtividade salvo em {summary_path}."
    )

    return {"executado": True, "summary": summary, "tickets_descartados": descartados, "summary_path": summary_path}
