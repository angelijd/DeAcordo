"""Correções da 2ª revisão do PR de produção: triagem só por ID, texto livre neutralizado,
data das trocas em horário de Brasília e falha de leitura do estado sem apagar tickets."""

import os
import json
import tempfile
from datetime import datetime, timezone
from unittest import mock

os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")

from utils.texto import neutralizar_mrkdwn


def test_triagem_so_por_id():
    with mock.patch.dict(os.environ, {"TRIAGEM_USER_IDS": "U_TRIAGEM"}):
        import importlib
        import config.triagem_config as tc
        importlib.reload(tc)
        tc.USE_MOCK_USERS = False
        tc.TEST_ALLOW_SELF_APPROVAL = False
        assert tc.is_user_triagem("U_TRIAGEM")
        assert not tc.is_user_triagem("U_OUTRO", "Rafael Martinez")
        assert not tc.is_user_triagem("U_OUTRO", "Aline Del Pezzo (triagem)")


def test_neutraliza_mrkdwn():
    assert neutralizar_mrkdwn("<!channel> veja <https://x.com|Simulador>") == \
        "&lt;!channel&gt; veja &lt;https://x.com|Simulador&gt;"
    assert neutralizar_mrkdwn(neutralizar_mrkdwn("a<b")) == "a&lt;b"
    d = neutralizar_mrkdwn({"obs": "<@U1>", "marcas": ["<!here>"], "n": 3, "link": "https://drive.google.com/x?a=1&b=2"})
    assert d == {"obs": "&lt;@U1&gt;", "marcas": ["&lt;!here&gt;"], "n": 3, "link": "https://drive.google.com/x?a=1&b=2"}


def test_troca_vale_ate_fim_do_dia_em_brasilia():
    import services.substitution_service as ss
    with tempfile.TemporaryDirectory() as d:
        ss.SUBSTITUTIONS_FILE = os.path.join(d, "subs.json")
        ss.registrar_substituicao(ticket_key="T1", approval_key="a1", role_title="Alçada", original_approver_name="Fulano", original_approver_id="",
                                  new_approver_id="U2", new_approver_name="Ciclano",
                                  until_date="2026-11-04", reason="férias", triagem_user_id="U_TRIAGEM")
        # 22h de 04/11 em Brasília = 01h de 05/11 em UTC: a troca ainda deve valer
        utc = datetime(2026, 11, 5, 1, 0, tzinfo=timezone.utc)

        class _DT(datetime):
            @classmethod
            def now(cls, tz=None):
                return utc.astimezone(tz) if tz else utc.replace(tzinfo=None)

        with mock.patch.object(ss, "datetime", _DT):
            assert ss.get_active_substitute("Fulano") is not None


def test_estado_corrompido_nao_vira_vazio():
    import services.ticket_service as ts
    with tempfile.TemporaryDirectory() as d:
        caminho = os.path.join(d, "tickets_state.json")
        with open(caminho, "w", encoding="utf-8") as f:
            f.write('{"T1": {"key": "T1"')  # JSON truncado
        with mock.patch.object(ts, "TICKETS_FILE", caminho):
            try:
                ts.load_tickets()
                assert False, "deveria falhar em vez de devolver {}"
            except json.JSONDecodeError:
                pass
            os.remove(caminho)
            assert ts.load_tickets() == {}  # arquivo ausente continua sendo estado vazio


if __name__ == "__main__":
    test_triagem_so_por_id()
    test_neutraliza_mrkdwn()
    test_troca_vale_ate_fim_do_dia_em_brasilia()
    test_estado_corrompido_nao_vira_vazio()
    print("OK test_revisao2")
