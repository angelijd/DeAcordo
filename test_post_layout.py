import os
import tempfile

import services.ticket_service as ts
from services.ticket_service import (
    create_ticket, approve_step, reject_step, build_thread_blocks, build_decidir_modal, rotulo_checklist,
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
    assert "*0 de 2 aprovadas* · faltam <@U_LIDER> e @Rafael Bae" in txt
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

    # Depois de aprovar e reprovar a exceção: concluída com aprovação parcial, sem botões
    approve_step(t["key"], "comercial", "U_LIDER", "lider")
    res = reject_step(t["key"], "excecao_1_ops", "U_BAE", "bae", "outros", "c. Outros", "não")
    blocks = build_thread_blocks(res["ticket"])
    assert blocks[0]["text"]["text"].startswith("🟡 ")
    assert "Concluída com aprovação parcial" in textos(blocks)
    assert action_ids(blocks) == []

    # Post antigo (sem o layout novo) continua renderizando
    legado = dict(res["ticket"], extra_data={"post_view": {"titulo": "T", "subtitulo": "S", "campos": [("A", "1")]}})
    assert build_thread_blocks(legado)[0]["text"]["text"] == "T"

print("test_post_layout OK")
