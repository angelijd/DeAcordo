import os
import tempfile
from services.ticket_service import (
    create_ticket,
    approve_step,
    to_tabular_record,
    to_tabular_approval_records,
    to_tabular_exception_records,
    export_to_csv,
    TICKET_ROW_FIELDS,
    APPROVAL_ROW_FIELDS,
    EXCEPTION_ROW_FIELDS,
)

# Usa um tickets_state.json isolado em pasta temporária para não tocar dado real
import services.ticket_service as ts_module

with tempfile.TemporaryDirectory() as tmp:
    ts_module.TICKETS_FILE = os.path.join(tmp, "tickets_state.json")

    ticket = create_ticket(
        channel_id="C123",
        thread_ts="111.222",
        escola="Escola Teste",
        consultor_id="U_CONSULTOR",
        consultor_name="Consultor Teste",
        details_text="> texto da solicitação",
        thread_permalink="https://arco.slack.com/archives/C123/p111222",
        approvals_list=[
            {
                "key": "comercial",
                "role_title": "👤 APROVAÇÃO COMERCIAL",
                "short_label": "Comercial",
                "approver_id": "U_LIDER",
                "approver_name": "Líder Teste",
            },
            {
                "key": "inviabilidade_core",
                "role_title": "🚨 APROVAÇÃO INVIABILIDADE (Core)",
                "short_label": "Inviabilidade Core",
                "approver_id": "",
                "approver_name": "Diana Sarah Proenca De Oliveira",
            },
        ],
        extra_data={
            "acv": "R$ 100.000,00", "marcas": "SAS", "cnpj": "00000000000191", "frente": "(CE) Inbound",
            "contexto_geral": "Negociação em andamento com a rede.",
            "mais_excecoes": False,
            "excecoes": [{
                "numero": 1,
                "nome": "Exclusividade de fornecimento - Escola",
                "contexto": "Escola pediu exclusividade por 2 anos.",
                "aprovador_comercial": "@lider_teste (Líder Direto)",
                "aprovador_operacoes": "-",
            }],
        },
    )

    row = to_tabular_record(ticket)
    assert set(row.keys()) == set(TICKET_ROW_FIELDS), "faltou campo no schema de tickets"
    assert row["escola"] == "Escola Teste"
    assert row["frente"] == "(CE) Inbound"
    assert row["thread_permalink"] == "https://arco.slack.com/archives/C123/p111222"
    assert row["contexto_geral"] == "Negociação em andamento com a rede."

    approval_rows = to_tabular_approval_records(ticket)
    assert len(approval_rows) == 2
    assert set(approval_rows[0].keys()) == set(APPROVAL_ROW_FIELDS), "faltou campo no schema de approvals"
    assert {r["approval_key"] for r in approval_rows} == {"comercial", "inviabilidade_core"}
    assert approval_rows[0]["sla_due_at"]  # SLA calculado na criação

    # Exceção aciona só a alçada Comercial -> status deve seguir o status dela
    exception_rows = to_tabular_exception_records(ticket)
    assert len(exception_rows) == 1
    assert set(exception_rows[0].keys()) == set(EXCEPTION_ROW_FIELDS), "faltou campo no schema de exceções"
    assert exception_rows[0]["status"] == "pending"

    approve_step(ticket["key"], "comercial", "U_LIDER", "Líder Teste")
    ticket = ts_module.get_ticket(ticket["key"])
    exception_rows = to_tabular_exception_records(ticket)
    assert exception_rows[0]["status"] == "approved", "exceção só depende da alçada Comercial, que foi aprovada"

    paths = export_to_csv(os.path.join(tmp, "export"))
    assert os.path.exists(paths["tickets_csv"])
    assert os.path.exists(paths["approvals_csv"])
    assert os.path.exists(paths["exceptions_csv"])

print("SUCCESS: exportação tabular (CSV) validada com sucesso!")
