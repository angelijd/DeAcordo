import sys
from config.exceptions_rules import EXCEPTIONS_RULES, ALL_EXCEPTIONS_LIST
from config.approvers_map import format_user_mention

print(f"Total de regras cadastradas: {len(ALL_EXCEPTIONS_LIST)}")

# Teste 1: Regra com Líder Direto
regra_multa = EXCEPTIONS_RULES.get("Pagamento de multa do concorrente")
assert regra_multa["comercial_approver"] == "LIDER_DIRETO"

# Teste 2: Regra com Aprovador específico (Rafael Martinez)
regra_excl = EXCEPTIONS_RULES.get("Exclusividade de fornecimento - Município")
assert regra_excl["comercial_approver"] == "Rafael Martinez"
assert format_user_mention(regra_excl["comercial_approver"]) == "@Rafael Martinez"

# Teste 3: Modalidade de venda - dívida > 50k vai para Matheus Alves Rocha; até 50k é automática
from config.exceptions_rules import aplicar_dispensa_por_divida
regra_divida = EXCEPTIONS_RULES.get("Modalidade de venda - alteração (B2C x B2B x B2B2B)")
assert regra_divida.get("check_debt") is True
assert regra_divida["ops_approver"] == "Matheus Alves Rocha"
assert format_user_mention("Matheus Alves Rocha") == "<@U09R71Q9UHM>"
for divida, esperado in ((0.0, None), (50000.0, None), (50000.01, "Matheus Alves Rocha")):
    efetiva, dispensa = aplicar_dispensa_por_divida(regra_divida, divida)
    assert efetiva["ops_approver"] == esperado, (divida, efetiva)
    assert bool(dispensa) == (esperado is None)
# Outras exceções com dívida não mudaram (seguem com Rafael Bae)
regra_incentivo = EXCEPTIONS_RULES.get("Incentivo Comercial para inadimplentes")
assert aplicar_dispensa_por_divida(regra_incentivo, 0.0)[0]["ops_approver"] == "Rafael Bae"

# Teste 4: Regra com N3 (Chalfun/Faleiros)
regra_mat_opcional = EXCEPTIONS_RULES.get("Material opcional sem principal")
assert regra_mat_opcional["comercial_approver"] == "N3 - Direto do Chalfun/Faleiros"
assert regra_mat_opcional["ops_approver"] == "Ingrid Mariana De Souza Costa"

print("SUCCESS: Todos os testes unitarios de regras foram aprovados com sucesso!")
