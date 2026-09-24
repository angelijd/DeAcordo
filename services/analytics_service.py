"""
Camada de exportação de dados para análise (planilha/BigQuery).

Hoje grava localmente em formato normalizado (uma linha por evento de alçada).
Quando o acesso ao BigQuery for aprovado, basta preencher as credenciais via
variáveis de ambiente (BIGQUERY_PROJECT, BIGQUERY_DATASET, BIGQUERY_TABLE) que
os mesmos eventos passam a ser gravados lá também, sem alterar os pontos de
chamada em ticket_service.py.
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("analytics_service")

ANALYTICS_FILE = os.path.join(os.path.dirname(__file__), "..", "analytics_events.jsonl")

BIGQUERY_PROJECT = os.environ.get("BIGQUERY_PROJECT")
BIGQUERY_DATASET = os.environ.get("BIGQUERY_DATASET")
BIGQUERY_TABLE = os.environ.get("BIGQUERY_TABLE")
BIGQUERY_ENABLED = bool(BIGQUERY_PROJECT and BIGQUERY_DATASET and BIGQUERY_TABLE)

_bq_client = None


def _get_bq_client():
    """Cria (uma vez) o client do BigQuery, se as credenciais estiverem configuradas."""
    global _bq_client
    if _bq_client is not None:
        return _bq_client
    try:
        from google.cloud import bigquery
        _bq_client = bigquery.Client(project=BIGQUERY_PROJECT)
    except Exception as e:
        logger.warning(f"BigQuery configurado mas indisponível ({e}). Eventos seguem só no arquivo local.")
        _bq_client = False
    return _bq_client


def _write_local(record: Dict[str, Any]):
    try:
        with open(ANALYTICS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"Erro ao gravar evento de analytics localmente: {e}")


def _write_bigquery(record: Dict[str, Any]):
    if not BIGQUERY_ENABLED:
        return
    client = _get_bq_client()
    if not client:
        return
    table_id = f"{BIGQUERY_PROJECT}.{BIGQUERY_DATASET}.{BIGQUERY_TABLE}"
    try:
        errors = client.insert_rows_json(table_id, [record])
        if errors:
            logger.error(f"Erro ao inserir evento no BigQuery: {errors}")
    except Exception as e:
        logger.error(f"Erro ao enviar evento para o BigQuery: {e}")


def _emit(record: Dict[str, Any]):
    _write_local(record)
    _write_bigquery(record)


def _base_ticket_fields(ticket: Dict[str, Any]) -> Dict[str, Any]:
    extra = ticket.get("extra_data") or {}
    return {
        "ticket_id": ticket.get("key"),
        "escola": ticket.get("escola"),
        "rede": extra.get("rede"),
        "nome_rede": extra.get("nome_rede"),
        "cnpj": ticket.get("cnpj"),
        "consultor_id": ticket.get("consultor_id"),
        "consultor_name": ticket.get("consultor_name"),
        "acv": ticket.get("acv"),
        "marcas": ticket.get("marcas"),
        "inep": ticket.get("inep"),
        "thread_permalink": ticket.get("thread_permalink"),
        "ticket_status": ticket.get("status"),
        "created_at": ticket.get("created_at"),
        "completed_at": ticket.get("completed_at"),
    }


def emit_ticket_created(ticket: Dict[str, Any]):
    """Emite um evento por ticket criado, e um evento por alçada/exceção associada."""
    base = _base_ticket_fields(ticket)
    _emit({
        **base,
        "event_type": "ticket_created",
        "event_at": datetime.now().isoformat(),
    })
    for approval in (ticket.get("approvals") or {}).values():
        _emit({
            **base,
            "event_type": "alcada_criada",
            "event_at": datetime.now().isoformat(),
            "approval_key": approval.get("key"),
            "role_title": approval.get("role_title"),
            "exception_context": approval.get("scope_reason"),
            "approver_id": approval.get("approver_id"),
            "approver_name": approval.get("approver_name"),
            "approval_status": approval.get("status"),
            "sla_due_at": approval.get("sla_due_at"),
        })


def emit_approval_event(ticket: Dict[str, Any], approval: Dict[str, Any], event_type: str):
    """Emite um evento de mudança de estado de uma alçada (aprovada/reprovada/substituída)."""
    base = _base_ticket_fields(ticket)
    _emit({
        **base,
        "event_type": event_type,
        "event_at": datetime.now().isoformat(),
        "approval_key": approval.get("key"),
        "role_title": approval.get("role_title"),
        "exception_context": approval.get("scope_reason"),
        "approver_id": approval.get("approver_id"),
        "approver_name": approval.get("approver_name"),
        "approval_status": approval.get("status"),
        "approved_by_id": approval.get("approved_by_id"),
        "approved_by_name": approval.get("approved_by_name"),
        "rejected_by_id": approval.get("rejected_by_id"),
        "rejected_by_name": approval.get("rejected_by_name"),
        "reason_key": approval.get("reason_key"),
        "reason_label": approval.get("reason_label"),
    })


def emit_ticket_completed(ticket: Dict[str, Any]):
    """Emite o evento de fechamento do ticket (aprovado ou reprovado ao final)."""
    base = _base_ticket_fields(ticket)
    _emit({
        **base,
        "event_type": "ticket_completed",
        "event_at": datetime.now().isoformat(),
        "rejection_reason_key": ticket.get("rejection_reason_key"),
        "rejection_reason_label": ticket.get("rejection_reason_label"),
    })
