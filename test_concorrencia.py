import os
import tempfile
import threading

import services.ticket_service as ts
from services.ticket_service import create_ticket, approve_step, reject_step, load_tickets, atualizar_campos_alcada
from utils.links import link_do_google_drive

with tempfile.TemporaryDirectory() as tmp:
    ts.TICKETS_FILE = os.path.join(tmp, "tickets_state.json")
    alcadas = [{"key": f"a{i}", "role_title": f"A{i}", "short_label": f"A{i}",
                "approver_id": f"U{i}", "approver_name": f"P{i}"} for i in range(8)]
    t = create_ticket(channel_id="C1", thread_ts="1.1", escola="Escola",
                      consultor_id="UC", consultor_name="C", details_text="x", approvals_list=alcadas)

    # Aprovações simultâneas de alçadas diferentes não se apagam
    threads = [threading.Thread(target=approve_step, args=(t["key"], f"a{i}", f"U{i}", f"P{i}")) for i in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    salvo = load_tickets()[t["key"]]
    assert all(a["status"] == "approved" for a in salvo["approvals"].values())
    assert salvo["status"] == "completed"

    # Reprovação enviada depois de a alçada já ter sido aprovada não desfaz a aprovação
    res = reject_step(t["key"], "a0", "U0", "P0", "outros", "c. Outros")
    assert res["already_decided"]
    assert load_tickets()[t["key"]]["approvals"]["a0"]["status"] == "approved"

    # Atualizar campos de DM não sobrescreve o resto do ticket
    atualizar_campos_alcada(t["key"], "a1", {"dm_msg_ts": "9.9"})
    salvo = load_tickets()[t["key"]]
    assert salvo["approvals"]["a1"]["dm_msg_ts"] == "9.9" and salvo["status"] == "completed"

assert link_do_google_drive("https://docs.google.com/spreadsheets/d/abc/edit")
assert link_do_google_drive("https://drive.google.com/file/d/abc/view")
assert not link_do_google_drive("http://docs.google.com/x")
assert not link_do_google_drive("https://evil.com/docs.google.com")
assert not link_do_google_drive("https://docs.google.com.evil.com/x")
assert not link_do_google_drive("https://docs.google.com/x|Clique aqui")
print("SUCCESS: concorrência, reprovação atrasada e link do simulador validados!")
