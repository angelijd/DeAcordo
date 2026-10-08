"""
Exporta tickets_state.json para CSVs tabulares (tickets.csv, approvals.csv e
exceptions.csv), prontos para carregar em qualquer banco/planilha (ex.:
BigQuery) quando houver destino definido. Não escreve em nenhum serviço externo.

Uso: python export_tickets_csv.py [pasta_de_saida]
"""
import sys
from services.ticket_service import export_to_csv

if __name__ == "__main__":
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "export"
    paths = export_to_csv(out_dir)
    print(f"✅ Exportado: {paths['tickets_csv']}, {paths['approvals_csv']} e {paths['exceptions_csv']}")
