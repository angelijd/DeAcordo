import os
import tempfile

import services.ticket_service as ts
from services.ticket_service import (
    create_ticket, approve_step, reject_step, build_thread_blocks, build_decidir_modal, rotulo_checklist,
    build_main_post_blocks, update_ticket_card_ts, get_ticket,
)


def autorizado(apprv, user_id):
    return (user_id == apprv.get("approver_id"), False)


def textos(blocks):
    out = []
    for b in blocks:
        if b["type"] in ("header", "section"):
            out.append(b["text"]["text"])
        elif b["type"] == "context":
            out.extend(e["text"] for e in b["elements"])
    return "\n".join(out)


def action_ids(blocks):
    return [e["action_id"] for b in blocks if b["type"] == "actions" for e in b["elements"]]


assert rotulo_checklist("excecao_1_ops", "Exceção 1 (Ops)", {"1": "Kit Professor"}, {}) == "Exceção 1 (Operações) · Kit Professor"
assert rotulo_checklist("aprovador_n3_2", "N3 Julia", {}, {"aprovador_n3_2": "SAE"}) == "N3 SAE"
assert rotulo_checklist("comercial", "Comercial", {}, {}) == "Comercial (Líder)"

with tempfile.TemporaryDirectory() as tmp:
    ts.TICKETS_FILE = os.path.join(tmp, "tickets_state.json")
    post_view = {
        "fluxo": "Renovação", "escola": "SEIS PRE-VESTIBULAR LTDA",
        "resumo": "💵 *R$ 10.000,00*  ·  SAS, SAE", "pessoas": "👤 <@U_CONSULTOR>",
        "extras": [], "excecoes_sem_alcada": ["⚠️ Exceção 2 · X · sem aprovador definido na regra"],
    }
    t = create_ticket(
        channel_id="C1", thread_ts="1.1", escola="SEIS PRE-VESTIBULAR LTDA",
        consultor_id="U_CONSULTOR", consultor_name="Consultor", details_text="texto",
        approvals_list=[
            {"key": "comercial", "role_title": "Comercial", "short_label": "Comercial",
             "approver_id": "U_LIDER", "approver_name": "Líder Direto", "checklist_label": "Comercial (Líder)"},
            {"key": "excecao_1_ops", "role_title": "Exceção 1", "short_label": "Exceção 1 (Ops)",
             "approver_id": "", "approver_name": "Rafael Bae (@triagem--contratos psc)", "parcial": True,
             "checklist_label": "Exceção 1 (Operações) · Kit Professor"},
        ],
        extra_data={"post_view": post_view},
    )

    # Opção A (padrão): status no topo, checklist e um botão só
    os.environ.pop("POST_BOTOES", None)
    blocks = build_thread_blocks(t)
    txt = textos(blocks)
    assert blocks[0]["text"]["text"] == "⏳ Renovação · SEIS PRE-VESTIBULAR LTDA"
    assert "aprovadas" not in txt and "faltam" not in txt
    assert "⏳ Exceção 1 (Operações) · Kit Professor · @Rafael Bae" in txt
    assert "⚠️ Exceção 2 · X" in txt
    assert action_ids(blocks) == ["btn_decidir_minhas", "triagem_menu"]

    # Opção B: bloco de aprovações no formato anterior
    os.environ["POST_BOTOES"] = "por_alcada"
    blocks_b = build_thread_blocks(t)
    assert "📋 Status das Aprovações do Ticket" in textos(blocks_b)
    assert action_ids(blocks_b) == [
        "btn_aprovar_comercial", "btn_reprovar_comercial",
        "btn_aprovar_excecao_1_ops", "btn_reprovar_excecao_1_ops",
        "btn_triagem_substituicao", "btn_triagem_cobrar_ticket",
    ]
    os.environ.pop("POST_BOTOES")

    # Janela "Minhas aprovações" mostra só as alçadas de quem clicou
    modal = build_decidir_modal(t, "U_LIDER", autorizado)
    assert "Comercial (Líder)" in textos(modal["blocks"])
    assert "Kit Professor" not in textos(modal["blocks"])

    # Card na thread: o canal mostra só tipo, escola, CNPJ e status, sem botões
    update_ticket_card_ts(t["key"], "1.2")
    t = get_ticket(t["key"])
    t["extra_data"]["post_view"]["cnpj"] = "17407203000108"
    canal = build_main_post_blocks(t)
    assert textos(canal) == "🔄 *Renovação · SEIS PRE-VESTIBULAR LTDA*\nCNPJ 17.407.203/0001-08  ·  *⏳ Pendente*"
    assert action_ids(canal) == []
    assert build_thread_blocks(t)[0]["type"] != "header"
    assert "btn_decidir_minhas" in action_ids(build_thread_blocks(t))

    # Depois de aprovar e reprovar a exceção: concluída com aprovação parcial, sem botões
    approve_step(t["key"], "comercial", "U_LIDER", "lider")
    res = reject_step(t["key"], "excecao_1_ops", "U_BAE", "bae", "outros", "c. Outros", "não")
    blocks = build_thread_blocks(res["ticket"])
    assert action_ids(blocks) == []
    # No canal, 1 ou mais reprovações = Reprovado, mesmo com aprovações
    assert "❌ Reprovado" in textos(build_main_post_blocks(res["ticket"]))

    # Post antigo (sem o layout novo) continua renderizando
    legado = dict(res["ticket"], extra_data={"post_view": {"titulo": "T", "subtitulo": "S", "campos": [("A", "1")]}})
    assert build_thread_blocks(legado)[0]["text"]["text"] == "T"

print("test_post_layout OK")
