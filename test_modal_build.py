import json
from views.modals import build_aprovacoes_modal

modal = build_aprovacoes_modal(
    current_user_id="U12345678",
    channel_id="C12345678",
    num_exceptions=3,
    is_rede=True,
    saved_values={"frente": "(CE) Inbound", "cnpj": "00000000000191", "razao_social": "BANCO DO BRASIL SA"},
    cnpj_info={"sucesso": True, "municipio": "BRASILIA", "uf": "DF", "tipo": "MATRIZ", "situacao": "ATIVA"}
)

print(f"Modal gerado com sucesso!")
print(f"Tipo da view: {modal['type']}")
print(f"Callback ID: {modal['callback_id']}")
print(f"Titulo: {modal['title']['text']}")
print(f"Total de blocos: {len(modal['blocks'])}")
assert len(modal['blocks']) > 15
print("SUCCESS: Estrutura do modal validada!")
