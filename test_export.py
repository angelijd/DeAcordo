import os
import tempfile
from services.ticket_service import (
    create_ticket,
    to_tabular_record,
    to_tabular_approval_records,
    export_to_csv,
    TICKET_ROW_FIELDS,
    APPROVAL_ROW_FIELDS,
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
        approvals_list=[{
            "key": "comercial",
            "role_title": "👤 APROVAÇÃO COMERCIAL",
            "short_label": "Comercial",
            "approver_id": "U_LIDER",
            "approver_name": "Líder Teste",
        }],
        extra_data={"acv": "R$ 100.000,00", "marcas": "SAS", "cnpj": "00000000000191", "frente": "(CE) Inbound"},
    )

    row = to_tabular_record(ticket)
    assert set(row.keys()) == set(TICKET_ROW_FIELDS), "faltou campo no schema de tickets"
    assert row["escola"] == "Escola Teste"
    assert row["frente"] == "(CE) Inbound"

    approval_rows = to_tabular_approval_records(ticket)
    assert len(approval_rows) == 1
    assert set(approval_rows[0].keys()) == set(APPROVAL_ROW_FIELDS), "faltou campo no schema de approvals"
    assert approval_rows[0]["approver_name"] == "Líder Teste"
    assert approval_rows[0]["sla_due_at"]  # SLA calculado na criação

    paths = export_to_csv(os.path.join(tmp, "export"))
    assert os.path.exists(paths["tickets_csv"])
    assert os.path.exists(paths["approvals_csv"])

print("SUCCESS: exportação tabular (CSV) validada com sucesso!")
