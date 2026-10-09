import os
import tempfile

import services.ticket_service as ts
from services.ticket_service import create_ticket, approve_step, reject_step
import services.sheets_service as sh


class FakeWS:
    def __init__(self):
        self.rows = []

    def row_values(self, n):
        return self.rows[n - 1] if len(self.rows) >= n else []

    def col_values(self, n):
        return [r[n - 1] for r in self.rows]

    def update(self, values, range_name, raw=True):
        idx = int(range_name[1:])
        while len(self.rows) < idx:
            self.rows.append([])
        self.rows[idx - 1] = values[0]

    def append_row(self, row, value_input_option="RAW"):
        self.rows.append(row)

    def freeze(self, rows=1):
        pass


class FakeSpreadsheet:
    def __init__(self):
        self.tabs = {}

    def worksheet(self, nome):
        if nome not in self.tabs:
            raise KeyError(nome)
        return self.tabs[nome]

    def add_worksheet(self, title, rows, cols):
        self.tabs[title] = FakeWS()
        return self.tabs[title]


with tempfile.TemporaryDirectory() as tmp:
    ts.TICKETS_FILE = os.path.join(tmp, "tickets_state.json")
    sheet = FakeSpreadsheet()

    t = create_ticket(
        channel_id="C1", thread_ts="1.1", escola="Escola X",
        consultor_id="U1", consultor_name="Consultor",
        details_text="texto",
        approvals_list=[
            {"key": "comercial", "role_title": "Comercial", "short_label": "Comercial",
             "approver_id": "U_LIDER", "approver_name": "Líder"},
            {"key": "excecao_1_com", "role_title": "Exceção 1", "short_label": "Exceção 1",
             "approver_id": "", "approver_name": "Rafael", "parcial": True},
        ],
        extra_data={"tipo_fluxo": "renovacao", "pct_reajuste_liquido": "6"},
    )
    sh.gravar_ticket(sheet, t)
    ws = sheet.tabs["Renovação"]
    assert ws.rows[0] == sh.SHEET_FIELDS
    assert len(ws.rows) == 2 and ws.rows[1][0] == t["key"]
    assert "Crescimento" not in sheet.tabs

    reject_step(t["key"], "excecao_1_com", "U_R", "Rafael", "outros", "c. Outros", "x")
    res = approve_step(t["key"], "comercial", "U_LIDER", "Líder")
    sh.gravar_ticket(sheet, res["ticket"])
    assert len(ws.rows) == 2, "deve atualizar a mesma linha, não duplicar"
    cabecalho = ws.rows[0]
    linha = dict(zip(cabecalho, ws.rows[1]))
    assert linha["status"] == "Concluído" and linha["resultado"] == "Aprovação parcial"
    assert "Exceção 1: ❌ reprovado" in linha["alcadas"] and "Comercial: ✅ aprovado" in linha["alcadas"]

    assert not sh.is_enabled()  # sem GOOGLE_SHEET_ID: não faz nada
    sh.sincronizar_ticket(t["key"])

print("SUCCESS: espelhamento na planilha validado!")
