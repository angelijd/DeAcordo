import re
import json
from typing import Dict, Any, Optional
from config.exceptions_rules import ALL_EXCEPTIONS_LIST
from config.mock_users import MOCK_CONSULTORES, MOCK_LIDERES, MOCK_APROVADORES
from config.triagem_config import USE_MOCK_USERS
from utils.currency_words import valor_para_extenso, format_real_input

# Lista de opções de Frente
FRENTES_OPTIONS = [
    "(CE) Inbound",
    "(CE) ArcoPlus Novas",
    "(CE) Outbound SAS/SPE",
    "(CE) Outbound COC/GKE",
    "(CE) Outbound SAE/CQT",
    "(CE) KA",
]

# Marcas Oficiais: Core e Plus
MARCAS_CORE = [
    "SAS",
    "SPE (Sistema Positivo de Ensino)",
    "CQT (Conquista)",
    "COC",
    "Geekie",
    "SAE",
]

MARCAS_PLUS = [
    "MARALTO",
    "NAV / Nave à Vela",
    "IS",
    "PES",
    "EI",
    "GF",
]

ALL_MARCAS = MARCAS_CORE + MARCAS_PLUS
MARCAS_OPTIONS = ALL_MARCAS


def formatar_cnpj(cnpj_raw: str) -> str:
    """Aplica a máscara XX.XXX.XXX/XXXX-XX se houver 14 dígitos"""
    if not cnpj_raw:
        return ""
    digitos = re.sub(r"\D", "", str(cnpj_raw))
    if len(digitos) == 14:
        return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"
    return cnpj_raw


def build_aprovacoes_modal(
    current_user_id: str,
    channel_id: str,
    num_exceptions: int = 1,
    is_rede: bool = False,
    is_divida: bool = False,
    saved_values: Optional[Dict[str, Any]] = None,
    cnpj_info: Optional[Dict[str, Any]] = None,
    has_file_input: bool = True,
) -> Dict[str, Any]:
    """
    Constrói o dicionário de blocos da janela modal 'Aprovações Arco'
    com renderização dinâmica imediata para Marcas, Dívida, CNPJ, Inviabilidade e Exceções.
    """
    saved_values = saved_values or {}
    cnpj_info = cnpj_info or {}
    
    # Sincroniza flags com saved_values
    if saved_values.get("rede_grupo") == "sim":
        is_rede = True
    elif saved_values.get("rede_grupo") == "nao":
        is_rede = False

    if saved_values.get("tem_divida") == "sim":
        is_divida = True
    elif saved_values.get("tem_divida") == "nao":
        is_divida = False

    # Metadata para manter o estado entre views.update
    metadata = {
        "channel_id": channel_id,
        "current_user_id": current_user_id,
        "num_exceptions": max(1, min(5, num_exceptions)),
        "is_rede": is_rede,
        "is_divida": is_divida,
        "cnpj_info": cnpj_info,
        "has_file_input": True,
    }

    blocks = []

    # -------------------------------------------------------------
    # 1. Frente (P1) - Obrigatório
    # -------------------------------------------------------------
    frente_options_blocks = [
        {
            "text": {"type": "plain_text", "text": opt},
            "value": opt,
        }
        for opt in FRENTES_OPTIONS
    ]
    initial_frente = saved_values.get("frente")
    frente_element = {
        "type": "static_select",
        "action_id": "frente_select",
        "placeholder": {"type": "plain_text", "text": "Selecionar uma opção"},
        "options": frente_options_blocks,
    }
    if initial_frente:
        frente_element["initial_option"] = {
            "text": {"type": "plain_text", "text": initial_frente},
            "value": initial_frente,
        }
    blocks.append({
        "type": "input",
        "block_id": "frente_block",
        "element": frente_element,
        "label": {"type": "plain_text", "text": "Frente:"},
    })

    # -------------------------------------------------------------
    # 2. Consultor (P2) - Obrigatório (Preenchido com o usuário atual)
    # -------------------------------------------------------------
    initial_consultor = saved_values.get("consultor") or current_user_id
    if USE_MOCK_USERS:
        consultor_options = [
            {"text": {"type": "plain_text", "text": "Meu Usuário Atual (Você)"}, "value": current_user_id}
        ] + [
            {"text": {"type": "plain_text", "text": c["name"]}, "value": c["name"]}
            for c in MOCK_CONSULTORES
        ]
        consultor_element = {
            "type": "static_select",
            "action_id": "consultor_select",
            "placeholder": {"type": "plain_text", "text": "Selecionar consultor"},
            "options": consultor_options,
        }
        for opt in consultor_options:
            if opt["value"] == initial_consultor or (initial_consultor == current_user_id and "Você" in opt["text"]["text"]):
                consultor_element["initial_option"] = opt
                break
    else:
        consultor_element = {
            "type": "users_select",
            "action_id": "consultor_select",
            "placeholder": {"type": "plain_text", "text": "Selecionar um usuário"},
            "initial_user": initial_consultor,
        }

    blocks.append({
        "type": "input",
        "block_id": "consultor_block",
        "element": consultor_element,
        "label": {"type": "plain_text", "text": "Consultor:"},
    })

    # -------------------------------------------------------------
    # 3. Líder direto do Consultor (P3) - Obrigatório
    # -------------------------------------------------------------
    if USE_MOCK_USERS:
        lider_options = [
            {"text": {"type": "plain_text", "text": "Meu Usuário Atual (Você - Para Teste)"}, "value": current_user_id}
        ] + [
            {"text": {"type": "plain_text", "text": l["name"]}, "value": l["name"]}
            for l in MOCK_LIDERES
        ]
        lider_element = {
            "type": "static_select",
            "action_id": "lider_select",
            "placeholder": {"type": "plain_text", "text": "Selecionar líder"},
            "options": lider_options,
        }
        if saved_values.get("lider"):
            for opt in lider_options:
                if opt["value"] == saved_values.get("lider"):
                    lider_element["initial_option"] = opt
                    break
    else:
        lider_element = {
            "type": "users_select",
            "action_id": "lider_select",
            "placeholder": {"type": "plain_text", "text": "Selecionar um usuário"},
        }
        if saved_values.get("lider"):
            lider_element["initial_user"] = saved_values.get("lider")

    blocks.append({
        "type": "input",
        "block_id": "lider_block",
        "element": lider_element,
        "label": {"type": "plain_text", "text": "Líder direto do Consultor:"},
    })

    # -------------------------------------------------------------
    # 4. Marca(s) (P4) - Em Section Accessory para disparo instantâneo
    # -------------------------------------------------------------
    marcas_option_groups = [
        {
            "label": {"type": "plain_text", "text": "Marcas Core"},
            "options": [
                {"text": {"type": "plain_text", "text": m}, "value": m}
                for m in MARCAS_CORE
            ],
        },
        {
            "label": {"type": "plain_text", "text": "Marcas Plus"},
            "options": [
                {"text": {"type": "plain_text", "text": m}, "value": m}
                for m in MARCAS_PLUS
            ],
        },
    ]
    marcas_element = {
        "type": "multi_static_select",
        "action_id": "marcas_select",
        "placeholder": {"type": "plain_text", "text": "Selecione a(s) marca(s)"},
        "option_groups": marcas_option_groups,
        "max_selected_items": 10,
    }
    selected_marcas = saved_values.get("marcas", [])
    if selected_marcas:
        marcas_element["initial_options"] = [
            {"text": {"type": "plain_text", "text": m}, "value": m}
            for m in selected_marcas if m in ALL_MARCAS
        ]
    blocks.append({
        "type": "input",
        "block_id": "marcas_block",
        "dispatch_action": True,
        "element": marcas_element,
        "label": {"type": "plain_text", "text": "Marca(s):"},
        "hint": {"type": "plain_text", "text": "Preencher com a(s) marca(s) para as quais irá solicitar aprovação. Abre as perguntas de inviabilidade."},
    })

    blocks.append({"type": "divider"})

    # -------------------------------------------------------------
    # 5. CNPJ (P5) - Aceita números puros ou com máscara (- / .)
    # -------------------------------------------------------------
    raw_cnpj = saved_values.get("cnpj") or cnpj_info.get("cnpj", "")
    formatted_cnpj = formatar_cnpj(raw_cnpj)
    cnpj_element = {
        "type": "plain_text_input",
        "action_id": "cnpj_input",
        "placeholder": {"type": "plain_text", "text": "Inserir CNPJ (com ou sem pontuação)"},
        "dispatch_action_config": {
            "trigger_actions_on": ["on_character_entered", "on_enter_pressed"]
        },
    }
    if formatted_cnpj:
        cnpj_element["initial_value"] = formatted_cnpj

    digitos_cnpj = re.sub(r"\D", "", str(formatted_cnpj or ""))
    cnpj_key = f"_{abs(hash(formatted_cnpj)) % 100000}" if len(digitos_cnpj) == 14 else ""
    cnpj_block_id = f"cnpj_block{cnpj_key}"
        
    blocks.append({
        "type": "input",
        "block_id": cnpj_block_id,
        "dispatch_action": True,
        "element": cnpj_element,
        "label": {"type": "plain_text", "text": "CNPJ:"},
    })

    # Botão de Ação: Buscar na Receita Federal
    blocks.append({
        "type": "actions",
        "block_id": "btn_cnpj_action_block",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "🔍 Buscar Dados do CNPJ na Receita"},
                "action_id": "btn_buscar_cnpj",
                "style": "primary",
            }
        ],
    })

    # -------------------------------------------------------------
    # 6. Razão Social da Escola (P6)
    # -------------------------------------------------------------
    initial_razao = (saved_values.get("razao_social") or cnpj_info.get("razao_social", "") or "").strip()
    razao_key = f"_{abs(hash(initial_razao)) % 100000}" if initial_razao else ""
    razao_block_id = f"razao_social_block{razao_key}"
    razao_action_id = f"razao_social_input{razao_key}"

    razao_element = {
        "type": "plain_text_input",
        "action_id": razao_action_id,
    }
    if initial_razao:
        razao_element["initial_value"] = initial_razao

    razao_hint_text = "Preencher com o Razão Social da escola."
    if cnpj_info.get("sucesso"):
        tipo_str = cnpj_info.get('tipo') or 'MATRIZ'
        detalhes = f"✅ Encontrado: {cnpj_info.get('municipio')}/{cnpj_info.get('uf')} | {tipo_str} | Status: {cnpj_info.get('situacao', 'ATIVA')}"
        razao_hint_text = detalhes

    blocks.append({
        "type": "input",
        "block_id": razao_block_id,
        "element": razao_element,
        "label": {"type": "plain_text", "text": "Razão Social da Escola:"},
        "hint": {"type": "plain_text", "text": razao_hint_text},
    })

    # -------------------------------------------------------------
    # 7. Faz parte de Rede/Grupo? (P7) - Input com dispatch_action
    # -------------------------------------------------------------
    rede_options = [
        {"text": {"type": "plain_text", "text": "Não"}, "value": "nao"},
        {"text": {"type": "plain_text", "text": "Sim"}, "value": "sim"},
    ]
    rede_element = {
        "type": "static_select",
        "action_id": "rede_grupo_select",
        "placeholder": {"type": "plain_text", "text": "Selecionar uma opção"},
        "options": rede_options,
    }
    if saved_values.get("rede_grupo"):
        for opt in rede_options:
            if opt["value"] == saved_values.get("rede_grupo"):
                rede_element["initial_option"] = opt
                break
    elif is_rede:
        rede_element["initial_option"] = {"text": {"type": "plain_text", "text": "Sim"}, "value": "sim"}

    blocks.append({
        "type": "input",
        "block_id": "rede_grupo_block",
        "dispatch_action": True,
        "element": rede_element,
        "label": {"type": "plain_text", "text": "Faz parte de Rede/Grupo?"},
    })

    # Se for rede, exibe P7.1 e P7.2 dinamicamente
    if is_rede:
        nome_rede_elem = {
            "type": "plain_text_input",
            "action_id": "nome_rede_input",
            "placeholder": {"type": "plain_text", "text": "Escreva o nome"},
        }
        if saved_values.get("nome_rede"):
            nome_rede_elem["initial_value"] = saved_values.get("nome_rede")
        blocks.append({
            "type": "input",
            "block_id": "nome_rede_block",
            "optional": True,
            "element": nome_rede_elem,
            "label": {"type": "plain_text", "text": "Nome da Rede/Grupo:"},
        })

        cnpjs_rede_elem = {
            "type": "plain_text_input",
            "action_id": "cnpjs_rede_input",
            "multiline": True,
            "placeholder": {"type": "plain_text", "text": "Escreva algo"},
        }
        if saved_values.get("cnpjs_rede"):
            cnpjs_rede_elem["initial_value"] = saved_values.get("cnpjs_rede")
        blocks.append({
            "type": "input",
            "block_id": "cnpjs_rede_block",
            "optional": True,
            "element": cnpjs_rede_elem,
            "label": {"type": "plain_text", "text": "CNPJ de todas as unidades da rede (caso rede):"},
        })

    # -------------------------------------------------------------
    # 8. INEP (P8) - Numérico, Opcional, Sem hint
    # -------------------------------------------------------------
    initial_inep = str(saved_values.get("inep") or "").strip()
    inep_key = f"_{abs(hash(initial_inep)) % 100000}" if initial_inep else ""
    inep_block_id = f"inep_block{inep_key}"
    inep_action_id = f"inep_input{inep_key}"

    inep_elem = {
        "type": "number_input",
        "is_decimal_allowed": False,
        "action_id": inep_action_id,
        "placeholder": {"type": "plain_text", "text": "Código INEP"},
    }
    if initial_inep:
        digitos_inep = re.sub(r"\D", "", initial_inep)
        if digitos_inep:
            inep_elem["initial_value"] = digitos_inep

    blocks.append({
        "type": "input",
        "block_id": inep_block_id,
        "optional": True,
        "element": inep_elem,
        "label": {"type": "plain_text", "text": "INEP:"},
    })

    # -------------------------------------------------------------
    # 9. Alunado Total (P9) - Numérico Inteiro, Opcional
    # -------------------------------------------------------------
    alunado_elem = {
        "type": "number_input",
        "is_decimal_allowed": False,
        "action_id": "alunado_input",
        "placeholder": {"type": "plain_text", "text": "Inserir um número"},
    }
    if saved_values.get("alunado") is not None:
        alunado_elem["initial_value"] = str(saved_values.get("alunado"))
    blocks.append({
        "type": "input",
        "block_id": "alunado_block",
        "optional": True,
        "element": alunado_elem,
        "label": {"type": "plain_text", "text": "Alunado Total:"},
    })

    # -------------------------------------------------------------
    # 10. Valor do Contrato ACV (P10) - Com Destaque de Extenso Imediato
    # -------------------------------------------------------------
    raw_acv = saved_values.get("acv", "")
    acv_elem = {
        "type": "plain_text_input",
        "action_id": "acv_input",
        "placeholder": {"type": "plain_text", "text": "Ex: 10000 ou 10.000,00"},
        "dispatch_action_config": {
            "trigger_actions_on": ["on_character_entered", "on_enter_pressed"]
        },
    }
    if raw_acv:
        acv_elem["initial_value"] = str(raw_acv)

    extenso_acv = valor_para_extenso(raw_acv)
    formatted_display = format_real_input(raw_acv)

    blocks.append({
        "type": "input",
        "block_id": "acv_block",
        "dispatch_action": True,
        "element": acv_elem,
        "label": {"type": "plain_text", "text": "Valor do Contrato (ACV):"},
    })

    # Exibe banner destacado com o valor por extenso
    if extenso_acv and formatted_display:
        blocks.append({
            "type": "context",
            "block_id": "acv_extenso_context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"💵 *Valor do contrato:* *{extenso_acv}* (R$ {formatted_display})",
                }
            ],
        })
    else:
        blocks.append({
            "type": "context",
            "block_id": "acv_extenso_context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "💡 *Dica:* Digite o valor em números (ex: `10000` ou `10.000,00` ou `100k`). O sistema valida o extenso em tempo real para evitar erros.",
                }
            ],
        })

    # -------------------------------------------------------------
    # 11. A escola possui Dívida? (P11) - Input com dispatch_action para disparo instantâneo
    # -------------------------------------------------------------
    divida_select_options = [
        {"text": {"type": "plain_text", "text": "Não"}, "value": "nao"},
        {"text": {"type": "plain_text", "text": "Sim"}, "value": "sim"},
    ]
    divida_select_elem = {
        "type": "static_select",
        "action_id": "tem_divida_select",
        "placeholder": {"type": "plain_text", "text": "Selecionar uma opção"},
        "options": divida_select_options,
    }
    if saved_values.get("tem_divida"):
        for opt in divida_select_options:
            if opt["value"] == saved_values.get("tem_divida"):
                divida_select_elem["initial_option"] = opt
                break
    elif is_divida:
        divida_select_elem["initial_option"] = {"text": {"type": "plain_text", "text": "Sim"}, "value": "sim"}

    blocks.append({
        "type": "input",
        "block_id": "tem_divida_block",
        "dispatch_action": True,
        "element": divida_select_elem,
        "label": {"type": "plain_text", "text": "A escola possui Dívida?"},
    })

    # Se a escola tiver dívida, exibe campo obrigatório de Valor da Dívida com formatação automática
    if is_divida:
        raw_divida = saved_values.get("valor_divida") or saved_values.get("divida") or ""
        divida_val_elem = {
            "type": "plain_text_input",
            "action_id": "valor_divida_input",
            "placeholder": {"type": "plain_text", "text": "Ex: 50000 ou 50.000,00"},
            "dispatch_action_config": {
                "trigger_actions_on": ["on_character_entered", "on_enter_pressed"]
            },
        }
        if raw_divida:
            divida_val_elem["initial_value"] = str(raw_divida)

        extenso_divida = valor_para_extenso(raw_divida)
        formatted_divida_display = format_real_input(raw_divida)

        blocks.append({
            "type": "input",
            "block_id": "valor_divida_block",
            "dispatch_action": True,
            "element": divida_val_elem,
            "label": {"type": "plain_text", "text": "Valor da Dívida:"},
        })

        if extenso_divida and formatted_divida_display:
            blocks.append({
                "type": "context",
                "block_id": "divida_extenso_context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"💵 *Dívida confirmada:* *{extenso_divida}* (R$ {formatted_divida_display})",
                    }
                ],
            })

    # -------------------------------------------------------------
    # 12. Link Oportunidade SalesForce (P12) - Obrigatório
    # -------------------------------------------------------------
    sf_elem = {
        "type": "url_text_input",
        "action_id": "link_sf_input",
        "placeholder": {"type": "plain_text", "text": "https://..."},
    }
    if saved_values.get("link_sf"):
        sf_elem["initial_value"] = saved_values.get("link_sf")
    blocks.append({
        "type": "input",
        "block_id": "link_sf_block",
        "element": sf_elem,
        "label": {"type": "plain_text", "text": "Link Oportunidade SalesForce:"},
    })

    blocks.append({"type": "divider"})

    # -------------------------------------------------------------
    # 14. Inviabilidade personalizada por marca (P14)
    # -------------------------------------------------------------
    inviabilidades_salvas = saved_values.get("inviabilidades", {})
    if selected_marcas:
        for m in selected_marcas:
            slug = re.sub(r"[^a-zA-Z0-9_]", "_", m.lower())
            val_salvo = inviabilidades_salvas.get(m) or saved_values.get(f"inviab_{slug}") or ""
            inviab_elem = {
                "type": "number_input",
                "is_decimal_allowed": True,
                "action_id": f"inviab_input_{slug}",
                "placeholder": {"type": "plain_text", "text": "Ex: 10"},
            }
            if val_salvo is not None and str(val_salvo) != "":
                limpo_num = str(val_salvo).replace("%", "").strip()
                inviab_elem["initial_value"] = limpo_num

            blocks.append({
                "type": "input",
                "block_id": f"inviab_block_{slug}",
                "element": inviab_elem,
                "label": {"type": "plain_text", "text": f"[{m}] Qual % de inviabilidade?"},
                "hint": {"type": "plain_text", "text": "Inviabilidade conforme Alçada do Simulador"},
            })
    else:
        blocks.append({
            "type": "context",
            "block_id": "inviab_aviso_sem_marcas_block",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "ℹ️ *Inviabilidade:* Selecione a(s) marca(s) acima para preencher o percentual de cada uma.",
                }
            ],
        })

    # -------------------------------------------------------------
    # 15. Contexto Geral da Escola/Negociação (P15)
    # -------------------------------------------------------------
    ctx_elem = {
        "type": "plain_text_input",
        "action_id": "contexto_geral_input",
        "multiline": True,
        "placeholder": {"type": "plain_text", "text": "Dê detalhes suficientes para a tomada de decisão"},
    }
    if saved_values.get("contexto_geral"):
        ctx_elem["initial_value"] = saved_values.get("contexto_geral")
    blocks.append({
        "type": "input",
        "block_id": "contexto_geral_block",
        "element": ctx_elem,
        "label": {"type": "plain_text", "text": "Contexto Geral da Escola/Negociação:"},
    })

    blocks.append({"type": "divider"})

    # -------------------------------------------------------------
    # 16 e 17. Exceções Dinâmicas (1 até 5)
    # -------------------------------------------------------------
    exc_options = [
        {"text": {"type": "plain_text", "text": exc[:75]}, "value": exc}
        for exc in ALL_EXCEPTIONS_LIST
    ]

    for i in range(1, num_exceptions + 1):
        exc_key = f"excecao_{i}"
        ctx_key = f"contexto_excecao_{i}"
        
        selected_exc = saved_values.get(exc_key)
        exc_select_elem = {
            "type": "static_select",
            "action_id": f"excecao_{i}_select",
            "placeholder": {"type": "plain_text", "text": "Selecionar uma opção"},
            "options": exc_options,
        }
        if selected_exc:
            exc_select_elem["initial_option"] = {
                "text": {"type": "plain_text", "text": selected_exc[:75]},
                "value": selected_exc,
            }

        exc_block = {
            "type": "input",
            "block_id": f"excecao_{i}_block",
            "optional": i > 1,
            "element": exc_select_elem,
            "label": {"type": "plain_text", "text": f"Exceção {i}:"},
        }
        if i == 5:
            exc_block["hint"] = {"type": "plain_text", "text": "Para mais aprovações, utilizar o botão 'Mais Aprovações' após enviar esta mensagem."}
        blocks.append(exc_block)

        ctx_exc_elem = {
            "type": "plain_text_input",
            "action_id": f"contexto_excecao_{i}_input",
            "multiline": True,
            "placeholder": {"type": "plain_text", "text": "Dê detalhes suficientes para a tomada de decisão"},
        }
        if saved_values.get(ctx_key):
            ctx_exc_elem["initial_value"] = saved_values.get(ctx_key)

        ctx_block = {
            "type": "input",
            "block_id": f"contexto_excecao_{i}_block",
            "optional": True,
            "element": ctx_exc_elem,
            "label": {"type": "plain_text", "text": f"Contexto Exceção {i}: (dê detalhes)"},
        }
        if i == 5:
            ctx_block["hint"] = {"type": "plain_text", "text": "Para mais aprovações utilizar o botão 'Mais Aprovações' no fluxo."}
        blocks.append(ctx_block)

    # Botão dinâmico: Adicionar outra exceção
    if num_exceptions < 5:
        blocks.append({
            "type": "actions",
            "block_id": "btn_add_exception_block",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": f"➕ Adicionar Exceção {num_exceptions + 1}"},
                    "action_id": "btn_add_exception",
                }
            ],
        })

    blocks.append({"type": "divider"})

    # -------------------------------------------------------------
    # 18. Simulador Obrigatório em XLSX (Botão Nativo de Upload)
    # -------------------------------------------------------------
    blocks.append({
        "type": "input",
        "block_id": "simulador_block",
        "optional": False,
        "element": {
            "type": "file_input",
            "action_id": "simulador_file_input",
            "filetypes": ["xlsx"],
            "max_files": 1,
        },
        "label": {"type": "plain_text", "text": "📁 Simulador (Upload do Arquivo):"},
        "hint": {"type": "plain_text", "text": "Baixe o simulador em XLSX e clique no botão 'Choose files' para anexá-lo aqui."},
    })

    return {
        "type": "modal",
        "callback_id": "modal_aprovacoes_arco",
        "title": {"type": "plain_text", "text": "Aprovações Arco"},
        "submit": {"type": "plain_text", "text": "Enviar"},
        "close": {"type": "plain_text", "text": "Fechar"},
        "private_metadata": json.dumps(metadata),
        "blocks": blocks,
    }


def extract_modal_values(view_state: Dict[str, Any], num_exceptions: int) -> Dict[str, Any]:
    """
    Extrai de forma segura todos os valores preenchidos no estado do modal.
    """
    values = view_state.get("values", {})
    res = {}

    def get_val(block_id: str, action_id: str):
        b = values.get(block_id, {})
        a = b.get(action_id, {})
        return a.get("value")

    def get_selected(block_id: str, action_id: str):
        b = values.get(block_id, {})
        a = b.get(action_id, {})
        sel = a.get("selected_option")
        return sel.get("value") if sel else None

    def get_user(block_id: str, action_id: str):
        b = values.get(block_id, {})
        a = b.get(action_id, {})
        return a.get("selected_user")

    def get_multi_static(block_id: str, action_id: str):
        b = values.get(block_id, {})
        a = b.get(action_id, {})
        opts = a.get("selected_options", [])
        return [o.get("value") for o in opts if o.get("value")]

    def get_val_by_prefix(prefix: str):
        for b_id, b_val in values.items():
            if b_id.startswith(prefix):
                for a_id, a_val in b_val.items():
                    if a_val.get("value") is not None:
                        return a_val.get("value")
        return None

    def get_selected_by_prefix(prefix: str):
        for b_id, b_val in values.items():
            if b_id.startswith(prefix):
                for a_id, a_val in b_val.items():
                    sel = a_val.get("selected_option")
                    if sel and sel.get("value"):
                        return sel.get("value")
        return None

    res["frente"] = get_selected("frente_block", "frente_select")
    res["consultor"] = get_user("consultor_block", "consultor_select") or get_selected("consultor_block", "consultor_select")
    res["lider"] = get_user("lider_block", "lider_select") or get_selected("lider_block", "lider_select")
    res["marcas"] = get_multi_static("marcas_block", "marcas_select")
    res["cnpj"] = get_val_by_prefix("cnpj_block") or get_val("cnpj_block", "cnpj_input")
    res["razao_social"] = get_val_by_prefix("razao_social_block")
    res["rede_grupo"] = get_selected("rede_grupo_block", "rede_grupo_select")
    res["nome_rede"] = get_val("nome_rede_block", "nome_rede_input")
    res["cnpjs_rede"] = get_val("cnpjs_rede_block", "cnpjs_rede_input")
    res["inep"] = get_val_by_prefix("inep_block")
    res["alunado"] = get_val("alunado_block", "alunado_input")
    raw_acv_val = get_val_by_prefix("acv_block") or get_val("acv_block", "acv_input")
    res["acv"] = raw_acv_val if raw_acv_val is not None else ""
    res["tem_divida"] = get_selected("tem_divida_block", "tem_divida_select")
    raw_div_val = get_val_by_prefix("valor_divida_block") or get_val("valor_divida_block", "valor_divida_input")
    res["valor_divida"] = raw_div_val if raw_div_val is not None else ""
    res["link_sf"] = get_val("link_sf_block", "link_sf_input")

    # Inviabilidade personalizada por marca
    inviabilidades = {}
    for b_id, b_val in values.items():
        if b_id.startswith("inviab_block_"):
            slug = b_id.replace("inviab_block_", "")
            for a_id, a_val in b_val.items():
                val = a_val.get("value")
                if val is not None:
                    marca_nome = slug
                    for m in ALL_MARCAS:
                        if re.sub(r"[^a-zA-Z0-9_]", "_", m.lower()) == slug:
                            marca_nome = m
                            break
                    inviabilidades[marca_nome] = val
                    res[f"inviab_{slug}"] = val

    res["inviabilidades"] = inviabilidades
    res["contexto_geral"] = get_val("contexto_geral_block", "contexto_geral_input")

    # Exceções dinâmicas
    for i in range(1, num_exceptions + 1):
        res[f"excecao_{i}"] = get_selected(f"excecao_{i}_block", f"excecao_{i}_select")
        res[f"contexto_excecao_{i}"] = get_val(f"contexto_excecao_{i}_block", f"contexto_excecao_{i}_input")

    # Simulador XLSX
    sim_data = values.get("simulador_block", {}).get("simulador_file_input", {})
    res["simulador_files"] = sim_data.get("files", [])
    res["simulador_fallback"] = values.get("simulador_block", {}).get("simulador_fallback_input", {}).get("value")

    return res


def build_reprovar_modal(
    ticket_key: str,
    approval_key: str,
    role_title: str,
    escola: str,
    consultor_id: str,
    consultor_name: str,
    channel_id: str,
    is_from_dm: bool = False,
    dm_message_ts: Optional[str] = None,
    dm_channel_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Constrói o modal oficial de Reprovação de Solicitação com seleção de motivos padronizados.
    Motivos:
    a. Negociação caiu
    b. Precisa de mais informações
    c. Outros + campo de texto obrigatório
    """
    metadata = {
        "ticket_key": ticket_key,
        "approval_key": approval_key,
        "role_title": role_title,
        "escola": escola,
        "consultor_id": consultor_id,
        "consultor_name": consultor_name,
        "channel_id": channel_id,
        "is_from_dm": is_from_dm,
        "dm_message_ts": dm_message_ts,
        "dm_channel_id": dm_channel_id,
    }

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"⚠️ *Atenção:* Você está prestes a *reprovar* a solicitação para *{escola}*.\n"
                    f"• *Alçada em deliberação:* {role_title}\n"
                    f"• *Consultor Responsável:* {consultor_name}\n\n"
                    f"O consultor será marcado na thread pública informando a reprovação e o motivo selecionado."
                )
            }
        },
        {"type": "divider"},
        {
            "type": "input",
            "block_id": "motivo_reprovacao_block",
            "element": {
                "type": "static_select",
                "action_id": "motivo_reprovacao_select",
                "placeholder": {"type": "plain_text", "text": "Selecione o motivo da reprovação"},
                "options": [
                    {
                        "text": {"type": "plain_text", "text": "a. Negociação caiu"},
                        "value": "negociacao_caiu"
                    },
                    {
                        "text": {"type": "plain_text", "text": "b. Precisa de mais informações"},
                        "value": "precisa_mais_informacoes"
                    },
                    {
                        "text": {"type": "plain_text", "text": "c. Outros (especificar abaixo)"},
                        "value": "outros"
                    }
                ]
            },
            "label": {"type": "plain_text", "text": "Motivo da Reprovação:"}
        },
        {
            "type": "input",
            "block_id": "detalhes_reprovacao_block",
            "element": {
                "type": "plain_text_input",
                "action_id": "detalhes_reprovacao_input",
                "multiline": True,
                "placeholder": {"type": "plain_text", "text": "Descreva os motivos ou quais informações faltaram para o consultor..."}
            },
            "label": {"type": "plain_text", "text": "Justificativa / Detalhes da Decisão:"},
            "hint": {"type": "plain_text", "text": "Campo obrigatório para qualquer justificativa."}
        }
    ]

    return {
        "type": "modal",
        "callback_id": "modal_reprovar_ticket",
        "title": {"type": "plain_text", "text": "Reprovar Solicitação"},
        "submit": {"type": "plain_text", "text": "Confirmar Reprovação"},
        "close": {"type": "plain_text", "text": "Cancelar"},
        "private_metadata": json.dumps(metadata),
        "blocks": blocks,
    }


def build_triagem_substituicao_modal(
    ticket: Dict[str, Any],
    current_user_id: str,
    channel_id: str,
) -> Dict[str, Any]:
    """
    Constrói o modal administrativo da @triagem para trocar aprovadores por ausência temporária com período de vigência.
    """
    from datetime import datetime, timedelta

    ticket_key = ticket["key"]
    escola = ticket["escola"]
    approvals = ticket.get("approvals", {})

    # Filtra apenas alçadas pendentes
    pending_options = []
    for k, a in approvals.items():
        if a.get("status") == "pending":
            sub_info = f" [Substituto: @{a['approver_name']}]" if a.get("is_substituted") else ""
            pending_options.append({
                "text": {"type": "plain_text", "text": f"{a['short_label']} (@{a['approver_name']}){sub_info}"[:75]},
                "value": k
            })

    if not pending_options:
        pending_options.append({
            "text": {"type": "plain_text", "text": "Nenhuma alçada pendente"},
            "value": "none"
        })

    # Opções de aprovador substituto
    if USE_MOCK_USERS:
        substitute_options = [
            {"text": {"type": "plain_text", "text": "Meu Usuário Atual (Você - Para Teste)"}, "value": current_user_id}
        ] + [
            {"text": {"type": "plain_text", "text": ap["name"][:75]}, "value": ap["id"]}
            for ap in MOCK_APROVADORES
        ]
        substitute_element = {
            "type": "static_select",
            "action_id": "novo_aprovador_select",
            "placeholder": {"type": "plain_text", "text": "Selecione o aprovador substituto"},
            "options": substitute_options,
        }
    else:
        substitute_element = {
            "type": "users_select",
            "action_id": "novo_aprovador_select",
            "placeholder": {"type": "plain_text", "text": "Selecione o usuário substituto"},
        }

    # Data inicial padrão: hoje + 7 dias
    default_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    metadata = {
        "ticket_key": ticket_key,
        "channel_id": channel_id,
        "current_user_id": current_user_id,
        "escola": escola,
    }

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"🔄 *Substituição de Aprovador por Ausência (@triagem)*\n"
                    f"• *Escola:* {escola}\n"
                    f"• *Ticket:* `{ticket_key}`\n\n"
                    f"Selecione a alçada que necessita de cobertura temporária e indique quem assumirá a deliberação até a data limite estipulada."
                )
            }
        },
        {"type": "divider"},
        {
            "type": "input",
            "block_id": "alcada_substituicao_block",
            "element": {
                "type": "static_select",
                "action_id": "alcada_substituicao_select",
                "placeholder": {"type": "plain_text", "text": "Selecione a alçada a substituir"},
                "options": pending_options,
                **({"initial_option": pending_options[0]} if pending_options and pending_options[0]["value"] != "none" else {})
            },
            "label": {"type": "plain_text", "text": "Qual alçada será substituída?"}
        },
        {
            "type": "input",
            "block_id": "novo_aprovador_block",
            "element": substitute_element,
            "label": {"type": "plain_text", "text": "Novo Aprovador Substituto:"},
            "hint": {"type": "plain_text", "text": "Esta pessoa receberá o card de aprovação na DM e terá permissão para aprovar o item."}
        },
        {
            "type": "input",
            "block_id": "data_limite_block",
            "element": {
                "type": "datepicker",
                "action_id": "data_limite_datepicker",
                "initial_date": default_date,
                "placeholder": {"type": "plain_text", "text": "Selecione a data"}
            },
            "label": {"type": "plain_text", "text": "Substituto ativo até o dia (inclusive):"},
            "hint": {"type": "plain_text", "text": "A partir do dia seguinte a esta data, a alçada volta a ser do titular original."}
        },
        {
            "type": "input",
            "block_id": "motivo_ausencia_block",
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": "motivo_ausencia_input",
                "placeholder": {"type": "plain_text", "text": "Ex.: Férias até 25/09, Licença médica, Viagem a trabalho..."}
            },
            "label": {"type": "plain_text", "text": "Motivo da Ausência:"}
        }
    ]

    return {
        "type": "modal",
        "callback_id": "modal_triagem_substituicao",
        "title": {"type": "plain_text", "text": "Substituir Aprovador"},
        "submit": {"type": "plain_text", "text": "Confirmar Substituição"},
        "close": {"type": "plain_text", "text": "Cancelar"},
        "private_metadata": json.dumps(metadata),
        "blocks": blocks,
    }
