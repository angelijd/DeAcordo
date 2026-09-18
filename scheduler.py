import os
import sys
import logging
from datetime import datetime
from dotenv import load_dotenv
from slack_sdk import WebClient
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from services.ticket_service import executar_cobranca_pendencias

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cobranca_scheduler")

load_dotenv()

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
        # Agenda 2x ao dia: às 11:00 e às 17:00 de segunda a sexta-feira
        trigger_11h = CronTrigger(hour=11, minute=0, day_of_week="mon-fri")
        trigger_17h = CronTrigger(hour=17, minute=0, day_of_week="mon-fri")

        scheduler.add_job(rotina_cobranca, trigger_11h, id="job_11h")
        scheduler.add_job(rotina_cobranca, trigger_17h, id="job_17h")

        logger.info("🕒 Agendador de Cobrança iniciado! Execuções diárias às 11:00 e 17:00 (Segunda a Sexta).")
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Agendador encerrado.")
