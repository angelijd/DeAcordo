import os
import tempfile
from datetime import datetime, timedelta

import services.ticket_service as ts
from services.ticket_service import (
    create_ticket,
    approve_step,
    reject_step,
    substitute_approver,
    compute_productivity_summary,
    purge_tickets_keep_summary,
    BR_TZ,
)

with tempfile.TemporaryDirectory() as tmp:
    ts.TICKETS_FILE = os.path.join(tmp, "tickets_state.json")

    year = datetime.now(BR_TZ).year

    # Ticket 1: Comercial aprovado dentro do prazo (24h), por um titular sem substituição
    t1 = create_ticket(
        channel_id="C1", thread_ts="1.1", escola="Escola 1",
        consultor_id="U_CONSULTOR_1", consultor_name="Consultor A",
        details_text="texto",
        approvals_list=[{"key": "comercial", "role_title": "Comercial", "short_label": "Comercial",
                          "approver_id": "U_LIDER_1", "approver_name": "Líder A"}],
    )
    assert t1["is_test"] is False  # USE_MOCK_USERS default é false
    assert t1["ano"] == year
    approve_step(t1["key"], "comercial", "U_LIDER_1", "Líder A")

    # Ticket 2: Comercial vencido (empurra o sla_due_at pro passado antes de decidir)
    t2 = create_ticket(
        channel_id="C2", thread_ts="2.2", escola="Escola 2",
        consultor_id="U_CONSULTOR_2", consultor_name="Consultor B",
        details_text="texto",
        approvals_list=[{"key": "comercial", "role_title": "Comercial", "short_label": "Comercial",
                          "approver_id": "U_LIDER_1", "approver_name": "Líder A"}],
    )
    tickets = ts.load_tickets()
    passado = (datetime.now(BR_TZ) - timedelta(hours=1)).isoformat()
    tickets[t2["key"]]["approvals"]["comercial"]["sla_due_at"] = passado
    ts.save_tickets(tickets)
    reject_step(t2["key"], "comercial", "U_LIDER_1", "Líder A", "negociacao_caiu", "a. Negociação caiu")

    # Ticket 3: Operações, com substituição - titular nominal deve continuar sendo o original
    t3 = create_ticket(
        channel_id="C3", thread_ts="3.3", escola="Escola 3",
        consultor_id="U_CONSULTOR_1", consultor_name="Consultor A",
        details_text="texto",
        approvals_list=[
            {"key": "comercial", "role_title": "Comercial", "short_label": "Comercial",
             "approver_id": "U_LIDER_1", "approver_name": "Líder A"},
            {"key": "operacoes", "role_title": "Operações", "short_label": "Operações",
             "approver_id": "", "approver_name": "Thibaut Frederic Choukroun"},
        ],
    )
    substitute_approver(
        ticket_key=t3["key"], approval_key="operacoes",
        new_approver_id="U_SUBSTITUTO", new_approver_name="Substituto X",
        until_date="2099-12-31", reason="férias", triagem_user_id="U_TRIAGEM",
    )
    approve_step(t3["key"], "operacoes", "U_SUBSTITUTO", "Substituto X")
    approve_step(t3["key"], "comercial", "U_LIDER_1", "Líder A")

    # Ticket 4: deve ser ignorado no resumo por ser de teste (simula USE_MOCK_USERS=true na criação)
    t4 = create_ticket(
        channel_id="C4", thread_ts="4.4", escola="Escola Teste",
        consultor_id="mock_consultor_1", consultor_name="Consultor Mock",
        details_text="texto",
        approvals_list=[{"key": "comercial", "role_title": "Comercial", "short_label": "Comercial",
                          "approver_id": "", "approver_name": "Líder A"}],
    )
    tickets = ts.load_tickets()
    tickets[t4["key"]]["is_test"] = True
    ts.save_tickets(tickets)

    summary = compute_productivity_summary(year)
    assert summary["total_contratos"] == 3, f"esperado 3 contratos reais, veio {summary['total_contratos']}"
    assert "Consultor Mock" not in summary["contratos_por_consultor"], "ticket de teste não deveria entrar"
    assert summary["contratos_por_consultor"]["Consultor A"] == 2
    assert summary["contratos_por_consultor"]["Consultor B"] == 1

    sla_com = summary["sla_comercial"]
    assert sla_com["no_prazo"] == 2, sla_com  # t1 e t3 comercial aprovados dentro do prazo
    assert sla_com["vencido"] == 1, sla_com   # t2 reprovado após o prazo

    sla_ops = summary["sla_operacoes"]
    assert sla_ops["no_prazo"] == 1, sla_ops
    assert "Thibaut Frederic Choukroun" in sla_ops["por_aprovador"], "titular nominal deveria ficar com o crédito, não o substituto"
    assert "Substituto X" not in sla_ops["por_aprovador"]

    # Nenhum dado sensível no resumo
    resumo_str = str(summary)
    assert "Escola" not in resumo_str
    assert "CNPJ" not in resumo_str.upper().replace("CONSULTOR", "")

    # purge sem --confirm não altera nada
    dry = purge_tickets_keep_summary(year, confirm=False)
    assert dry["executado"] is False
    assert len(ts.load_tickets()) == 4

    # purge com confirm descarta encerrados do ano, mantém o resto
    real = purge_tickets_keep_summary(year, confirm=True)
    assert real["executado"] is True
    assert os.path.exists(real["summary_path"])
    restantes = ts.load_tickets()
    assert t1["key"] not in restantes  # encerrado, descartado
    assert t2["key"] not in restantes  # encerrado, descartado
    assert t3["key"] not in restantes  # encerrado, descartado
    assert t4["key"] in restantes      # nunca decidido -> continua pending -> nunca descarta

print("SUCCESS: resumo de produtividade e purge de fim de ano validados!")
