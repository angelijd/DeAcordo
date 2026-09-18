import os
import json
from typing import Dict, Any, List
from google import genai
from google.genai import types

SYSTEM_PROMPT = """Você é um assistente de inteligência artificial encarregado de fazer a triagem e encerramento de threads de solicitações de aprovação na Arco Educação.
Você analisa o histórico das mensagens trocadas em uma thread de aprovação e decide se o fluxo foi concluído/resolvido ou se ainda deve permanecer aberto.

Critérios para fechar (is_resolved = true):
- Todos os aprovadores marcados deram o "de acordo", "aprovado", "ok" ou validaram a exceção.
- O solicitante/consultor confirmou que a demanda foi atendida ("resolvido", "fechado", "obrigado").
- A negociação foi declarada encerrada ou cancelada.

Critérios para manter aberto (is_resolved = false):
- Ainda há perguntas sem resposta na thread.
- Algum aprovador pediu mais informações ou ajuste de cálculo/simulador e ainda não houve resposta final.
- Ninguém respondeu ainda ou está em análise.

Responda ESTRITAMENTE em formato JSON com o seguinte esquema:
{
  "is_resolved": boolean,
  "reason": "motivo claro e sucinto da decisão",
  "closing_message": "mensagem cordial informando o encerramento da thread caso is_resolved seja true, ou string vazia caso false"
}
"""

def analisar_thread_com_ia(thread_messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analisa as mensagens de uma thread com o Gemini para decidir se deve ser fechada.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {
            "is_resolved": False,
            "reason": "GEMINI_API_KEY não configurada no arquivo .env.",
            "closing_message": "",
        }

    # Formata a conversa da thread
    transcript_lines = []
    for msg in thread_messages:
        user = msg.get("user") or "Bot"
        text = msg.get("text", "")
        transcript_lines.append(f"[{user}]: {text}")

    full_conversation = "\n".join(transcript_lines)
    
    prompt = f"Avalie o histórico de mensagens desta thread de aprovação:\n\n{full_conversation}"

    try:
        model_name = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        
        result = json.loads(response.text)
        return {
            "is_resolved": bool(result.get("is_resolved")),
            "reason": result.get("reason", ""),
            "closing_message": result.get("closing_message", "🔒 Solicitação finalizada automaticamente após confirmação de aprovação."),
        }
    except Exception as e:
        return {
            "is_resolved": False,
            "reason": f"Erro na chamada do modelo de IA: {str(e)}",
            "closing_message": "",
        }
