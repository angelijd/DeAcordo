import os
import tempfile

import services.ticket_service as ts
from services.ticket_service import create_ticket, approve_step, reject_step, build_thread_blocks, get_ticket, marcar_sucedida
from services.rodada_service import (
    campos_alterados, excecoes_reprovadas_da_rodada, herdar_aprovacoes, mensagem_nova_rodada,
    ultima_rodada_da_escola, valores_do_ticket, MODO_REENVIO,
)
from views.modals import build_rodada_modal, build_aprovacoes_modal


def action_ids(blocks):
    return [e["action_id"] for b in blocks if b["type"] == "actions" for e in b["elements"]]


FORM = {
    "tipo_fluxo": "crescimento", "frente": "(CE) Inbound", "consultor": "UCONS", "lider": "ULIDER",
    "marcas": ["SAS"], "cnpj": "17.407.203/0001-08", "razao_social": "ESCOLA", "acv": "10000",
    "inviabilidades": {"SAS": "0"}, "contexto_geral": "ctx", "link_sf": "https://a.salesforce.com/x",
    "simulador_link": "https://drive.google.com/x",
}

APROVACOES = [
    {"key": "comercial", "role_title": "Comercial", "short_label": "Comercial", "approver_id": "ULIDER", "approver_name": "Líder"},
    {"key": "excecao_1_com", "role_title": "Exceção 1", "short_label": "Exceção 1", "approver_id": "ULIDER",
     "approver_name": "Líder", "parcial": True},
]

# Diferenças entre rodadas: valor formatado, ordem das marcas não conta
mud = campos_alterados(FORM, dict(FORM, acv="12.000,00", marcas=["SAS"]))
assert [m["rotulo"] for m in mud] == ["Valor do contrato (ACV)"]
assert mud[0]["antes"] == "R$ 10.000,00" and mud[0]["depois"] == "R$ 12.000,00"
assert campos_alterados(FORM, dict(FORM, marcas=["SAS"], excecao_1="X")) == []

with tempfile.TemporaryDirectory() as tmp:
    ts.TICKETS_FILE = os.path.join(tmp, "tickets_state.json")
    extra = {"cnpj": FORM["cnpj"], "form_values": FORM, "post_view": {"fluxo": "Crescimento", "escola": "ESCOLA"},
             "excecoes": [{"numero": 1, "nome": "Desconto", "contexto": "10%"}]}
    r1 = create_ticket("C1", "1.1", "ESCOLA", "UCONS", "Consultor", "t", APROVACOES, extra_data=extra)
    assert r1["key"] == "C1_1.1" and r1["rodada"] == 1
    assert ultima_rodada_da_escola("C1", "17407203000108")["key"] == r1["key"]
    assert ultima_rodada_da_escola("C2", "17407203000108") is None

    approve_step(r1["key"], "comercial", "ULIDER", "lider")
    r1 = reject_step(r1["key"], "excecao_1_com", "ULIDER", "lider", "outros", "c. Outros", "menos")["ticket"]
    r1["card_na_thread"] = True
    assert action_ids(build_thread_blocks(r1)) == ["btn_rodada_nova", "btn_rodada_reenviar"]
    assert excecoes_reprovadas_da_rodada(r1) == [{"nome": "Desconto", "contexto": "10%"}]
    assert valores_do_ticket(r1) == (FORM, True)

    # Rodada 2 sem mudança nos dados gerais: Comercial vem aprovada da rodada 1, só a exceção decide
    lista = [dict(a) for a in APROVACOES]
    herdar_aprovacoes(lista, r1, gerais_mudaram=False)
    r2 = create_ticket("C1", "1.1", "ESCOLA", "UCONS", "Consultor", "t", lista, extra_data=extra,
                       rodada=2, rodada_anterior=r1["key"], modo_rodada=MODO_REENVIO)
    assert r2["key"] == "C1_1.1_r2" and r2["thread_ts"] == "1.1"
    assert r2["approvals"]["comercial"]["status"] == "approved"
    assert r2["approvals"]["comercial"]["herdada"]["rodada"] == 1
    assert r2["approvals"]["excecao_1_com"]["status"] == "pending"
    r2["card_na_thread"] = True
    texto = "\n".join(b["text"]["text"] for b in build_thread_blocks(r2) if b["type"] == "section")
    assert "aprovada na rodada 1" in texto

    # Com dados gerais alterados, nada é herdado
    lista = [dict(a) for a in APROVACOES]
    herdar_aprovacoes(lista, r1, gerais_mudaram=True)
    assert not any(a.get("herdada") for a in lista)

    # Rodada anterior sai de cena: sem botões e não é mais a última da escola
    antigo = marcar_sucedida(r1["key"], r2["key"])
    antigo["card_na_thread"] = True
    assert action_ids(build_thread_blocks(antigo)) == []
    assert ultima_rodada_da_escola("C1", FORM["cnpj"])["key"] == r2["key"]
    assert get_ticket(r2["key"])["status"] == "pending"

msg = mensagem_nova_rodada(2, MODO_REENVIO, "UCONS", mud, [{"nome": "Desconto", "contexto": "5%"}],
                           [{"nome": "Desconto", "contexto": "10%"}], "ajustei")
assert "Rodada 2 · Reenvio com ajustes" in msg and "R$ 10.000,00 → R$ 12.000,00" in msg
assert "antes: _10%_" in msg and "agora: _5%_" in msg

# Formulário curto: exceções + "Editar formulário completo"; o completo trava o CNPJ
rodada = {"modo": "reenvio", "parent_key": "C1_1.1", "cnpj": "17407203000108"}
curto = build_rodada_modal(rodada, "ESCOLA", "crescimento", [{"nome": "Desconto", "contexto": "10%"}], 1)
assert curto["callback_id"] == "modal_rodada"
assert action_ids(curto["blocks"]) == ["btn_rodada_add_exception", "btn_rodada_form_completo"]
completo = build_aprovacoes_modal("UCONS", "C1", saved_values=dict(FORM), tipo_fluxo="crescimento", rodada=rodada)
ids = [b.get("block_id") or "" for b in completo["blocks"]]
assert "cnpj_travado_block" in ids and not any(i.startswith("cnpj_block") for i in ids)
assert "btn_buscar_cnpj" not in action_ids(completo["blocks"])

print("test_rodadas OK")
