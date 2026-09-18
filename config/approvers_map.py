"""
Mapeamento de Aprovadores por Nome e Cargo.
Você pode preencher o 'slack_id' (ex.: 'U0123456789') de cada pessoa conforme descobrir no Workspace.
Se o slack_id estiver vazio, o bot exibirá a menção com o nome @Nome em texto.
"""

APPROVERS_CONFIG = {
    "Rafael Martinez": {
        "slack_id": "",
        "tag_role": "@triagem psc",
    },
    "Rafael Bae": {
        "slack_id": "",
        "tag_role": "@triagem--contratos psc",
    },
    "Thibaut Frederic Choukroun": {
        "slack_id": "",
        "tag_role": "Operações / Logística",
    },
    "Lucas Alves Ramos": {
        "slack_id": "",
        "tag_role": "Operações / Produtos",
    },
    "Ingrid Mariana De Souza Costa": {
        "slack_id": "",
        "tag_role": "Pedagógico / Adaptações",
    },
    "Aline Del Pezzo": {
        "slack_id": "",
        "tag_role": "@triagem",
    },
    "Gleidson Oliveira": {
        "slack_id": "",
        "tag_role": "Comercial / PIC",
    },
    "Thais Teixeira De Oliveira Rego": {
        "slack_id": "",
        "tag_role": "Jurídico / Foro",
    },
    "Luani Bissi": {
        "slack_id": "",
        "tag_role": "Financeiro / Repasse",
    },
    "Matheus Alves Rocha": {
        "slack_id": "",
        "tag_role": "Financeiro / Repasse",
    },
    "Rafael Soares Da Silva": {
        "slack_id": "",
        "tag_role": "TI / Chromebook",
    },
    "Bianca Assone Rodrigues": {
        "slack_id": "",
        "tag_role": "Jurídico / LGPD",
    },
    "Livia Goia De Araujo Rossi": {
        "slack_id": "",
        "tag_role": "Regulatório / CNAE",
    },
    "Maria Julia Pagani Fazano": {
        "slack_id": "",
        "tag_role": "Financeiro / Multa e Juros",
    },
    "Nath Nobre": {
        "slack_id": "",
        "tag_role": "Financeiro / Cobrança",
    },
    "Rhayam Oliveira Nascimento": {
        "slack_id": "",
        "tag_role": "Comercial / Churn 0",
    },
    "Rafael De Simone Martines": {
        "slack_id": "",
        "tag_role": "Comercial / Comodato",
    },
    "Ana Beatriz Do Vale Silva": {
        "slack_id": "",
        "tag_role": "Comercial / B2C SAS",
    },
    "Carla Beatriz Catunda Fernandes": {
        "slack_id": "",
        "tag_role": "Comercial / B2C SAS",
    },
    "N3 - Direto do Chalfun/Faleiros": {
        "slack_id": "",
        "tag_role": "Diretoria Comercial N3",
    },
    "Diana Sarah Proenca De Oliveira": {
        "slack_id": "",
        "tag_role": "Aprovação Inviabilidade",
    },
    "Theo Constantinesco Hamaoui": {
        "slack_id": "",
        "tag_role": "Aprovação Exceções",
    },
    "Felipe Fanali Daniel": {
        "slack_id": "",
        "tag_role": "Liderança Comercial",
    },
    "Fernando Rodrigues Santos": {
        "slack_id": "",
        "tag_role": "Consultor Comercial",
    },
}

def format_user_mention(name: str) -> str:
    """Retorna <@USER_ID> se configurado, ou @Nome se ainda não mapeado."""
    config = APPROVERS_CONFIG.get(name)
    if config and config.get("slack_id"):
        return f"<@{config['slack_id']}>"
    return f"@{name}"
