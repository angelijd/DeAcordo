import json
from views.modals import build_aprovacoes_modal

modal = build_aprovacoes_modal(
    current_user_id="U12345678",
    channel_id="C12345678",
    num_exceptions=3,
    is_rede=True,
    saved_values={"frente": "(CE) Inbound", "cnpj": "00000000000191", "razao_social": "BANCO DO BRASIL SA"},
    cnpj_info={"sucesso": True, "municipio": "BRASILIA", "uf": "DF", "tipo": "MATRIZ", "situacao": "ATIVA"},
    tipo_fluxo="crescimento",
)

print(f"Modal gerado com sucesso!")
print(f"Tipo da view: {modal['type']}")
print(f"Callback ID: {modal['callback_id']}")
print(f"Titulo: {modal['title']['text']}")
print(f"Total de blocos: {len(modal['blocks'])}")
assert len(modal['blocks']) > 15
print("SUCCESS: Estrutura do modal validada!")

# Canal não mapeado (tipo_fluxo=None): só o seletor manual de Tipo de Solicitação
modal_fallback = build_aprovacoes_modal(
    current_user_id="U12345678",
    channel_id="C_NAO_MAPEADO",
    tipo_fluxo=None,
)
assert len(modal_fallback["blocks"]) == 1
assert modal_fallback["blocks"][0]["block_id"] == "tipo_fluxo_select_block"
print("SUCCESS: Fallback de canal não mapeado validado!")

# Renovação: campos específicos aparecem, inviabilidade por marca não aparece
modal_renovacao = build_aprovacoes_modal(
    current_user_id="U12345678",
    channel_id="C_RENOVACAO",
    tipo_fluxo="renovacao",
)
block_ids_renovacao = [b.get("block_id") for b in modal_renovacao["blocks"]]
assert "reajuste_liquido_block" in block_ids_renovacao
assert "aprovador_simulador_block" in block_ids_renovacao
assert "aprovador_n3_block" not in block_ids_renovacao
assert "aprovador_n3_info_block" in block_ids_renovacao
assert not any((b or "").startswith("inviab_block_") for b in block_ids_renovacao)
frente_block = next(b for b in modal_renovacao["blocks"] if b.get("block_id") == "frente_block")
assert [o["value"] for o in frente_block["element"]["options"]] == ["CSE", "CSP"]
print("SUCCESS: Campos específicos de Renovação validados!")

# N3 automático por Frente + Marca
from config.n3_config import resolver_aprovadores_n3

n3 = resolver_aprovadores_n3("CSE", ["COC"])
assert [(p["nome"], p["marcas"]) for p in n3] == [("Camila Lima Moreira", ["COC"])]

n3 = resolver_aprovadores_n3("CSP", ["COC", "Geekie", "SAE", "CQT (Conquista)"])
assert [p["nome"] for p in n3] == ["Renato Judice", "Andreia Moraes", "Juliana Loures"]
assert n3[2]["marcas"] == ["SAE", "CQT (Conquista)"]

n3 = resolver_aprovadores_n3("CSE", ["MARALTO", "GF"])
assert len(n3) == 1 and n3[0]["nome"] == "Livia Archeti"

assert resolver_aprovadores_n3("(CE) Inbound", ["COC"]) == []
print("SUCCESS: Aprovador N3 automático validado!")
