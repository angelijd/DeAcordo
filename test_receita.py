from services.receita_service import consultar_cnpj

# CNPJ de teste (ex: Petrobras ou Arco se público, ou Banco do Brasil: 00000000000191)
resultado = consultar_cnpj("00000000000191")
print("Resultado da consulta de teste:")
print(resultado)
