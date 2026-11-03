"""
Espelha cada ticket numa planilha do Google Sheets (1 linha por ticket, uma aba por tipo de fluxo).
Desligado por padrão: só ativa com GOOGLE_SHEET_ID e o arquivo de credenciais da conta de serviço.
Qualquer falha é registrada em log e nunca derruba o fluxo de aprovação.
"""

import os
import logging
import threading
from typing import Any, Dict, List, Optional

from services.ticket_service import TICKET_ROW_FIELDS, to_tabular_record, load_tickets

logger = logging.getLogger("sheets_service")

SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "").strip()
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "google_credentials.json").strip()

ABAS_POR_FLUXO = {"crescimento": "Crescimento", "renovacao": "Renovação"}
EXTRA_FIELDS = ["alcadas", "resultado", "modo_teste"]
SHEET_FIELDS = TICKET_ROW_FIELDS + EXTRA_FIELDS

_STATUS_PT = {"pending": "Pendente", "completed": "Concluído", "rejected": "Reprovado"}
_APPROVAL_PT = {"pending": "⏳ pendente", "approved": "✅ aprovado", "rejected": "❌ reprovado"}
_RESULTADO_PT = {"total": "Aprovação total", "parcial": "Aprovação parcial"}

_lock = threading.Lock()
_spreadsheet = None


def is_enabled() -> bool:
    return bool(SHEET_ID) and os.path.exists(CREDENTIALS_FILE)


def _get_spreadsheet():
    global _spreadsheet
    if _spreadsheet is None:
        import gspread  # importado aqui para o bot rodar sem a biblioteca quando a planilha está desligada
        _spreadsheet = gspread.service_account(filename=CREDENTIALS_FILE).open_by_key(SHEET_ID)
    return _spreadsheet


def _resumo_alcadas(ticket: Dict[str, Any]) -> str:
    partes = []
    for a in (ticket.get("approvals") or {}).values():
        label = a.get("short_label") or a.get("role_title") or "Alçada"
        nome = a.get("approved_by_name") or a.get("rejected_by_name") or a.get("approver_name") or ""
        status = _APPROVAL_PT.get(a.get("status"), a.get("status") or "")
        partes.append(f"{label}: {status}" + (f" ({nome})" if nome and a.get("status") != "pending" else ""))
    return "\n".join(partes)


def montar_linha(ticket: Dict[str, Any]) -> List[str]:
    rec = to_tabular_record(ticket)
    rec["status"] = _STATUS_PT.get(rec.get("status"), rec.get("status"))
    rec["alcadas"] = _resumo_alcadas(ticket)
    rec["resultado"] = _RESULTADO_PT.get(ticket.get("resultado"), "")
    rec["modo_teste"] = "Sim" if ticket.get("is_test") else ""
    return ["" if rec.get(f) is None else str(rec.get(f)) for f in SHEET_FIELDS]


def _obter_aba(spreadsheet, nome: str):
    try:
        ws = spreadsheet.worksheet(nome)
    except Exception:
        ws = spreadsheet.add_worksheet(title=nome, rows=1000, cols=len(SHEET_FIELDS))
    if not ws.row_values(1):
        ws.update(values=[SHEET_FIELDS], range_name="A1", raw=True)
        try:
            ws.freeze(rows=1)
        except Exception:
            pass
    return ws


def gravar_ticket(spreadsheet, ticket: Dict[str, Any]) -> None:
    """Insere o ticket na aba do seu fluxo ou atualiza a linha existente (chave: ticket_key)."""
    linha = montar_linha(ticket)
    nome_aba = ABAS_POR_FLUXO.get(to_tabular_record(ticket)["tipo_fluxo"], "Crescimento")
    ws = _obter_aba(spreadsheet, nome_aba)
    chaves = ws.col_values(1)
    if ticket["key"] in chaves:
        idx = chaves.index(ticket["key"]) + 1
        ws.update(values=[linha], range_name=f"A{idx}", raw=True)
    else:
        ws.append_row(linha, value_input_option="RAW")


def _sincronizar(ticket_key: str) -> None:
    with _lock:
        try:
            ticket = load_tickets().get(ticket_key)
            if ticket:
                gravar_ticket(_get_spreadsheet(), ticket)
        except Exception as e:
            logger.warning(f"Falha ao gravar o ticket {ticket_key} na planilha: {type(e).__name__}: {e}")


def sincronizar_ticket(ticket_key: Optional[str]) -> None:
    """Grava o estado mais recente do ticket em segundo plano. Sem efeito se a planilha estiver desligada."""
    if not ticket_key or not is_enabled():
        return
    threading.Thread(target=_sincronizar, args=(ticket_key,), daemon=True).start()
