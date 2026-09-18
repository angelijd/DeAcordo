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

# Teste 3: Regra com verificação de dívida (Rafael Bae)
regra_divida = EXCEPTIONS_RULES.get("Modalidade de venda - alteração (B2C x B2B x B2B2B)")
assert regra_divida.get("check_debt") is True
assert regra_divida["ops_approver"] == "Rafael Bae"

# Teste 4: Regra com N3 (Chalfun/Faleiros)
regra_mat_opcional = EXCEPTIONS_RULES.get("Material opcional sem principal")
assert regra_mat_opcional["comercial_approver"] == "N3 - Direto do Chalfun/Faleiros"
assert regra_mat_opcional["ops_approver"] == "Ingrid Mariana De Souza Costa"

print("SUCCESS: Todos os testes unitarios de regras foram aprovados com sucesso!")
