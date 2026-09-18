import re
import requests
from typing import Dict, Any

def consultar_cnpj(cnpj_raw: str) -> Dict[str, Any]:
    """
    Consulta dados do CNPJ com redundância/fallback:
    1º Tenta BrasilAPI
    2º Tenta ReceitaWS
    3º Tenta CNPJ.ws Pública
    """
    cnpj_limpo = re.sub(r"\D", "", cnpj_raw or "")
    
    if len(cnpj_limpo) != 14:
        return {
            "sucesso": False,
            "erro": "CNPJ deve conter exatamente 14 dígitos numéricos.",
        }

    # Provedor 1: BrasilAPI
    try:
        url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}"
        headers = {"User-Agent": "Arco-Slack-Bot/1.0"}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            tipo_raw = data.get("descricao_identificador_matriz_filial") or data.get("descricao_matriz_filial") or data.get("identificador_matriz_filial") or ""
            if str(tipo_raw) == "1":
                tipo = "MATRIZ"
            elif str(tipo_raw) == "2":
                tipo = "FILIAL"
            else:
                tipo = str(tipo_raw).upper() if tipo_raw else "MATRIZ"

            razao = (data.get("razao_social") or "").strip()
            fantasia = (data.get("nome_fantasia") or "").strip() or razao

            return {
                "sucesso": True,
                "cnpj": cnpj_limpo,
                "razao_social": razao,
                "nome_fantasia": fantasia,
                "municipio": (data.get("municipio") or "").strip(),
                "uf": (data.get("uf") or "").strip(),
                "tipo": tipo,
                "situacao": (data.get("descricao_situacao_cadastral") or "ATIVA").strip(),
                "cnae_fiscal_descricao": data.get("cnae_fiscal_descricao") or "",
            }
    except Exception:
        pass

    # Provedor 2: ReceitaWS
    try:
        url = f"https://receitaws.com.br/v1/cnpj/{cnpj_limpo}"
        headers = {"User-Agent": "Arco-Slack-Bot/1.0"}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "OK":
                razao = (data.get("nome") or "").strip()
                fantasia = (data.get("fantasia") or "").strip() or razao
                tipo = (data.get("tipo") or "MATRIZ").strip().upper()
                return {
                    "sucesso": True,
                    "cnpj": cnpj_limpo,
                    "razao_social": razao,
                    "nome_fantasia": fantasia,
                    "municipio": (data.get("municipio") or "").strip(),
                    "uf": (data.get("uf") or "").strip(),
                    "tipo": tipo,
                    "situacao": (data.get("situacao") or "ATIVA").strip(),
                    "cnae_fiscal_descricao": data.get("atividade_principal", [{}])[0].get("text", ""),
                }
    except Exception:
        pass

    # Provedor 3: CNPJ.ws pública
    try:
        url = f"https://publica.cnpj.ws/cnpj/{cnpj_limpo}"
        headers = {"User-Agent": "Arco-Slack-Bot/1.0"}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            estabelecimento = data.get("estabelecimento", {})
            razao = (data.get("razao_social") or "").strip()
            fantasia = (estabelecimento.get("nome_fantasia") or "").strip() or razao
            tipo = (estabelecimento.get("tipo") or "MATRIZ").strip().upper()
            return {
                "sucesso": True,
                "cnpj": cnpj_limpo,
                "razao_social": razao,
                "nome_fantasia": fantasia,
                "municipio": (estabelecimento.get("cidade", {}).get("nome") or "").strip(),
                "uf": (estabelecimento.get("estado", {}).get("sigla") or "").strip(),
                "tipo": tipo,
                "situacao": (estabelecimento.get("situacao_cadastral") or "ATIVA").strip(),
                "cnae_fiscal_descricao": estabelecimento.get("atividade_principal", {}).get("descricao", ""),
            }
    except Exception:
        pass

    return {
        "sucesso": False,
        "erro": "Não foi possível obter dados do CNPJ nos provedores públicos. Você pode preencher a Razão Social manualmente.",
    }
