import os
import re
import json
import logging
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config.approvers_map import format_user_mention
from config.exceptions_rules import EXCEPTIONS_RULES
from config.triagem_config import is_user_triagem
from services.receita_service import consultar_cnpj
from services.inep_service import buscar_inep
from services.ticket_service import (
    create_ticket,
    get_ticket,
    approve_step,
    reject_step,
    substitute_approver,
    build_thread_blocks,
    build_main_post_blocks,
    update_ticket_card_ts,
    executar_cobranca_pendencias,
    cobrar_pendencias_de_ticket,
    get_pending_tickets,
)
from services.dm_approval_service import send_dm_approval_cards, send_dm_substitute_card
from services.consultor_feedback_service import send_consultor_progress_dm, send_consultor_rejection_dm
from services.substitution_service import registrar_substituicao, get_active_substitute
from views.modals import (
    build_aprovacoes_modal,
    extract_modal_values,
    build_reprovar_modal,
    build_triagem_substituicao_modal,
    MARCAS_CORE,
    MARCAS_PLUS,
)
from utils.currency_words import format_real_input, parse_currency_str, valor_para_extenso

# Configura logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("slack_bot")

# Carrega variáveis de ambiente
load_dotenv()

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
DEFAULT_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")

if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
    raise ValueError("SLACK_BOT_TOKEN e SLACK_APP_TOKEN devem estar configurados no arquivo .env!")

app = App(token=SLACK_BOT_TOKEN)


def format_mention(user_or_name: str) -> str:
    """Formata menção para Slack ID (<@USER_ID>) ou nome legível (@Nome)."""
    if not user_or_name:
        return "-"
    if user_or_name.startswith("U") or user_or_name.startswith("W"):
        return f"<@{user_or_name}>"
    if user_or_name.startswith("@"):
        return user_or_name
    return f"@{user_or_name}"


_HAS_FILES_READ = None

def check_files_read_scope(client) -> bool:
    """Verifica de forma segura e cacheada se o bot token tem o escopo files:read"""
    global _HAS_FILES_READ
    if _HAS_FILES_READ is not None:
        return _HAS_FILES_READ
    try:
        resp = client.auth_test()
        scopes = resp.headers.get("x-oauth-scopes", "")
        _HAS_FILES_READ = "files:read" in scopes
        logger.info(f"Escopos OAuth detectados: files:read={_HAS_FILES_READ}")
    except Exception as e:
        logger.warning(f"Erro ao verificar escopos: {e}")
        _HAS_FILES_READ = False
    return _HAS_FILES_READ


def safe_views_open(client, trigger_id: str, modal: dict):
    """Abre o modal diretamente"""
    try:
        client.views_open(trigger_id=trigger_id, view=modal)
    except Exception as e:
        logger.error(f"Erro ao abrir modal views.open: {e}")
        raise e


def safe_views_update(client, view_id: str, modal: dict):
    """Atualiza o modal tratando graciosamente"""
    try:
        client.views_update(view_id=view_id, view=modal)
    except Exception as e:
        logger.error(f"Erro no views.update: {e}")
        raise e


def check_approval_authorization(apprv: dict, user_id: str) -> tuple[bool, bool]:
    """
    Verifica se `user_id` pode aprovar/reprovar a alçada `apprv`.
    Nega por padrão quando não há approver_id real do Slack mapeado, em vez de liberar
    para qualquer pessoa - evita bypass de governança enquanto approvers_map.py não
    estiver com os IDs reais preenchidos.
    Retorna (is_authorized, is_unmapped).
    """
    expected_approver_id = apprv.get("approver_id") or ""
    allow_self = os.environ.get("TEST_ALLOW_SELF_APPROVAL", "false").lower() == "true"

    if expected_approver_id and expected_approver_id.startswith(("U", "W")):
        return (user_id == expected_approver_id or allow_self, False)

    return (allow_self, True)


# =========================================================================
# 1. GATILHOS PARA ABRIR O FORMULÁRIO (Comandos, Atalhos e Botões)
# =========================================================================

@app.command("/solicitacao")
@app.command("/aprovacoes")
def handle_slash_command(ack, body, client):
    """Abre o modal quando o usuário digita /solicitacao ou /aprovacoes"""
    ack()
    trigger_id = body["trigger_id"]
    channel_id = body.get("channel_id") or DEFAULT_CHANNEL_ID
    current_user_id = body["user_id"]

    has_files_scope = check_files_read_scope(client)
    modal = build_aprovacoes_modal(
        current_user_id=current_user_id,
        channel_id=channel_id,
        num_exceptions=1,
        is_rede=False,
        is_divida=False,
        has_file_input=has_files_scope,
    )
    safe_views_open(client, trigger_id, modal)


@app.shortcut("abrir_formulario_aprovacoes")
def handle_global_shortcut(ack, body, client):
    """Abre o modal a partir do menu global de atalhos do Slack"""
    ack()
    trigger_id = body["trigger_id"]
    channel_id = DEFAULT_CHANNEL_ID
    current_user_id = body["user"]["id"]

    has_files_scope = check_files_read_scope(client)
    modal = build_aprovacoes_modal(
        current_user_id=current_user_id,
        channel_id=channel_id,
        num_exceptions=1,
        is_rede=False,
        is_divida=False,
        has_file_input=has_files_scope,
    )
    safe_views_open(client, trigger_id, modal)


@app.action("btn_abrir_modal_aprovacao")
@app.action("btn_abrir_solicitacao")
def handle_channel_button(ack, body, client):
    """Abre o modal ao clicar no botão fixado no topo do canal"""
    ack()
    trigger_id = body["trigger_id"]
    channel_id = body.get("channel", {}).get("id") or DEFAULT_CHANNEL_ID
    current_user_id = body["user"]["id"]

    has_files_scope = check_files_read_scope(client)
    modal = build_aprovacoes_modal(
        current_user_id=current_user_id,
        channel_id=channel_id,
        num_exceptions=1,
        is_rede=False,
        is_divida=False,
        has_file_input=has_files_scope,
    )
    safe_views_open(client, trigger_id, modal)


@app.command("/postar-botao-aprovacoes")
def handle_post_button_command(ack, body, client):
    """Comando administrativo para postar o card fixo com o botão no canal"""
    ack()
    channel_id = body["channel_id"]

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🚀 Central de Aprovações Comerciais - Ciclo CE 2027",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "Olá, equipe comercial!\n\n"
                    "Para submeter uma nova solicitação de aprovação ou exceção comercial, "
                    "clique no botão abaixo para abrir o formulário interativo oficial."
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "📝 Nova Solicitação de Aprovação",
                        "emoji": True,
                    },
                    "action_id": "btn_abrir_modal_aprovacao",
                    "style": "primary",
                }
            ],
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "💡 *Acesso Rápido:* Submissão 100% via formulário interativo, sem necessidade de digitação no canal.",
                }
            ],
        },
    ]

    client.chat_postMessage(
        channel=channel_id,
        text="Central de Aprovações Comerciais - Ciclo CE 2027",
        blocks=blocks,
    )


# =========================================================================
# 2. EVENTOS INTERATIVOS NO FORMULÁRIO (Dívida, CNPJ, Rede, Marcas, Extenso)
# =========================================================================

@app.action("tem_divida_select")
def handle_tem_divida_select(ack, body, client):
    """Atualiza o modal quando o usuário marca se a escola tem dívida ou não"""
    ack()
    view = body["view"]
    view_id = view["id"]
    metadata = json.loads(view.get("private_metadata", "{}"))

    num_exceptions = metadata.get("num_exceptions", 1)
    is_rede = metadata.get("is_rede", False)
    current_user_id = metadata.get("current_user_id")
    channel_id = metadata.get("channel_id")
    cnpj_info = metadata.get("cnpj_info", {})
    has_file_input = metadata.get("has_file_input", True)

    saved_values = extract_modal_values(view["state"], num_exceptions)
    selected_opt = body.get("actions", [{}])[0].get("selected_option")
    val = selected_opt.get("value") if selected_opt else "nao"
    is_divida = (val == "sim")
    saved_values["tem_divida"] = val
    logger.info(f"🔔 [ACTION: tem_divida_select] Opção selecionada: '{val}' -> is_divida={is_divida}")

    updated_modal = build_aprovacoes_modal(
        current_user_id=current_user_id,
        channel_id=channel_id,
        num_exceptions=num_exceptions,
        is_rede=is_rede,
        is_divida=is_divida,
        saved_values=saved_values,
        cnpj_info=cnpj_info,
        has_file_input=has_file_input,
    )
    safe_views_update(client, view_id, updated_modal)


@app.action("rede_grupo_select")
def handle_rede_select(ack, body, client):
    """Atualiza o modal dinamicamente quando o usuário seleciona se é Rede/Grupo"""
    ack()
    view = body["view"]
    view_id = view["id"]
    metadata = json.loads(view.get("private_metadata", "{}"))

    num_exceptions = metadata.get("num_exceptions", 1)
    is_divida = metadata.get("is_divida", False)
    current_user_id = metadata.get("current_user_id")
    channel_id = metadata.get("channel_id")
    cnpj_info = metadata.get("cnpj_info", {})
    has_file_input = metadata.get("has_file_input", True)

    saved_values = extract_modal_values(view["state"], num_exceptions)
    selected_opt = body.get("actions", [{}])[0].get("selected_option")
    val = selected_opt.get("value") if selected_opt else "nao"
    is_rede = (val == "sim")
    saved_values["rede_grupo"] = val
    logger.info(f"🔔 [ACTION: rede_grupo_select] Opção selecionada: '{val}' -> is_rede={is_rede}")

    updated_modal = build_aprovacoes_modal(
        current_user_id=current_user_id,
        channel_id=channel_id,
        num_exceptions=num_exceptions,
        is_rede=is_rede,
        is_divida=is_divida,
        saved_values=saved_values,
        cnpj_info=cnpj_info,
        has_file_input=has_file_input,
    )
    safe_views_update(client, view_id, updated_modal)


@app.action("cnpj_input")
def handle_cnpj_input(ack, body, client):
    """Busca automática de dados na Receita e INEP ao completar 14 dígitos ou dar Enter"""
    ack()
    view = body["view"]
    view_id = view["id"]
    metadata = json.loads(view.get("private_metadata", "{}"))

    raw_val = body.get("actions", [{}])[0].get("value", "")
    digitos = re.sub(r"\D", "", raw_val)

    # Se ainda tiver menos de 14 dígitos e não foi Enter, apenas retorna sem re-renderizar para manter fluidez
    action_type = body.get("actions", [{}])[0].get("type")
    if len(digitos) < 14 and action_type != "enter_pressed":
        return

    num_exceptions = metadata.get("num_exceptions", 1)
    is_rede = metadata.get("is_rede", False)
    is_divida = metadata.get("is_divida", False)
    current_user_id = metadata.get("current_user_id")
    channel_id = metadata.get("channel_id")
    cnpj_info = metadata.get("cnpj_info", {})
    has_file_input = metadata.get("has_file_input", True)

    saved_values = extract_modal_values(view["state"], num_exceptions)
    saved_values["cnpj"] = digitos

    # Dispara consulta automática se tiver 14 dígitos e for diferente do último pesquisado
    if len(digitos) == 14 and digitos != cnpj_info.get("cnpj"):
        info = consultar_cnpj(digitos)
        if info.get("sucesso"):
            cnpj_info = info
            saved_values["razao_social"] = info.get("razao_social", "")
            inep_res = buscar_inep(info.get("nome_fantasia", ""), info.get("razao_social", ""))
            if inep_res and inep_res.get("codigo_inep"):
                saved_values["inep"] = inep_res["codigo_inep"]

    updated_modal = build_aprovacoes_modal(
        current_user_id=current_user_id,
        channel_id=channel_id,
        num_exceptions=num_exceptions,
        is_rede=is_rede,
        is_divida=is_divida,
        saved_values=saved_values,
        cnpj_info=cnpj_info,
        has_file_input=has_file_input,
    )
    safe_views_update(client, view_id, updated_modal)


@app.action("btn_buscar_cnpj")
def handle_buscar_cnpj_button(ack, body, client):
    """Busca manual de CNPJ via clique de botão"""
    ack()
    view = body["view"]
    view_id = view["id"]
    metadata = json.loads(view.get("private_metadata", "{}"))

    num_exceptions = metadata.get("num_exceptions", 1)
    is_rede = metadata.get("is_rede", False)
    is_divida = metadata.get("is_divida", False)
    current_user_id = metadata.get("current_user_id")
    channel_id = metadata.get("channel_id")
    has_file_input = metadata.get("has_file_input", True)

    saved_values = extract_modal_values(view["state"], num_exceptions)
    cnpj_digitado = saved_values.get("cnpj") or ""
    digitos = re.sub(r"\D", "", str(cnpj_digitado))

    cnpj_info = {}
    if digitos:
        cnpj_info = consultar_cnpj(digitos)
        if cnpj_info.get("sucesso"):
            saved_values["razao_social"] = cnpj_info.get("razao_social", "")
            inep_res = buscar_inep(cnpj_info.get("nome_fantasia", ""), cnpj_info.get("razao_social", ""))
            if inep_res and inep_res.get("codigo_inep"):
                saved_values["inep"] = inep_res["codigo_inep"]

    updated_modal = build_aprovacoes_modal(
        current_user_id=current_user_id,
        channel_id=channel_id,
        num_exceptions=num_exceptions,
        is_rede=is_rede,
        is_divida=is_divida,
        saved_values=saved_values,
        cnpj_info=cnpj_info,
        has_file_input=has_file_input,
    )
    safe_views_update(client, view_id, updated_modal)


@app.action(re.compile(r"^acv_input.*"))
@app.action(re.compile(r"^valor_divida_input.*"))
def handle_currency_realtime_hint(ack, body, client):
    """Atualiza dinamicamente a dica com o valor por extenso conforme o usuário digita"""
    ack()
    view = body["view"]
    view_id = view["id"]
    metadata = json.loads(view.get("private_metadata", "{}"))

    num_exceptions = metadata.get("num_exceptions", 1)
    is_rede = metadata.get("is_rede", False)
    is_divida = metadata.get("is_divida", False)
    current_user_id = metadata.get("current_user_id")
    channel_id = metadata.get("channel_id")
    cnpj_info = metadata.get("cnpj_info", {})
    has_file_input = metadata.get("has_file_input", True)

    saved_values = extract_modal_values(view["state"], num_exceptions)

    # Captura o valor exato recém-digitado da ação atual
    action = body.get("actions", [{}])[0]
    action_id = action.get("action_id", "")
    action_val = action.get("value", "")
    if action_id.startswith("acv_input"):
        saved_values["acv"] = action_val
    elif action_id.startswith("valor_divida_input"):
        saved_values["valor_divida"] = action_val

    updated_modal = build_aprovacoes_modal(
        current_user_id=current_user_id,
        channel_id=channel_id,
        num_exceptions=num_exceptions,
        is_rede=is_rede,
        is_divida=is_divida,
        saved_values=saved_values,
        cnpj_info=cnpj_info,
        has_file_input=has_file_input,
    )
    safe_views_update(client, view_id, updated_modal)


@app.action("btn_add_exception")
def handle_add_exception(ack, body, client):
    """Adiciona dinamicamente a próxima exceção (até o limite de 5)"""
    ack()
    view = body["view"]
    view_id = view["id"]
    metadata = json.loads(view.get("private_metadata", "{}"))
    
    num_exceptions = min(5, metadata.get("num_exceptions", 1) + 1)
    is_rede = metadata.get("is_rede", False)
    is_divida = metadata.get("is_divida", False)
    current_user_id = metadata.get("current_user_id")
    channel_id = metadata.get("channel_id")
    cnpj_info = metadata.get("cnpj_info", {})
    has_file_input = metadata.get("has_file_input", False)

    saved_values = extract_modal_values(view["state"], num_exceptions)

    updated_modal = build_aprovacoes_modal(
        current_user_id=current_user_id,
        channel_id=channel_id,
        num_exceptions=num_exceptions,
        is_rede=is_rede,
        is_divida=is_divida,
        saved_values=saved_values,
        cnpj_info=cnpj_info,
        has_file_input=has_file_input,
    )
    safe_views_update(client, view_id, updated_modal)


@app.action("marcas_select")
def handle_marcas_select(ack, body, client):
    """Atualiza o modal dinamicamente quando o consultor altera as marcas selecionadas"""
    ack()
    view = body["view"]
    view_id = view["id"]
    metadata = json.loads(view.get("private_metadata", "{}"))

    num_exceptions = metadata.get("num_exceptions", 1)
    is_rede = metadata.get("is_rede", False)
    is_divida = metadata.get("is_divida", False)
    current_user_id = metadata.get("current_user_id")
    channel_id = metadata.get("channel_id")
    cnpj_info = metadata.get("cnpj_info", {})
    has_file_input = metadata.get("has_file_input", True)

    saved_values = extract_modal_values(view["state"], num_exceptions)

    selected_opts = body.get("actions", [{}])[0].get("selected_options", [])
    saved_values["marcas"] = [opt["value"] for opt in selected_opts if opt.get("value")]
    logger.info(f"🔔 [ACTION: marcas_select] Marcas selecionadas: {saved_values['marcas']}")

    updated_modal = build_aprovacoes_modal(
        current_user_id=current_user_id,
        channel_id=channel_id,
        num_exceptions=num_exceptions,
        is_rede=is_rede,
        is_divida=is_divida,
        saved_values=saved_values,
        cnpj_info=cnpj_info,
        has_file_input=has_file_input,
    )
    safe_views_update(client, view_id, updated_modal)


# Ignora / reconhece ações sem atualizar o modal inteiro
@app.action("frente_select")
@app.action("consultor_select")
@app.action("lider_select")
@app.action("excecao_1_select")
@app.action("excecao_2_select")
@app.action("excecao_3_select")
@app.action("excecao_4_select")
@app.action("excecao_5_select")
@app.action("link_sf_input")
@app.action("contexto_geral_input")
@app.action("contexto_excecao_1_input")
@app.action("contexto_excecao_2_input")
@app.action("contexto_excecao_3_input")
@app.action("contexto_excecao_4_input")
@app.action("contexto_excecao_5_input")
def handle_generic_action(ack):
    ack()


# =========================================================================
# 3. SUBMISSÃO DO FORMULÁRIO (view_submission) & GOVERNANÇA DE REGRAS
# =========================================================================

@app.view("modal_aprovacoes_arco")
def handle_submission(ack, body, client):
    """Processa o envio do formulário, valida regras e dispara a solicitação"""
    view = body["view"]
    metadata = json.loads(view.get("private_metadata", "{}"))
    num_exceptions = metadata.get("num_exceptions", 1)
    
    data = extract_modal_values(view["state"], num_exceptions)

    # Validações obrigatórias
    errors = {}
    
    def get_actual_block_id(prefix: str) -> str:
        for b_id in view.get("state", {}).get("values", {}).keys():
            if b_id.startswith(prefix):
                return b_id
        return prefix

    if not data.get("frente"):
        errors["frente_block"] = "Selecione uma Frente."
    if not data.get("lider"):
        errors["lider_block"] = "Informe o Líder direto do Consultor."
    elif data.get("lider") == (data.get("consultor") or body["user"]["id"]):
        errors["lider_block"] = "O Líder Direto não pode ser o mesmo usuário do Consultor."
    if not data.get("marcas"):
        errors["marcas_block"] = "Selecione pelo menos uma Marca."

    # CNPJ com 14 dígitos
    cnpj_limpo = re.sub(r"\D", "", str(data.get("cnpj") or ""))
    if not cnpj_limpo or len(cnpj_limpo) != 14:
        errors[get_actual_block_id("cnpj_block")] = "Digite um CNPJ válido com exatamente 14 números."

    if not data.get("razao_social"):
        if cnpj_limpo and len(cnpj_limpo) == 14:
            info = consultar_cnpj(cnpj_limpo)
            if info.get("sucesso"):
                data["razao_social"] = info.get("razao_social")
        if not data.get("razao_social"):
            errors[get_actual_block_id("razao_social_block")] = "Informe a Razão Social da Escola ou digite um CNPJ válido e busque."

    if not data.get("acv"):
        errors["acv_block"] = "Informe o Valor do Contrato (ACV)."
    else:
        acv_parsed = parse_currency_str(data.get("acv"))
        if acv_parsed is None or acv_parsed <= 0:
            errors["acv_block"] = "Informe um valor de contrato válido (ex: 10000 ou 10.000,00)."

    if data.get("tem_divida") == "sim":
        if not data.get("valor_divida"):
            errors["valor_divida_block"] = "Informe o Valor da Dívida da Escola."
        else:
            divida_parsed = parse_currency_str(data.get("valor_divida"))
            if divida_parsed is None or divida_parsed < 0:
                errors["valor_divida_block"] = "Informe um valor de dívida válido (ex: 50000 ou 50.000,00)."

    if not data.get("link_sf"):
        errors["link_sf_block"] = "Informe o Link da Oportunidade no SalesForce."

    if not data.get("contexto_geral"):
        errors["contexto_geral_block"] = "Preencha o Contexto Geral da Escola/Negociação."

    if not data.get("excecao_1"):
        errors["excecao_1_block"] = "Selecione a Exceção 1."

    # Validação de inviabilidade para cada marca selecionada
    for m in data.get("marcas", []):
        slug = re.sub(r"[^a-zA-Z0-9_]", "_", m.lower())
        b_id = f"inviab_block_{slug}"
        val = data.get("inviabilidades", {}).get(m) or data.get(f"inviab_{slug}")
        if val is None or str(val).strip() == "":
            errors[b_id] = f"Informe o percentual de inviabilidade para a marca {m}."

    # Simulador XLSX obrigatório
    if not data.get("simulador_files") and not data.get("simulador_fallback"):
        errors["simulador_block"] = "O anexo do arquivo do Simulador em formato XLSX é obrigatório."

    if errors:
        ack(response_action="errors", errors=errors)
        return

    # Formulário aprovado para envio!
    ack()

    channel_id = metadata.get("channel_id") or DEFAULT_CHANNEL_ID
    consultor_id = data.get("consultor") or body["user"]["id"]
    lider_id = data.get("lider")

    # Mapeamento dos Aprovadores das Exceções selecionadas
    excecoes_detalhes = []
    aprovadores_para_marcar = set()

    for i in range(1, num_exceptions + 1):
        exc_nome = data.get(f"excecao_{i}")
        ctx_exc = data.get(f"contexto_excecao_{i}") or "Sem contexto adicional informado."

        if not exc_nome or exc_nome == "N/A":
            continue

        rule = EXCEPTIONS_RULES.get(exc_nome, {
            "comercial": "Consultar alçada",
            "comercial_approver": None,
            "ops": "-",
            "ops_approver": None,
        })

        # Resolve Aprovador Comercial
        aprov_com = rule.get("comercial_approver")
        com_tag = "-"
        if aprov_com == "LIDER_DIRETO":
            lider_tag = format_mention(lider_id)
            com_tag = f"{lider_tag} (Líder Direto)"
            aprovadores_para_marcar.add(lider_tag)
        elif aprov_com:
            com_tag = format_user_mention(aprov_com)
            aprovadores_para_marcar.add(com_tag)

        # Resolve Aprovador Operações
        aprov_ops = rule.get("ops_approver")
        ops_tag = "-"
        if aprov_ops:
            ops_tag = format_user_mention(aprov_ops)
            aprovadores_para_marcar.add(ops_tag)

        excecoes_detalhes.append({
            "numero": i,
            "nome": exc_nome,
            "contexto": ctx_exc,
            "regra_comercial": rule.get("comercial", "-"),
            "aprov_com_tag": com_tag,
            "regra_ops": rule.get("ops", "-"),
            "aprov_ops_tag": ops_tag,
        })

    # Aprovador Automático de Inviabilidade (Regras de Governança por Marca)
    def checar_inviabilidade(pct_str: Optional[str]) -> bool:
        if not pct_str:
            return False
        limpo = re.sub(r"[^\d,\.]", "", str(pct_str)).replace(",", ".")
        try:
            val = float(limpo)
            return val > 0.0
        except ValueError:
            texto = str(pct_str).strip().lower()
            return bool(texto) and texto not in ["0", "0%", "0.0%", "0,0%", "não", "nao", "-", "n/a"]

    inviabilidades = data.get("inviabilidades", {})
    marcas_selecionadas = data.get("marcas", [])
    marcas_str = ", ".join(marcas_selecionadas)
    consultor_tag = format_mention(consultor_id)
    lider_tag = format_mention(lider_id)

    # Separação de Inviabilidade por Core e Plus
    marcas_com_inviab = []
    core_inviab_vals = []
    plus_inviab_vals = []

    for m in marcas_selecionadas:
        pct = inviabilidades.get(m)
        if checar_inviabilidade(pct):
            val_clean = str(pct).strip().rstrip("%") + "%"
            marcas_com_inviab.append((m, val_clean))
            if m in MARCAS_CORE:
                core_inviab_vals.append(val_clean)
            else:
                plus_inviab_vals.append(val_clean)

    # Aprovador oficial de Inviabilidade
    aprovador_inviab_nome = "Diana Sarah Proenca De Oliveira"
    aprovador_inviab_tag = format_user_mention(aprovador_inviab_nome)

    if marcas_com_inviab:
        aprovadores_para_marcar.add(aprovador_inviab_tag)

    # Aprovador Automático de Dívida > R$ 50k (Rafael Bae)
    tem_divida_alta = False
    aprovador_bae = format_user_mention("Rafael Bae")
    if data.get("tem_divida") == "sim" and data.get("valor_divida"):
        val_div_num = parse_currency_str(data.get("valor_divida")) or 0.0
        if val_div_num > 50000.0:
            tem_divida_alta = True
            aprovadores_para_marcar.add(aprovador_bae)

    # Dados cadastrais e complementares
    cnpj_formatado = data.get('cnpj') or 'Não informado'
    inep_val = data.get('inep') or '-'

    rede_val = data.get("rede_grupo", "nao")
    if rede_val == "sim":
        rede_nome = data.get("nome_rede") or ""
        cnpjs_rede = data.get("cnpjs_rede") or ""
        rede_str = f"Sim - {rede_nome} / / CNPJ (Rede): {cnpjs_rede}"
    else:
        rede_str = "Não / / CNPJ (Rede):"

    alunado_val = data.get('alunado') or '-'
    acv_val = data.get('acv') or '-'
    acv_limpo = format_real_input(acv_val) if acv_val and acv_val != '-' else '-'

    # Links: SalesForce e Simulador
    link_sf = data.get('link_sf') or '-'
    sim_files = data.get("simulador_files", [])
    if sim_files:
        primeiro_arq = sim_files[0]
        nome_arq = primeiro_arq.get("name") or "Simulador.xlsx"
        url_arq = primeiro_arq.get("permalink") or primeiro_arq.get("url_private") or "#"
        link_simulador = f"<{url_arq}|{nome_arq}>"
    elif data.get("simulador_fallback"):
        link_simulador = data["simulador_fallback"]
    else:
        link_simulador = "-"

    # Textos de Inviabilidade Core e Plus
    nomes_marcas_inviab = ", ".join([m for m, _ in marcas_com_inviab]) if marcas_com_inviab else "n/a"
    core_pct_display = ", ".join(core_inviab_vals) if core_inviab_vals else "n/a"
    plus_pct_display = ", ".join(plus_inviab_vals) if plus_inviab_vals else "n/a"

    # Constrói as linhas exatamente no formato do workflow original do usuário
    raw_lines = [
        f"Consultor: {consultor_tag} / Liderança: {lider_tag}",
        f"Frente: {data.get('frente') or '-'}",
        "",
        f"Marcas: {marcas_str}",
        "",
        f"Escola: {data.get('razao_social') or '-'}",
        f"CNPJ: {cnpj_formatado} / INEP: {inep_val}",
        f"Rede/Grupo: {rede_str}",
        "",
        f"Alunado: {alunado_val} / Valor do Contrato: {acv_limpo}",
    ]

    # Se a escola possuir dívida informada
    if data.get("tem_divida") == "sim" and data.get("valor_divida"):
        divida_fmt = format_real_input(data.get("valor_divida")) or data.get("valor_divida")
        raw_lines.append(f"Dívida da Escola: Sim (R$ {divida_fmt})")

    raw_lines.extend([
        "",
        f"🔗SalesForce: {link_sf}",
        f"🔗Simulador: {link_simulador}",
        "",
        "Inviabilidade",
        f"Marca(s) com Inviabilidade: {nomes_marcas_inviab}",
        f"(Core) % de Inviabilidade {core_pct_display}",
        f"(Core) Aprovador(es): {aprovador_inviab_tag}",
        f"(Plus) % de Inviabilidade: {plus_pct_display}",
        f"(Plus) Aprovador(es): {aprovador_inviab_tag}",
        "",
        "Contexto Geral:",
        f"{data.get('contexto_geral') or 'Não informado.'}",
        "",
        "Exceções:",
    ])

    if excecoes_detalhes:
        for idx, item in enumerate(excecoes_detalhes):
            if idx > 0:
                raw_lines.append("-")
            raw_lines.append(f"🔹 Exceção {item['numero']}: {item['nome']}")
            raw_lines.append(f"Contexto: {item['contexto']}")
            aprovadores_exc = []
            if item.get("aprov_com_tag") and item["aprov_com_tag"] != "-":
                aprovadores_exc.append(item["aprov_com_tag"])
            if item.get("aprov_ops_tag") and item["aprov_ops_tag"] != "-" and item["aprov_ops_tag"] not in aprovadores_exc:
                aprovadores_exc.append(item["aprov_ops_tag"])
            for ap in aprovadores_exc:
                raw_lines.append(ap)
    else:
        raw_lines.append("Nenhuma exceção adicional solicitada.")

    # Converte todas as linhas para o formato de bloco com linha cinza vertical `>`
    all_split_lines = []
    for rl in raw_lines:
        for sub in str(rl).split("\n"):
            all_split_lines.append(sub)
    unified_quote_text = "\n".join(f"> {l}" if l.strip() else ">" for l in all_split_lines)

    # Mapeamento das Alçadas Individuais com Botões e Escopo de Aprovação
    approvals_list = []

    # Alçada Comercial (Líder Direto do Consultor)
    lider_display = format_mention(lider_id).replace("@", "").strip() if lider_id else "Líder Direto"
    approvals_list.append({
        "key": "comercial",
        "role_title": "👤 APROVAÇÃO COMERCIAL",
        "short_label": "Comercial",
        "approver_id": lider_id if (lider_id and lider_id.startswith(("U", "W"))) else "",
        "approver_name": lider_display,
        "scope_reason": "Validação de liderança direta sobre as condições comerciais e proposta para o Ciclo CE 2027.",
    })

    # Alçada Operações (se alguma exceção exigir)
    ops_item = next((item for item in excecoes_detalhes if item.get("regra_ops") != "-" and item.get("aprov_ops_tag") != "-"), None)
    if ops_item:
        ops_name = ops_item["aprov_ops_tag"].replace("@", "").strip()
        exc_nome = ops_item.get("nome", "Exceção Operacional")
        approvals_list.append({
            "key": "operacoes",
            "role_title": "⚙️ APROVAÇÃO OPERAÇÕES",
            "short_label": "Operações",
            "approver_id": "",
            "approver_name": ops_name,
            "scope_reason": f"Exceção operacional identificada: {exc_nome} (Regra de Operações exigida).",
        })

    # Alçada Inviabilidade (se alguma marca tiver inviabilidade)
    if marcas_com_inviab:
        nomes_inviab = ", ".join([f"{m} ({p})" for m, p in marcas_com_inviab])
        approvals_list.append({
            "key": "inviabilidade",
            "role_title": "🚨 APROVAÇÃO INVIABILIDADE",
            "short_label": "Inviabilidade",
            "approver_id": "",
            "approver_name": aprovador_inviab_nome,
            "scope_reason": f"Inviabilidade identificada na(s) marca(s): {nomes_inviab}.",
        })

    # Alçada Especial Dívida (> R$ 50k)
    if tem_divida_alta:
        divida_val_display = divida_fmt if (data.get("tem_divida") == "sim" and data.get("valor_divida")) else "Acima de R$ 50k"
        approvals_list.append({
            "key": "divida_bae",
            "role_title": "💰 APROVAÇÃO PENDÊNCIA FINANCEIRA (> R$ 50k)",
            "short_label": "Dívida > 50k",
            "approver_id": "",
            "approver_name": "Rafael Bae (@triagem--contratos psc)",
            "scope_reason": f"Pendência financeira crítica: Dívida da escola informada em R$ {divida_val_display}.",
        })

    extra_ticket_data = {
        "acv": f"R$ {acv_limpo}" if acv_limpo and acv_limpo != "-" else "Não informado",
        "marcas": marcas_str if marcas_str else "Não informada",
        "cnpj": cnpj_formatado,
        "inep": inep_val,
        "valor_divida": divida_fmt if (data.get("tem_divida") == "sim" and data.get("valor_divida")) else None,
        "tem_divida_alta": tem_divida_alta,
        "marcas_com_inviab": bool(marcas_com_inviab),
        "nomes_marcas_inviab": nomes_marcas_inviab,
    }

    # 1. Posta a MENSAGEM ÚNICA no canal
    temp_ticket = {
        "key": "pending",
        "escola": data.get("razao_social") or "Escola",
        "status": "pending",
        "details_text": unified_quote_text,
        "main_text_base": unified_quote_text,
        "extra_data": extra_ticket_data,
        "tem_divida_alta": tem_divida_alta,
        "marcas_com_inviab": bool(marcas_com_inviab),
        "valor_divida": extra_ticket_data["valor_divida"],
        "approvals": {
            apprv["key"]: {
                "key": apprv["key"],
                "role_title": apprv["role_title"],
                "short_label": apprv["short_label"],
                "approver_id": apprv.get("approver_id") or "",
                "approver_name": apprv["approver_name"],
                "scope_reason": apprv.get("scope_reason", ""),
                "status": "pending",
            }
            for apprv in approvals_list
        }
    }
    initial_blocks = build_thread_blocks(temp_ticket)

    resp = client.chat_postMessage(
        channel=channel_id,
        text=f"Aprovações Arco CE 2027: {data.get('razao_social')}",
        blocks=initial_blocks,
    )
    thread_ts = resp["ts"]

    # Obtém permalink
    thread_permalink = None
    try:
        p_resp = client.chat_getPermalink(channel=channel_id, message_ts=thread_ts)
        thread_permalink = p_resp.get("permalink")
    except Exception as e:
        logger.warning(f"Erro ao obter permalink da mensagem: {e}")

    # Registra o ticket no estado persistente com a chave real
    ticket = create_ticket(
        channel_id=channel_id,
        thread_ts=thread_ts,
        escola=data.get("razao_social") or "Escola",
        consultor_id=consultor_id,
        consultor_name=consultor_tag,
        details_text=unified_quote_text,
        approvals_list=approvals_list,
        main_text_base=unified_quote_text,
        thread_permalink=thread_permalink,
        extra_data=extra_ticket_data,
    )
    update_ticket_card_ts(ticket["key"], thread_ts)

    # Atualiza a mensagem única postada com os valores e botões reais vinculados à chave do ticket
    real_blocks = build_thread_blocks(ticket)
    try:
        client.chat_update(
            channel=channel_id,
            ts=thread_ts,
            blocks=real_blocks,
            text=f"Aprovações Arco CE 2027: {ticket['escola']}"
        )
    except Exception as e:
        logger.warning(f"Erro ao atualizar valores dos botões no post inicial: {e}")

    # Envia os cards executivos individuais na DM privada de cada aprovador
    try:
        send_dm_approval_cards(client, ticket, consultor_id)
    except Exception as e:
        logger.error(f"Erro ao enviar DMs de aprovação: {e}")

    logger.info(f"Solicitação criada com sucesso: {ticket['key']} no canal {channel_id}")


# =========================================================================
# 4. AÇÕES DE APROVAÇÃO INTERATIVA (DM PRIVADA & THREAD)
# =========================================================================

@app.action("btn_dm_aprovar")
@app.action("btn_dm_rejeitar")
def handle_dm_approval_action(ack, body, client):
    """
    Processa a decisão do aprovador tomada a partir do card executivo na DM Privada.
    Atualiza a DM in-place, espelha na thread pública e encerra se 100% concluído.
    """
    ack()
    action = body["actions"][0]
    action_id = action.get("action_id")
    action_val = action.get("value", "")
    user_id = body["user"]["id"]
    user_name = body["user"].get("name") or body["user"].get("username") or "Usuário"
    dm_channel_id = body["channel"]["id"]
    message_ts = body["message"]["ts"]

    is_approved = (action_id == "btn_dm_aprovar")

    if ":" not in action_val:
        return

    ticket_key, approval_key = action_val.split(":", 1)
    ticket = get_ticket(ticket_key)
    if not ticket:
        client.chat_postEphemeral(
            channel=dm_channel_id,
            user=user_id,
            text="⚠️ Solicitação não encontrada no histórico ativo do sistema."
        )
        return

    apprv = ticket.get("approvals", {}).get(approval_key, {})
    role_title = apprv.get("role_title", "Aprovação")
    short_label = apprv.get("short_label", "Aprovação")
    now_str = datetime.now().strftime("%d/%m às %Hh%M")

    is_authorized, is_unmapped = check_approval_authorization(apprv, user_id)
    if not is_authorized:
        if is_unmapped:
            auth_text = (
                "⚠️ Esta alçada ainda não possui um aprovador com ID de Slack configurado. "
                "Peça para a @triagem designar um substituto com `/substituir-aprovador`."
            )
        else:
            auth_text = "⚠️ Você não tem permissão para decidir sobre esta alçada."
        client.chat_postEphemeral(channel=dm_channel_id, user=user_id, text=auth_text)
        return

    if is_approved:
        res = approve_step(ticket_key, approval_key, user_id, user_name)
        updated_ticket = res["ticket"]

        # Atualiza a DM in-place: remove botões e estampa a confirmação com escaneabilidade
        dm_updated_blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "✅ Decisão Registrada com Sucesso", "emoji": True}
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*🏫 Escola:*\n{ticket['escola']}"},
                    {"type": "mrkdwn", "text": f"*📋 Alçada:*\n{role_title}"},
                    {"type": "mrkdwn", "text": f"*👤 Decisor:*\n@{user_name}"},
                    {"type": "mrkdwn", "text": f"*⏱️ Horário:*\n{now_str}"},
                ]
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"✅ Sua decisão foi espelhada em tempo real na thread do canal. • 🔗 <{ticket.get('thread_permalink') or '#'}|Ver negociação>"
                    }
                ]
            }
        ]
        try:
            client.chat_update(
                channel=dm_channel_id,
                ts=message_ts,
                blocks=dm_updated_blocks,
                text=f"Aprovação confirmada para {ticket['escola']}"
            )
        except Exception as e:
            logger.error(f"Erro ao atualizar mensagem na DM: {e}")

        # Feedback em tempo real na DM privada do Consultor
        try:
            send_consultor_progress_dm(
                client=client,
                ticket=updated_ticket,
                last_approval_key=approval_key,
                actor_id=user_id,
                actor_name=user_name,
            )
        except Exception as e:
            logger.error(f"Erro ao enviar feedback DM ao consultor: {e}")

        # Espelhamento imediato na Thread pública
        try:
            client.chat_postMessage(
                channel=ticket["channel_id"],
                thread_ts=ticket["thread_ts"],
                text=f"✅ *{role_title}* aprovada via DM privada por <@{user_id}> em {now_str}."
            )
        except Exception as e:
            logger.error(f"Erro ao postar confirmação na thread: {e}")

        # Atualiza o Post Principal no canal
        try:
            main_status_blocks = build_main_post_blocks(updated_ticket)
            client.chat_update(
                channel=ticket["channel_id"],
                ts=ticket["thread_ts"],
                blocks=main_status_blocks,
                text=f"Aprovações Arco: {updated_ticket['escola']}"
            )
        except Exception as e:
            logger.warning(f"Erro ao espelhar status no post principal: {e}")

        # Atualiza o card de status na thread
        card_msg_ts = updated_ticket.get("card_msg_ts")
        if card_msg_ts:
            try:
                updated_blocks = build_thread_blocks(updated_ticket)
                client.chat_update(
                    channel=ticket["channel_id"],
                    ts=card_msg_ts,
                    blocks=updated_blocks,
                    text=f"Status de Aprovações: {updated_ticket['escola']}"
                )
            except Exception as e:
                logger.error(f"Erro ao atualizar card da thread: {e}")

        # Se todas as alçadas foram aprovadas: ENCERRAMENTO AUTOMÁTICO IMEDIATO!
        if res.get("all_completed"):
            try:
                client.chat_postMessage(
                    channel=ticket["channel_id"],
                    thread_ts=ticket["thread_ts"],
                    text="🎉 *SOLICITAÇÃO 100% APROVADA E CONCLUÍDA!* Todos os decisores de alçada deliberaram. Ticket formalmente encerrado e liberado para emissão de contrato."
                )
                client.reactions_add(
                    channel=ticket["channel_id"],
                    timestamp=ticket["thread_ts"],
                    name="white_check_mark"
                )
            except Exception as e:
                logger.warning(f"Erro no encerramento automático: {e}")

    if not is_approved:
        # Abre o modal oficial de reprovação para coletar o motivo padronizado
        modal = build_reprovar_modal(
            ticket_key=ticket_key,
            approval_key=approval_key,
            role_title=role_title,
            escola=ticket.get("escola", "Escola"),
            consultor_id=ticket.get("consultor_id", ""),
            consultor_name=ticket.get("consultor_name", "Consultor"),
            channel_id=ticket.get("channel_id", DEFAULT_CHANNEL_ID),
            is_from_dm=True,
            dm_message_ts=message_ts,
            dm_channel_id=dm_channel_id,
        )
        safe_views_open(client, body["trigger_id"], modal)
        return


@app.action(re.compile(r"^btn_aprovar_.*"))
def handle_thread_approval_action(ack, body, client):
    """
    Processa o clique no botão individual de aprovação dentro da thread pública.
    """
    ack()
    user_id = body["user"]["id"]
    user_name = body["user"].get("name") or body["user"].get("username") or "Usuário"
    action = body["actions"][0]
    action_val = action.get("value", "")

    if ":" not in action_val:
        return

    ticket_key, approval_key = action_val.split(":", 1)
    ticket = get_ticket(ticket_key)
    if not ticket:
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=user_id,
            text="⚠️ Solicitação não encontrada no histórico ativo do sistema."
        )
        return

    apprv = ticket.get("approvals", {}).get(approval_key)
    if not apprv:
        return

    expected_name = apprv.get("approver_name") or "Aprovador Designado"

    is_authorized, is_unmapped = check_approval_authorization(apprv, user_id)
    if not is_authorized:
        if is_unmapped:
            auth_text = (
                f"⚠️ *{expected_name}* ainda não possui um ID de Slack configurado para esta alçada. "
                f"Peça para a @triagem designar um aprovador com `/substituir-aprovador` antes de decidir por aqui."
            )
        else:
            auth_text = f"⚠️ Você não tem permissão para aprovar este item. Apenas @{expected_name} pode dar este aceite."
        client.chat_postEphemeral(
            channel=ticket["channel_id"],
            user=user_id,
            text=auth_text
        )
        return

    res = approve_step(ticket_key, approval_key, user_id, user_name)
    updated_ticket = res["ticket"]

    card_msg_ts = updated_ticket.get("card_msg_ts")
    if card_msg_ts:
        updated_blocks = build_thread_blocks(updated_ticket)
        try:
            client.chat_update(
                channel=ticket["channel_id"],
                ts=card_msg_ts,
                blocks=updated_blocks,
                text=f"Status de Aprovações: {updated_ticket['escola']}"
            )
        except Exception as e:
            logger.error(f"Erro ao atualizar mensagem da thread: {e}")

    try:
        main_status_blocks = build_main_post_blocks(updated_ticket)
        client.chat_update(
            channel=ticket["channel_id"],
            ts=ticket["thread_ts"],
            blocks=main_status_blocks,
            text=f"Aprovações Arco: {updated_ticket['escola']}"
        )
    except Exception as e:
        logger.warning(f"Erro ao espelhar status no post principal: {e}")

    now_str = datetime.now().strftime("%d/%m às %Hh%M")
    client.chat_postMessage(
        channel=ticket["channel_id"],
        thread_ts=ticket["thread_ts"],
        text=f"✅ *{apprv['role_title']}* aprovada com sucesso por <@{user_id}> em {now_str}."
    )

    # Feedback em tempo real na DM privada do Consultor
    try:
        send_consultor_progress_dm(
            client=client,
            ticket=updated_ticket,
            last_approval_key=approval_key,
            actor_id=user_id,
            actor_name=user_name,
        )
    except Exception as e:
        logger.error(f"Erro ao enviar feedback DM ao consultor: {e}")

    if res.get("all_completed"):
        client.chat_postMessage(
            channel=ticket["channel_id"],
            thread_ts=ticket["thread_ts"],
            text="🎉 *SOLICITAÇÃO 100% APROVADA E CONCLUÍDA!* Todos os decisores de alçada deliberaram. Ticket formalmente encerrado e liberado para emissão de contrato."
        )
        try:
            client.reactions_add(
                channel=ticket["channel_id"],
                timestamp=ticket["thread_ts"],
                name="white_check_mark"
            )
        except Exception as e:
            logger.warning(f"Reação check_mark: {e}")


# =========================================================================
# 4.1. REPROVAÇÃO FORMAL DE SOLICITAÇÃO (Thread & DM)
# =========================================================================

@app.action(re.compile(r"^btn_reprovar_.*"))
def handle_thread_reprovar_action(ack, body, client):
    """
    Abre o modal oficial de reprovação com motivos e validações na thread pública.
    """
    ack()
    user_id = body["user"]["id"]
    action = body["actions"][0]
    action_val = action.get("value", "")

    if ":" not in action_val:
        return

    ticket_key, approval_key = action_val.split(":", 1)
    ticket = get_ticket(ticket_key)
    if not ticket:
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=user_id,
            text="⚠️ Solicitação não encontrada no histórico ativo do sistema."
        )
        return

    if ticket.get("status") in ("completed", "rejected"):
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=user_id,
            text=f"⚠️ Este ticket já foi finalizado como *{ticket.get('status')}*."
        )
        return

    apprv = ticket.get("approvals", {}).get(approval_key)
    if not apprv:
        return

    expected_name = apprv.get("approver_name") or "Aprovador Designado"

    is_authorized, is_unmapped = check_approval_authorization(apprv, user_id)
    if not is_authorized:
        if is_unmapped:
            auth_text = (
                f"⚠️ *{expected_name}* ainda não possui um ID de Slack configurado para esta alçada. "
                f"Peça para a @triagem designar um aprovador com `/substituir-aprovador` antes de decidir por aqui."
            )
        else:
            auth_text = f"⚠️ Você não tem permissão para reprovar este item. Apenas @{expected_name} pode tomar esta decisão."
        client.chat_postEphemeral(
            channel=ticket["channel_id"],
            user=user_id,
            text=auth_text
        )
        return

    modal = build_reprovar_modal(
        ticket_key=ticket_key,
        approval_key=approval_key,
        role_title=apprv.get("role_title", "Alçada"),
        escola=ticket.get("escola", "Escola"),
        consultor_id=ticket.get("consultor_id", ""),
        consultor_name=ticket.get("consultor_name", "Consultor"),
        channel_id=ticket.get("channel_id", DEFAULT_CHANNEL_ID),
        is_from_dm=False,
    )
    safe_views_open(client, body["trigger_id"], modal)


@app.view("modal_reprovar_ticket")
def handle_view_reprovar_ticket(ack, body, client, view):
    """
    Processa a submissão do modal de reprovação formal.
    Valida obrigatoriedade de justificativa para 'c. Outros'.
    Registra reprovação, marca consultor na thread e encerra o ticket.
    """
    values = view.get("state", {}).get("values", {})
    metadata = json.loads(view.get("private_metadata") or "{}")

    ticket_key = metadata.get("ticket_key")
    approval_key = metadata.get("approval_key")
    role_title = metadata.get("role_title", "Alçada")
    escola = metadata.get("escola", "Escola")
    consultor_id = metadata.get("consultor_id", "")
    channel_id = metadata.get("channel_id") or DEFAULT_CHANNEL_ID
    is_from_dm = metadata.get("is_from_dm", False)
    dm_message_ts = metadata.get("dm_message_ts")
    dm_channel_id = metadata.get("dm_channel_id")

    # Obtém motivo selecionado
    motivo_elem = values.get("motivo_reprovacao_block", {}).get("motivo_reprovacao_select", {})
    reason_key = motivo_elem.get("selected_option", {}).get("value")

    # Obtém justificativa / detalhes
    detalhes_elem = values.get("detalhes_reprovacao_block", {}).get("detalhes_reprovacao_input", {})
    detalhes = detalhes_elem.get("value") or ""

    errors = {}
    if not reason_key:
        errors["motivo_reprovacao_block"] = "Por favor, selecione um motivo para a reprovação."

    # Validação: campo de texto obrigatório para qualquer justificativa
    if not detalhes.strip():
        errors["detalhes_reprovacao_block"] = "Por favor, preencha a justificativa / detalhes da decisão para o consultor."

    if errors:
        ack(response_action="errors", errors=errors)
        return

    ack()

    reason_map = {
        "negociacao_caiu": "a. Negociação caiu",
        "precisa_mais_informacoes": "b. Precisa de mais informações",
        "outros": "c. Outros",
    }
    reason_label = reason_map.get(reason_key, reason_key)

    user_id = body["user"]["id"]
    user_name = body["user"].get("name") or body["user"].get("username") or "Usuário"

    res = reject_step(
        ticket_key=ticket_key,
        approval_key=approval_key,
        user_id=user_id,
        user_name=user_name,
        reason_key=reason_key,
        reason_label=reason_label,
        details=detalhes.strip(),
    )

    if not res.get("success"):
        logger.error(f"Erro ao rejeitar ticket {ticket_key}: {res.get('error')}")
        return

    updated_ticket = res["ticket"]
    now_str = datetime.now().strftime("%d/%m às %Hh%M")

    # 1. Posta aviso de alerta na thread marcando o consultor responsável (<@{consultor_id}>)
    consultor_tag = f"<@{consultor_id}>" if consultor_id and consultor_id.startswith(("U", "W")) else f"@{metadata.get('consultor_name', 'Consultor')}"
    detalhes_txt = f"\n• *Justificativa / Apontamentos:* _{detalhes.strip()}_" if detalhes.strip() else ""

    alert_msg = (
        f"🚨 *SOLICITAÇÃO COMERCIAL REPROVADA*\n"
        f"👤 *Atenção:* {consultor_tag} (Consultor Responsável)\n"
        f"• *Escola:* *{escola}*\n"
        f"• *Alçada:* *{role_title}* deliberada por <@{user_id}> em {now_str}\n"
        f"• *Motivo Formal:* *{reason_label}*{detalhes_txt}\n\n"
        f"⛔ *Status:* *Ticket encerrado.* Para nova análise ou correção, submeta uma nova solicitação via `/solicitacao`."
    )

    client.chat_postMessage(
        channel=channel_id,
        thread_ts=updated_ticket["thread_ts"],
        text=alert_msg
    )

    # 2. Adiciona reação de :x: na mensagem inicial da thread
    try:
        client.reactions_add(
            channel=channel_id,
            timestamp=updated_ticket["thread_ts"],
            name="x"
        )
    except Exception as e:
        logger.warning(f"Reação :x: na thread: {e}")

    # 3. Atualiza o card de status na thread
    card_msg_ts = updated_ticket.get("card_msg_ts")
    if card_msg_ts:
        try:
            updated_blocks = build_thread_blocks(updated_ticket)
            client.chat_update(
                channel=channel_id,
                ts=card_msg_ts,
                blocks=updated_blocks,
                text=f"Status de Aprovações: {updated_ticket['escola']}"
            )
        except Exception as e:
            logger.error(f"Erro ao atualizar card da thread pós-reprovação: {e}")

    # 4. Atualiza o Post Principal no canal de negociações
    try:
        main_status_blocks = build_main_post_blocks(updated_ticket)
        client.chat_update(
            channel=channel_id,
            ts=updated_ticket["thread_ts"],
            blocks=main_status_blocks,
            text=f"Aprovações Arco: {updated_ticket['escola']}"
        )
    except Exception as e:
        logger.warning(f"Erro ao atualizar post principal pós-reprovação: {e}")

    # 5. Se veio da DM privada, atualiza o card da DM in-place com escaneabilidade
    if is_from_dm and dm_message_ts:
        try:
            target_dm_ch = dm_channel_id or user_id
            dm_blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "❌ Decisão Registrada: Reprovada", "emoji": True}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*🏫 Escola:*\n{escola}"},
                        {"type": "mrkdwn", "text": f"*📋 Alçada:*\n{role_title}"},
                        {"type": "mrkdwn", "text": f"*👤 Decisor:*\n@{user_name}"},
                        {"type": "mrkdwn", "text": f"*⏱️ Horário:*\n{now_str}"},
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Motivo Formal:* *{reason_label}*{detalhes_txt}\n\n_O consultor ({consultor_tag}) foi notificado na DM e na thread com seus apontamentos._"
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"🔗 <{updated_ticket.get('thread_permalink') or '#'}|Abrir thread no canal de negociação>"
                        }
                    ]
                }
            ]
            client.chat_update(
                channel=target_dm_ch,
                ts=dm_message_ts,
                blocks=dm_blocks,
                text=f"Solicitação reprovada para {escola}"
            )
        except Exception as e:
            logger.error(f"Erro ao atualizar DM pós-reprovação: {e}")

    # 6. Notifica o consultor responsável em tempo real na DM privada
    try:
        rejection_payload = {
            "role_title": role_title,
            "rejected_by_name": user_name,
            "reason_label": reason_label,
            "details": detalhes.strip(),
        }
        send_consultor_rejection_dm(
            client=client,
            ticket=updated_ticket,
            rejection_data=rejection_payload,
            fallback_user_id=user_id,
        )
    except Exception as e:
        logger.error(f"Erro ao enviar DM de reprovação ao consultor: {e}")


# =========================================================================
# 4.2. SUBSTITUIÇÃO DE APROVADORES POR AUSÊNCIA (@TRIAGEM)
# =========================================================================

@app.action("btn_triagem_substituicao")
def handle_btn_triagem_substituicao(ack, body, client):
    """
    Ação acionada pelo botão da @triagem dentro da thread para trocar aprovador por ausência.
    """
    ack()
    user_id = body["user"]["id"]
    user_name = body["user"].get("name") or body["user"].get("username") or "Usuário"
    channel_id = body["channel"]["id"]
    action_val = body["actions"][0].get("value", "")

    if not is_user_triagem(user_id, user_name):
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="⛔ *Acesso Restrito ao Perfil @triagem:*\nApenas membros autorizados da Triagem têm permissão para substituir aprovadores por ausência temporária."
        )
        return

    ticket = get_ticket(action_val)
    if not ticket:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="⚠️ Ticket não encontrado no histórico ativo."
        )
        return

    if ticket.get("status") in ("completed", "rejected"):
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"⚠️ Este ticket já se encontra finalizado como *{ticket.get('status')}*. A substituição só é permitida em tickets pendentes."
        )
        return

    modal = build_triagem_substituicao_modal(
        ticket=ticket,
        current_user_id=user_id,
        channel_id=channel_id,
    )
    safe_views_open(client, body["trigger_id"], modal)


@app.action("btn_triagem_cobrar_ticket")
def handle_btn_triagem_cobrar_ticket(ack, body, client):
    """
    Ação acionada pelo botão da @triagem dentro da thread para cobrar pendências deste ticket específico.
    """
    ack()
    user_id = body["user"]["id"]
    user_name = body["user"].get("name") or body["user"].get("username") or "Triagem"
    channel_id = body["channel"]["id"]
    ticket_key = body["actions"][0].get("value", "")

    if not is_user_triagem(user_id, user_name):
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="⛔ *Acesso Restrito ao Perfil @triagem:*\nApenas membros autorizados da Triagem têm permissão para cobrar pendências deste ticket."
        )
        return

    res = cobrar_pendencias_de_ticket(client, ticket_key, user_id)
    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=res.get("message", "Cobrança de pendências realizada com sucesso.")
    )


@app.command("/substituir-aprovador")
def handle_cmd_substituir_aprovador(ack, body, client):
    """
    Comando de barra alternativo para a @triagem realizar a troca de aprovador.
    """
    ack()
    user_id = body["user_id"]
    user_name = body.get("user_name", "")
    channel_id = body["channel_id"]
    text = (body.get("text") or "").strip()

    if not is_user_triagem(user_id, user_name):
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="⛔ *Acesso Restrito ao Perfil @triagem:*\nApenas membros autorizados da Triagem têm permissão para executar este comando."
        )
        return

    target_ticket = None
    if text:
        target_ticket = get_ticket(text.strip())

    if not target_ticket:
        pendings = get_pending_tickets()
        for p in reversed(pendings):
            if p.get("channel_id") == channel_id:
                target_ticket = p
                break
        if not target_ticket and pendings:
            target_ticket = pendings[-1]

    if not target_ticket:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="⚠️ Nenhuma solicitação pendente encontrada para substituição."
        )
        return

    modal = build_triagem_substituicao_modal(
        ticket=target_ticket,
        current_user_id=user_id,
        channel_id=channel_id,
    )
    safe_views_open(client, body["trigger_id"], modal)


@app.view("modal_triagem_substituicao")
def handle_view_triagem_substituicao(ack, body, client, view):
    """
    Processa a submissão do modal da @triagem para substituição temporária de aprovador.
    Valida a data limite (>= hoje), atualiza o ticket, registra no histórico de vigência,
    posta auditoria formal na thread e dispara card na DM para o novo substituto.
    """
    values = view.get("state", {}).get("values", {})
    metadata = json.loads(view.get("private_metadata") or "{}")

    ticket_key = metadata.get("ticket_key")
    channel_id = metadata.get("channel_id") or DEFAULT_CHANNEL_ID
    user_id = body["user"]["id"]
    user_name = body["user"].get("name") or body["user"].get("username") or "Triagem"

    if not is_user_triagem(user_id, user_name):
        logger.warning(f"Usuário {user_id} tentou submeter substituição sem permissão de @triagem.")
        ack()
        return

    # 1. Alçada
    alcada_elem = values.get("alcada_substituicao_block", {}).get("alcada_substituicao_select", {})
    alcada_key = alcada_elem.get("selected_option", {}).get("value")

    # 2. Novo aprovador
    novo_elem = values.get("novo_aprovador_block", {}).get("novo_aprovador_select", {})
    if novo_elem.get("type") == "static_select":
        novo_aprovador_id = novo_elem.get("selected_option", {}).get("value")
        novo_aprovador_name = novo_elem.get("selected_option", {}).get("text", {}).get("text", "Aprovador Substituto")
    else:
        novo_aprovador_id = novo_elem.get("selected_user")
        novo_aprovador_name = "Aprovador Substituto"

    # 3. Data limite
    date_elem = values.get("data_limite_block", {}).get("data_limite_datepicker", {})
    until_date = date_elem.get("selected_date")

    # 4. Motivo
    motivo_elem = values.get("motivo_ausencia_block", {}).get("motivo_ausencia_input", {})
    motivo_ausencia = (motivo_elem.get("value") or "").strip()

    ticket_for_validation = get_ticket(ticket_key)
    consultor_id_check = ticket_for_validation.get("consultor_id") if ticket_for_validation else None

    errors = {}
    if not alcada_key or alcada_key == "none":
        errors["alcada_substituicao_block"] = "Selecione uma alçada pendente para substituição."

    if not novo_aprovador_id:
        errors["novo_aprovador_block"] = "Selecione o aprovador substituto."
    elif novo_aprovador_id == user_id:
        errors["novo_aprovador_block"] = "Você não pode se autodesignar como aprovador substituto."
    elif consultor_id_check and novo_aprovador_id == consultor_id_check:
        errors["novo_aprovador_block"] = "O consultor responsável pela solicitação não pode ser o aprovador substituto."

    today_str = datetime.now().strftime("%Y-%m-%d")
    if not until_date:
        errors["data_limite_block"] = "Informe a data limite para a vigência do substituto."
    elif until_date < today_str:
        errors["data_limite_block"] = f"A data limite deve ser hoje ({datetime.now().strftime('%d/%m/%Y')}) ou uma data futura."

    if errors:
        ack(response_action="errors", errors=errors)
        return

    ack()

    # Tenta obter nome real do usuário se for ID de Slack real
    if novo_aprovador_id and novo_aprovador_id.startswith(("U", "W")):
        try:
            u_info = client.users_info(user=novo_aprovador_id)
            u_obj = u_info.get("user", {})
            novo_aprovador_name = u_obj.get("real_name") or u_obj.get("name") or novo_aprovador_name
        except Exception:
            pass

    # Limpa o texto de teste se presente
    if "Meu Usuário Atual" in novo_aprovador_name:
        novo_aprovador_name = "Usuário Teste (Você)"

    # Executa a substituição no ticket
    sub_res = substitute_approver(
        ticket_key=ticket_key,
        approval_key=alcada_key,
        new_approver_id=novo_aprovador_id,
        new_approver_name=novo_aprovador_name,
        until_date=until_date,
        reason=motivo_ausencia,
        triagem_user_id=user_id,
    )

    if not sub_res.get("success"):
        logger.error(f"Erro ao substituir aprovador: {sub_res.get('error')}")
        return

    updated_ticket = sub_res["ticket"]
    apprv = sub_res["approval"]
    orig_name = sub_res.get("original_approver_name", "Titular")
    orig_id = sub_res.get("original_approver_id", "")
    role_title = apprv.get("role_title", "Alçada")

    # Registra no serviço persistente de substituições
    registrar_substituicao(
        ticket_key=ticket_key,
        approval_key=alcada_key,
        role_title=role_title,
        original_approver_id=orig_id,
        original_approver_name=orig_name,
        new_approver_id=novo_aprovador_id,
        new_approver_name=novo_aprovador_name,
        until_date=until_date,
        reason=motivo_ausencia,
        triagem_user_id=user_id,
    )

    # Formatação da data
    try:
        dt_obj = datetime.strptime(until_date, "%Y-%m-%d")
        until_formatted = dt_obj.strftime("%d/%m/%Y")
    except Exception:
        until_formatted = until_date

    # Menção ao substituto
    sub_mention = f"<@{novo_aprovador_id}>" if novo_aprovador_id and novo_aprovador_id.startswith(("U", "W")) else f"@{novo_aprovador_name}"
    motivo_txt = f"\n• *Motivo Informado:* _{motivo_ausencia}_" if motivo_ausencia else ""

    # 1. Posta auditoria pública na thread do ticket
    audit_msg = (
        f"🔄 *SUBSTITUIÇÃO DE APROVADOR POR AUSÊNCIA (@triagem)*\n"
        f"• *Alçada:* *{role_title}*\n"
        f"• *Titular Ausente:* @{orig_name}\n"
        f"• *Substituto Designado:* {sub_mention} (@{novo_aprovador_name})\n"
        f"• *Vigência:* Até *{until_formatted}* (inclusive){motivo_txt}\n"
        f"• *Ação realizada por:* <@{user_id}> (@triagem)\n\n"
        f"ℹ️ _O aprovador substituto já recebeu o card executivo para deliberação na DM e possui autorização imediata para aprovar ou reprovar esta solicitação._"
    )

    client.chat_postMessage(
        channel=channel_id,
        thread_ts=updated_ticket["thread_ts"],
        text=audit_msg
    )

    # 2. Atualiza o card de aprovações na thread com o badge de substituição
    card_msg_ts = updated_ticket.get("card_msg_ts")
    if card_msg_ts:
        try:
            updated_blocks = build_thread_blocks(updated_ticket)
            client.chat_update(
                channel=channel_id,
                ts=card_msg_ts,
                blocks=updated_blocks,
                text=f"Status de Aprovações: {updated_ticket['escola']}"
            )
        except Exception as e:
            logger.error(f"Erro ao atualizar card da thread pós-substituição: {e}")

    # 3. Dispara DM para o aprovador substituto com o card executivo
    try:
        send_dm_substitute_card(
            client=client,
            ticket=updated_ticket,
            approval_key=alcada_key,
            current_user_id=user_id,
        )
    except Exception as e:
        logger.error(f"Erro ao enviar DM para o substituto: {e}")


# =========================================================================
# 5. COBRANÇA INTELIGENTE DE PENDÊNCIAS (2x ao dia ou sob demanda)
# =========================================================================

@app.command("/cobrar-pendencias")
def handle_cmd_cobranca(ack, body, client):
    """Comando administrativo para disparar a cobrança de pendências manualmente"""
    ack()
    channel_id = body["channel_id"]
    user_id = body["user_id"]
    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text="⏳ Verificando pendências ativas e disparando cobranças inteligentes..."
    )
    total = executar_cobranca_pendencias(client)
    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=f"✅ Cobrança inteligente concluída! Total de lembretes enviados: {total}."
    )


@app.message("!cobrar")
def handle_msg_cobranca(message, say, client):
    """Dispara a cobrança de pendências por palavra-chave no canal"""
    total = executar_cobranca_pendencias(client)
    say(f"📢 *Cobrança Inteligente:* {total} lembrete(s) disparado(s) para alçadas pendentes nas threads ativas.")


# =========================================================================
# 6. INICIALIZAÇÃO DO BOT & AGENDADOR VIA SOCKET MODE
# =========================================================================

if __name__ == "__main__":
    try:
        bg_scheduler = BackgroundScheduler()
        bg_scheduler.add_job(
            lambda: executar_cobranca_pendencias(app.client),
            CronTrigger(hour=11, minute=0, day_of_week="mon-fri", timezone="America/Sao_Paulo"),
            id="cobranca_11h"
        )
        bg_scheduler.add_job(
            lambda: executar_cobranca_pendencias(app.client),
            CronTrigger(hour=17, minute=0, day_of_week="mon-fri", timezone="America/Sao_Paulo"),
            id="cobranca_17h"
        )
        bg_scheduler.start()
        logger.info("⏰ Agendador de Cobrança Inteligente ativo (11:00 e 17:00, horário de Brasília, seg-sex). DMs só saem para SLA vencido.")
    except Exception as e:
        logger.warning(f"Aviso ao iniciar BackgroundScheduler: {e}")

    logger.info("⚡ Iniciando o Slack Bot em Socket Mode...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
