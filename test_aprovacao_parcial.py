import os
import tempfile

import services.ticket_service as ts
from services.ticket_service import create_ticket, approve_step, reject_step, mensagem_conclusao, reacao_conclusao

with tempfile.TemporaryDirectory() as tmp:
    ts.TICKETS_FILE = os.path.join(tmp, "tickets_state.json")

    def novo_ticket(ts_id):
        return create_ticket(
            channel_id="C1", thread_ts=ts_id, escola="Escola",
            consultor_id="U_CONSULTOR", consultor_name="Consultor",
            details_text="texto",
            approvals_list=[
                {"key": "comercial", "role_title": "Comercial", "short_label": "Comercial",
                 "approver_id": "U_LIDER", "approver_name": "Líder"},
                {"key": "excecao_1_com", "role_title": "Exceção 1", "short_label": "Exceção 1",
                 "approver_id": "", "approver_name": "Rafael Martinez", "parcial": True},
                {"key": "excecao_2_com", "role_title": "Exceção 2", "short_label": "Exceção 2",
                 "approver_id": "", "approver_name": "Rafael Martinez", "parcial": True},
            ],
        )

    # Exceção reprovada não encerra o pedido; o resto segue e conclui como parcial
    t = novo_ticket("1.1")
    res = reject_step(t["key"], "excecao_1_com", "U_R", "Rafael", "outros", "c. Outros", "não")
    assert res["parcial"] and not res["all_completed"]
    assert res["ticket"]["status"] == "pending"
    approve_step(t["key"], "excecao_2_com", "U_R", "Rafael")
    res = approve_step(t["key"], "comercial", "U_LIDER", "Líder")
    assert res["all_completed"]
    assert res["ticket"]["status"] == "completed" and res["ticket"]["resultado"] == "parcial"
    assert "Exceção 1" in mensagem_conclusao(res["ticket"])

    # Exceção já reprovada não pode ser aprovada depois por um botão antigo
    assert approve_step(t["key"], "excecao_1_com", "U_R", "Rafael")["already_approved"]

    # Reprovação de alçada fixa (Líder) NÃO encerra na hora: as demais seguem decidindo,
    # e no fim o pedido fecha como reprovado com todos os ajustes listados
    t = novo_ticket("2.2")
    res = reject_step(t["key"], "comercial", "U_LIDER", "Líder", "outros", "c. Outros", "preço")
    assert not res.get("parcial") and not res["all_completed"]
    assert res["ticket"]["status"] == "pending"
    reject_step(t["key"], "excecao_1_com", "U_R", "Rafael", "outros", "c. Outros", "prazo")
    res = approve_step(t["key"], "excecao_2_com", "U_R", "Rafael")
    assert res["all_completed"] and res["ticket"]["status"] == "rejected"
    assert res["ticket"]["resultado"] == "reprovado"
    msg = mensagem_conclusao(res["ticket"])
    assert "REPROVADA" in msg and "preço" in msg and "prazo" in msg
    assert reacao_conclusao(res["ticket"]) == "x"

    # Tudo aprovado continua sendo 100%
    t = novo_ticket("3.3")
    for k in ("comercial", "excecao_1_com", "excecao_2_com"):
        res = approve_step(t["key"], k, "U", "X")
    assert res["ticket"]["resultado"] == "total"

print("SUCCESS: aprovação parcial por exceção validada!")
