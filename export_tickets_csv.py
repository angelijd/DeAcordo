"""
Exporta tickets_state.json para CSVs tabulares, separados por tipo de fluxo
(Crescimento e Renovação): tickets_<tipo>.csv, approvals_<tipo>.csv e
exceptions_<tipo>.csv, prontos para carregar em planilhas/tabelas distintas
por tipo de solicitação. Não escreve em nenhum serviço externo.

Uso: python export_tickets_csv.py [pasta_de_saida]
"""
import sys
from services.ticket_service import export_to_csv

if __name__ == "__main__":
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "export"
    paths = export_to_csv(out_dir)
    print("✅ Exportado:")
    for nome, caminho in sorted(paths.items()):
        print(f"  - {nome}: {caminho}")
