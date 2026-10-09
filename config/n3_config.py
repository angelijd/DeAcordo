"""
Aprovador N3 (Renovação) definido automaticamente pela Vertical (Frente CSE/CSP) e pela Marca.
Fonte: planilha "N3_por_marca" enviada pela Jéssica em 2026-10-09.
"""

import os
from typing import Dict, List, Optional

# false = só cita o nome do N3 (sem marcar no Slack e sem DM); true = marca e manda a DM de aprovação.
N3_MARCAR_APROVADORES = os.environ.get("N3_MARCAR_APROVADORES", "false").lower() == "true"

# Regra por segmento (Ultra High / Low) desligada até o formulário perguntar o segmento da escola.
N3_USAR_SEGMENTO = False

_MARCAS_PLUS = ["MARALTO", "NAV / Nave à Vela", "IS", "PES", "EI", "GF"]

# Grupos da planilha -> nomes de marca usados no formulário
_GRUPOS_MARCA: Dict[str, List[str]] = {
    "COC": ["COC"],
    "Geekie": ["Geekie"],
    "SAS": ["SAS"],
    "Positivo": ["SPE (Sistema Positivo de Ensino)"],
    "SAE e Conquista": ["SAE", "CQT (Conquista)"],
    "Arco Plus": _MARCAS_PLUS,
}

N3_POR_MARCA = [
    {"vertical": "CSE", "grupo": "COC", "nome": "Camila Lima Moreira", "slack_id": "U08P0H6A9HR"},
    {"vertical": "CSE", "grupo": "Geekie", "nome": "Gabriela Oliveira Almeida", "slack_id": "U08905NE6B0"},
    {"vertical": "CSE", "grupo": "SAS", "nome": "Henrique Luithardt", "slack_id": "U094L1MMTSA"},
    {"vertical": "CSE", "grupo": "Positivo", "nome": "Milena Kendrick", "slack_id": "U0579UKGJEM"},
    {"vertical": "CSE", "grupo": "SAE e Conquista", "nome": "Julia Beloni", "slack_id": "U0BEMGTBMT9"},
    {"vertical": "CSE", "grupo": "Arco Plus", "nome": "Livia Archeti", "slack_id": "U06TXM43MKN"},
    {"vertical": "CSP", "grupo": "COC", "nome": "Renato Judice", "slack_id": "U08SWETHQ90"},
    # Slack ID ainda não informado: aparece só como nome.
    {"vertical": "CSP", "grupo": "Geekie", "nome": "Andreia Moraes", "slack_id": ""},
    {"vertical": "CSP", "grupo": "SAS", "nome": "Kassiopeya", "slack_id": "U056UACUTHB"},
    {"vertical": "CSP", "grupo": "Positivo", "nome": "Eduarda Fernandes", "slack_id": "U034AN776VD"},
    {"vertical": "CSP", "grupo": "SAE e Conquista", "nome": "Juliana Loures", "slack_id": "U095WTCNTFT"},
    {"vertical": "CSP", "grupo": "Arco Plus", "nome": "Milene Bento", "slack_id": "U07D3CDJ5M0"},
]

N3_POR_SEGMENTO = [
    {"vertical": "CSE", "segmento": "Ultra High", "nome": "Marcelo Pereira", "slack_id": "U0AQE77JYPR"},
    {"vertical": "CSE", "segmento": "Low", "nome": "Camila Ribeiro", "slack_id": "U029X7M4VUJ"},
    {"vertical": "CSP", "segmento": "Ultra High", "nome": "Marco Moriggi", "slack_id": "U0579QLAA9X"},
    {"vertical": "CSP", "segmento": "Low", "nome": "Karina de Lemos", "slack_id": "U056GPKA7M5"},
]


def _vertical_da_frente(frente: Optional[str]) -> Optional[str]:
    frente = (frente or "").upper()
    if "CSE" in frente and "CSP" not in frente:
        return "CSE"
    if "CSP" in frente and "CSE" not in frente:
        return "CSP"
    return None


def resolver_aprovadores_n3(frente: Optional[str], marcas: List[str], segmento: Optional[str] = None) -> List[Dict]:
    """
    Retorna um aprovador N3 por pessoa distinta, com as marcas que ela cobre:
    [{"nome", "slack_id", "marcas": [...]}]. Lista vazia se a frente não for CSE/CSP.
    """
    vertical = _vertical_da_frente(frente)
    if not vertical:
        return []

    por_pessoa: Dict[str, Dict] = {}

    def _adicionar(entrada: Dict, marca: str):
        chave = entrada["slack_id"] or entrada["nome"]
        pessoa = por_pessoa.setdefault(chave, {"nome": entrada["nome"], "slack_id": entrada["slack_id"], "marcas": []})
        if marca not in pessoa["marcas"]:
            pessoa["marcas"].append(marca)

    for marca in marcas or []:
        if N3_USAR_SEGMENTO and segmento:
            entrada = next(
                (e for e in N3_POR_SEGMENTO if e["vertical"] == vertical and e["segmento"] == segmento),
                None,
            )
            if entrada:
                _adicionar(entrada, marca)
                continue

        entrada = next(
            (e for e in N3_POR_MARCA if e["vertical"] == vertical and marca in _GRUPOS_MARCA.get(e["grupo"], [])),
            None,
        )
        if entrada:
            _adicionar(entrada, marca)

    return list(por_pessoa.values())
