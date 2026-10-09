import os
import sys
import logging
from datetime import datetime
from dotenv import load_dotenv

# Precisa vir antes do import de services/, que lê o .env ao ser importado
load_dotenv()

from slack_sdk import WebClient
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from services.ticket_service import executar_cobranca_pendencias

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cobranca_scheduler")

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")

if not SLACK_BOT_TOKEN:
    raise ValueError("SLACK_BOT_TOKEN não configurado no .env!")

client = WebClient(token=SLACK_BOT_TOKEN)

def rotina_cobranca():
    logger.info(f"[{datetime.now()}] 🔍 Iniciando rotina de cobrança inteligente de pendências...")
    total = executar_cobranca_pendencias(client)
    logger.info(f"[{datetime.now()}] ✅ Rotina concluída. Lembretes enviados: {total}")

if __name__ == "__main__":
    if "--run-now" in sys.argv:
        logger.info("Executando cobrança imediatamente (--run-now)...")
        rotina_cobranca()
    else:
        scheduler = BlockingScheduler()
        # Agenda 2x ao dia: às 09:00 e às 14:00 de segunda a sexta-feira, horário de Brasília
        trigger_09h = CronTrigger(hour=9, minute=0, day_of_week="mon-fri", timezone="America/Sao_Paulo")
        trigger_14h = CronTrigger(hour=14, minute=0, day_of_week="mon-fri", timezone="America/Sao_Paulo")

        scheduler.add_job(rotina_cobranca, trigger_09h, id="job_09h")
        scheduler.add_job(rotina_cobranca, trigger_14h, id="job_14h")

        logger.info("🕒 Agendador de Cobrança iniciado! Execuções diárias às 09:00 e 14:00 (Segunda a Sexta).")
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Agendador encerrado.")
