"""
Retenção de fim de ano: mantém só o necessário pra analisar produtividade
(quantidade de contratos, SLA no prazo/vencido de Comercial e Operações,
consultor e aprovador nominal responsáveis) e descarta o resto (CNPJ, valores,
texto livre, etc.) dos tickets já encerrados daquele ano.

Sem --confirm, só mostra o resumo que seria salvo - não altera nada.

Uso:
  python purge_old_tickets.py 2026              # só mostra o resumo
  python purge_old_tickets.py 2026 --confirm    # grava o resumo e descarta os dados detalhados
"""
import sys
import json
from services.ticket_service import purge_tickets_keep_summary

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python purge_old_tickets.py <ano> [--confirm]")
        sys.exit(1)

    year = int(sys.argv[1])
    confirm = "--confirm" in sys.argv[2:]

    result = purge_tickets_keep_summary(year, confirm=confirm)

    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    if result["executado"]:
        print(f"\n✅ Resumo salvo em {result['summary_path']}. {result['tickets_descartados']} ticket(s) encerrado(s) de {year} removido(s) de tickets_state.json.")
    else:
        print(f"\nℹ️ {result['aviso']}")
