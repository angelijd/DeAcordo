import os
import csv
import re
import unicodedata
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("inep_service")

def normalizar_texto(texto: str) -> str:
    """Remove acentos, pontuação e converte para maiúsculas para comparação limpa."""
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join([c for c in nfkd if not unicodedata.combining(c)])
    limpo = re.sub(r"[^A-Za-z0-9\s]", " ", sem_acento).upper()
    return " ".join(limpo.split())

STOPWORDS = {
    "DE", "DA", "DO", "DOS", "DAS", "E", "EM", "LTDA", "ME", "EPP", "SA", "S/A", "CIA",
    "COLEGIO", "ESCOLA", "CENTRO", "EDUCACIONAL", "INSTITUTO", "ENSINO", "UNIDADE",
    "COMPLEXO", "GRUPO", "REDE", "ASSOCIACAO", "SOCIEDADE", "EDUCACAO", "EXTERNATO"
}

def extrair_tokens(texto: str):
    """Extrai palavras-chave distintivas ignorando termos comuns/stopwords."""
    norm = normalizar_texto(texto)
    return set([w for w in norm.split() if w not in STOPWORDS and len(w) >= 2])

# Cache em memória para buscas ultra-rápidas
_CENSO_CACHE = None
_CENSO_ITEMS = None

def _carregar_censo():
    """Carrega o arquivo censo_inep.csv em cache."""
    global _CENSO_CACHE, _CENSO_ITEMS
    if _CENSO_CACHE is not None and _CENSO_ITEMS is not None:
        return _CENSO_CACHE, _CENSO_ITEMS

    _CENSO_CACHE = {}
    _CENSO_ITEMS = []
    
    # Procura pelo arquivo CSV na pasta raiz ou em data/
    caminhos = [
        os.path.join(os.path.dirname(__file__), "..", "censo_inep.csv"),
        os.path.join(os.path.dirname(__file__), "..", "data", "censo_inep.csv"),
    ]

    arquivo_encontrado = None
    for p in caminhos:
        if os.path.exists(p):
            arquivo_encontrado = p
            break

    if not arquivo_encontrado:
        logger.warning("Arquivo censo_inep.csv ainda não encontrado. O preenchimento do INEP será manual.")
        return _CENSO_CACHE, _CENSO_ITEMS

    try:
        with open(arquivo_encontrado, mode="r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                inep = row.get("codigo_inep") or row.get("INEP") or row.get("co_entidade")
                nome_escola = row.get("escola") or row.get("nome_escola") or row.get("no_entidade")
                
                if inep and nome_escola:
                    inep_str = str(inep).strip()
                    nome_str = str(nome_escola).strip()
                    norm = normalizar_texto(nome_str)
                    toks = extrair_tokens(nome_str)
                    _CENSO_CACHE[norm] = inep_str
                    _CENSO_ITEMS.append((inep_str, nome_str, norm, toks))
                    
        logger.info(f"✅ Base do Censo INEP carregada com sucesso! Total de escolas: {len(_CENSO_ITEMS)}")
    except Exception as e:
        logger.error(f"Erro ao carregar censo_inep.csv: {e}")

    return _CENSO_CACHE, _CENSO_ITEMS


def _pesquisar_termo(termo: str, metodo_nome: str) -> Optional[Dict[str, Any]]:
    """Busca um termo (Nome Fantasia ou Razão Social) com correspondência Exata, Substring e Tokens."""
    if not termo or len(termo.strip()) < 3:
        return None

    tabela, itens = _carregar_censo()
    if not tabela or not itens:
        return None

    norm_termo = normalizar_texto(termo)
    tok_termo = extrair_tokens(termo)

    # 1. Correspondência Exata
    if norm_termo in tabela:
        return {
            "codigo_inep": tabela[norm_termo],
            "metodo": f"{metodo_nome} (Exato)",
            "termo_encontrado": termo,
        }

    # 2. Correspondência por Substring
    if len(norm_termo) > 6:
        for inep, raw_nome, norm_c, _ in itens:
            if norm_termo in norm_c or norm_c in norm_termo:
                return {
                    "codigo_inep": inep,
                    "metodo": f"{metodo_nome} (Contém)",
                    "termo_encontrado": raw_nome,
                }

    # 3. Correspondência Inteligente por Conjunto de Tokens (MEC inverte ordem dos nomes)
    if tok_termo:
        best_match = None
        best_score = 0.0

        for inep, raw_nome, norm_c, tok_c in itens:
            if not tok_c:
                continue
            inter = tok_termo & tok_c
            if not inter:
                continue

            # Conjunto exato de palavras-chave
            if tok_termo == tok_c:
                return {
                    "codigo_inep": inep,
                    "metodo": f"{metodo_nome} (Palavras-chave Exatas)",
                    "termo_encontrado": raw_nome,
                }

            # Sobreposição e subconjuntos
            score = len(inter) / max(len(tok_termo), len(tok_c))
            if len(inter) >= 2 and (tok_c.issubset(tok_termo) or tok_termo.issubset(tok_c)):
                score = max(score, 0.85)
            elif len(tok_c) == 1 and len(tok_termo) == 1 and tok_c == tok_termo:
                score = 1.0

            if score > best_score and score >= 0.70:
                best_score = score
                best_match = {
                    "codigo_inep": inep,
                    "metodo": f"{metodo_nome} (Aproximação {int(score*100)}%)",
                    "termo_encontrado": raw_nome,
                }

        if best_match:
            return best_match

    return None


def buscar_inep(nome_fantasia: str, razao_social: str) -> Optional[Dict[str, Any]]:
    """
    Executa a estratégia de contingência:
    - Plano A: Busca por Nome Fantasia
    - Plano B: Busca por Razão Social
    - Plano C: Retorna None (consultor preenche manualmente)
    """
    # 1. PLANO A: Nome Fantasia
    res_a = _pesquisar_termo(nome_fantasia, "Plano A (Nome Fantasia)")
    if res_a:
        return res_a

    # 2. PLANO B: Razão Social
    res_b = _pesquisar_termo(razao_social, "Plano B (Razão Social)")
    if res_b:
        return res_b

    # 3. PLANO C: Não encontrado (deixa em branco)
    return None
