"""
Thread única por escola: cada novo pedido de uma escola (identificada pelo CNPJ)
vira uma nova "rodada" dentro da mesma thread do canal, em vez de um post novo.
"""

import copy
import re
from typing import Any, Dict, List, Optional, Tuple

from services.ticket_service import load_tickets
from utils.currency_words import format_real_input

MODO_NOVA = "nova"
MODO_REENVIO = "reenvio"

MODO_LABEL = {
    MODO_NOVA: "Nova aprovação",
    MODO_REENVIO: "Reenvio com ajustes",
}

# Campos gerais do formulário (tudo menos as exceções). Se algum mudar, as
# alçadas obrigatórias (Comercial, Simulador, N3, Inviabilidade, Dívida) decidem de novo.
CAMPOS_GERAIS: List[Tuple[str, str]] = [
    ("tipo_fluxo", "Tipo de solicitação"),
    ("frente", "Frente"),
    ("consultor", "Consultor"),
    ("lider", "Líder direto"),
    ("marcas", "Marcas"),
    ("razao_social", "Razão social"),
    ("inep", "INEP"),
    ("rede_grupo", "Rede/Grupo"),
    ("nome_rede", "Nome da rede"),
    ("cnpjs_rede", "CNPJs da rede"),
    ("alunado", "Alunado"),
    ("acv", "Valor do contrato (ACV)"),
    ("tem_divida", "Possui dívida"),
    ("valor_divida", "Valor da dívida"),
    ("link_sf", "Link SalesForce"),
    ("inviabilidades", "Inviabilidade"),
    ("reajuste_liquido", "% Reajuste líquido"),
    ("aprovador_simulador", "Aprovador do simulador"),
    ("contexto_geral", "Contexto geral"),
    ("simulador_link", "Link do simulador"),
]

_CAMPOS_USUARIO = {"consultor", "lider", "aprovador_simulador"}
_CAMPOS_VALOR = {"acv", "valor_divida"}


def cnpj_digitos(cnpj: Any) -> str:
    return re.sub(r"\D", "", str(cnpj or ""))


def _numero(valor: Any) -> str:
    texto = str(valor or "").replace("%", "").strip().replace(",", ".")
    try:
        return f"{float(texto):g}"
    except ValueError:
        return texto


def _normalizar(campo: str, valor: Any) -> str:
    if campo == "marcas":
        return ", ".join(sorted(valor or []))
    if campo == "inviabilidades":
        return "; ".join(f"{m}: {_numero(v)}%" for m, v in sorted((valor or {}).items()) if str(v or "").strip())
    if campo in _CAMPOS_VALOR:
        return format_real_input(valor) if str(valor or "").strip() else ""
    if campo in ("alunado", "reajuste_liquido"):
        return _numero(valor) if str(valor or "").strip() else ""
    if campo == "tipo_fluxo":
        return {"crescimento": "Crescimento", "renovacao": "Renovação"}.get(valor or "", str(valor or ""))
    if campo in ("rede_grupo", "tem_divida"):
        return {"sim": "Sim", "nao": "Não"}.get(valor or "", str(valor or ""))
    return str(valor or "").strip()


def _exibir(campo: str, valor_normalizado: str) -> str:
    if not valor_normalizado:
        return "_(vazio)_"
    if campo in _CAMPOS_USUARIO and valor_normalizado.startswith(("U", "W")):
        return f"<@{valor_normalizado}>"
    if campo in _CAMPOS_VALOR:
        return f"R$ {valor_normalizado}"
    if campo in ("contexto_geral",) and len(valor_normalizado) > 300:
        return valor_normalizado[:300] + "…"
    return valor_normalizado


def campos_alterados(antes: Dict[str, Any], depois: Dict[str, Any]) -> List[Dict[str, str]]:
    """Campos gerais que mudaram entre duas rodadas, já formatados para exibição."""
    mudancas = []
    for campo, rotulo in CAMPOS_GERAIS:
        a = _normalizar(campo, antes.get(campo))
        d = _normalizar(campo, depois.get(campo))
        if a != d:
            mudancas.append({"campo": campo, "rotulo": rotulo, "antes": _exibir(campo, a), "depois": _exibir(campo, d)})
    return mudancas


def excecoes_do_formulario(valores: Dict[str, Any], num_exceptions: int = 5) -> List[Dict[str, str]]:
    excecoes = []
    for i in range(1, max(num_exceptions, 5) + 1):
        nome = valores.get(f"excecao_{i}")
        if nome and nome != "N/A":
            excecoes.append({"nome": nome, "contexto": (valores.get(f"contexto_excecao_{i}") or "").strip()})
    return excecoes


def limpar_excecoes(valores: Dict[str, Any]) -> Dict[str, Any]:
    novo = copy.deepcopy(valores)
    for i in range(1, 6):
        novo.pop(f"excecao_{i}", None)
        novo.pop(f"contexto_excecao_{i}", None)
    return novo


def preencher_excecoes(valores: Dict[str, Any], excecoes: List[Dict[str, str]]) -> Dict[str, Any]:
    novo = limpar_excecoes(valores)
    for i, exc in enumerate(excecoes[:5], start=1):
        novo[f"excecao_{i}"] = exc["nome"]
        novo[f"contexto_excecao_{i}"] = exc.get("contexto") or ""
    return novo


def valores_do_ticket(ticket: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """
    Valores do formulário da rodada. Retorna (valores, completos). Pedidos criados antes
    da thread única não guardavam o formulário: devolve o que dá para reaproveitar e
    completos=False (aí o consultor vai direto para o formulário completo).
    """
    extra = ticket.get("extra_data") or {}
    if extra.get("form_values"):
        return copy.deepcopy(extra["form_values"]), True
    marcas = [m.strip() for m in str(extra.get("marcas") or "").split(",") if m.strip() and m.strip() != "Não informada"]
    acv = str(extra.get("acv") or "").replace("R$", "").strip()
    valores = {
        "tipo_fluxo": extra.get("tipo_fluxo"),
        "frente": extra.get("frente") or None,
        "consultor": ticket.get("consultor_id") or None,
        "marcas": marcas,
        "cnpj": extra.get("cnpj") or ticket.get("cnpj"),
        "razao_social": ticket.get("escola"),
        "inep": extra.get("inep") if extra.get("inep") not in (None, "-") else None,
        "rede_grupo": extra.get("rede_grupo") or None,
        "nome_rede": extra.get("nome_rede") or None,
        "cnpjs_rede": extra.get("cnpjs_rede") or None,
        "alunado": extra.get("alunado"),
        "acv": acv if acv and acv != "Não informado" else "",
        "link_sf": extra.get("link_sf") or None,
        "contexto_geral": extra.get("contexto_geral") or None,
        "simulador_link": extra.get("simulador_link") or "",
    }
    return valores, False


def excecoes_reprovadas_da_rodada(ticket: Dict[str, Any]) -> List[Dict[str, str]]:
    """Exceções que alguma alçada reprovou, na ordem do pedido, com nome e contexto originais."""
    numeros: List[str] = []
    for key, apprv in (ticket.get("approvals") or {}).items():
        m = re.match(r"excecao_(\d+)_", key)
        if m and apprv.get("status") == "rejected" and m.group(1) not in numeros:
            numeros.append(m.group(1))
    por_numero = {str(e.get("numero")): e for e in (ticket.get("extra_data") or {}).get("excecoes") or []}
    return [
        {"nome": por_numero[n]["nome"], "contexto": por_numero[n].get("contexto") or ""}
        for n in numeros if n in por_numero
    ]


def tem_obrigatoria_nao_aprovada(ticket: Dict[str, Any]) -> bool:
    return any(
        not a.get("parcial") and a.get("status") != "approved"
        for a in (ticket.get("approvals") or {}).values()
    )


def rodada_de(ticket: Dict[str, Any]) -> int:
    return int(ticket.get("rodada") or 1)


def rodadas_da_thread(channel_id: str, thread_ts: str, tickets: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    tickets = tickets if tickets is not None else load_tickets()
    rodadas = [t for t in tickets.values() if t.get("channel_id") == channel_id and t.get("thread_ts") == thread_ts]
    return sorted(rodadas, key=rodada_de)


def ultima_rodada_da_escola(channel_id: str, cnpj: Any, tickets: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Rodada mais recente da escola (pelo CNPJ) neste canal, ou None se a escola ainda não tem thread."""
    digitos = cnpj_digitos(cnpj)
    if len(digitos) != 14:
        return None
    tickets = tickets if tickets is not None else load_tickets()
    candidatos = [
        t for t in tickets.values()
        if t.get("channel_id") == channel_id
        and not t.get("sucedida_por")
        and cnpj_digitos((t.get("extra_data") or {}).get("cnpj") or t.get("cnpj")) == digitos
    ]
    if not candidatos:
        return None
    return max(candidatos, key=lambda t: (float(t.get("thread_ts") or 0), rodada_de(t)))


def herdar_aprovacoes(approvals_list: List[Dict[str, Any]], anterior: Dict[str, Any], gerais_mudaram: bool) -> None:
    """
    Alçadas obrigatórias já aprovadas na rodada anterior não decidem de novo se os dados
    gerais não mudaram. Exceções sempre decidem (cada rodada só traz exceções novas ou reenviadas).
    """
    if gerais_mudaram:
        return
    aprovacoes_anteriores = anterior.get("approvals") or {}
    for apprv in approvals_list:
        if apprv.get("parcial"):
            continue
        prev = aprovacoes_anteriores.get(apprv["key"])
        if not prev or prev.get("status") != "approved":
            continue
        apprv["herdada"] = prev.get("herdada") or {
            "rodada": rodada_de(anterior),
            "approved_by_id": prev.get("approved_by_id"),
            "approved_by_name": prev.get("approved_by_name"),
            "approved_at": prev.get("approved_at"),
        }


def mensagem_nova_rodada(
    rodada: int,
    modo: str,
    autor_id: str,
    mudancas: List[Dict[str, str]],
    excecoes: List[Dict[str, str]],
    excecoes_antes: List[Dict[str, str]],
    observacao: str = "",
) -> str:
    """Abre a rodada na thread mostrando tudo que o consultor mudou em relação à rodada anterior."""
    linhas = [f"🔁 *Rodada {rodada} · {MODO_LABEL.get(modo, 'Nova solicitação')}* · enviada por <@{autor_id}>"]
    if observacao:
        linhas.append(f"> 💬 {observacao.strip()[:1500]}".replace("\n", "\n> "))

    if mudancas:
        linhas.append("\n*O que mudou no formulário:*")
        for m in mudancas:
            linhas.append(f"• *{m['rotulo']}:* {m['antes']} → {m['depois']}")
    else:
        linhas.append("\n*Formulário:* sem alterações nos dados gerais.")

    if modo == MODO_REENVIO and excecoes_antes:
        linhas.append("\n*Exceções reprovadas na rodada anterior:*")
        for i, antes in enumerate(excecoes_antes):
            depois = excecoes[i] if i < len(excecoes) else None
            if not depois:
                linhas.append(f"• ~{antes['nome']}~ · retirada")
            elif depois["nome"] == antes["nome"] and depois["contexto"] == antes["contexto"]:
                linhas.append(f"• {antes['nome']} · reenviada sem alteração")
            else:
                trecho = f"• {antes['nome']} → *{depois['nome']}*" if depois["nome"] != antes["nome"] else f"• *{antes['nome']}*"
                if depois["contexto"] != antes["contexto"]:
                    trecho += f"\n> antes: _{antes['contexto'][:400] or '(sem contexto)'}_\n> agora: _{depois['contexto'][:400] or '(sem contexto)'}_"
                linhas.append(trecho)
        novas = excecoes[len(excecoes_antes):]
    else:
        novas = excecoes

    if novas:
        linhas.append("\n*Exceções novas:*")
        for exc in novas:
            linha = f"• *{exc['nome']}*"
            if exc.get("contexto"):
                linha += f"\n> {exc['contexto'][:400]}"
            linhas.append(linha)
    return "\n".join(linhas)[:2900]


def rodadas_da_escola(cnpj: Any, tickets: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Todas as rodadas da escola (pelo CNPJ), em qualquer canal, da mais recente para a mais antiga."""
    digitos = cnpj_digitos(cnpj)
    if len(digitos) != 14:
        return []
    tickets = tickets if tickets is not None else load_tickets()
    rodadas = [
        t for t in tickets.values()
        if cnpj_digitos((t.get("extra_data") or {}).get("cnpj") or t.get("cnpj")) == digitos
    ]
    return sorted(rodadas, key=lambda t: (float(t.get("thread_ts") or 0), rodada_de(t)), reverse=True)
