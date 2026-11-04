import json
import os
import urllib.error
import urllib.request

from services.health_service import start_health_server

os.environ.pop("HEALTH_PORT", None)
os.environ["HEALTH_CHECK"] = "/actuator/health"

estado = {"conectado": True}
server = start_health_server(lambda: estado["conectado"], port=0)
url = f"http://127.0.0.1:{server.server_address[1]}"

with urllib.request.urlopen(url + "/health") as r:
    assert r.status == 200 and json.loads(r.read())["status"] == "ok"

with urllib.request.urlopen(url + "/api/v1/health") as r:
    assert r.status == 200
with urllib.request.urlopen(url + "/actuator/health") as r:
    assert r.status == 200

estado["conectado"] = False
try:
    urllib.request.urlopen(url + "/health")
    raise AssertionError("esperava 503")
except urllib.error.HTTPError as e:
    assert e.code == 503

try:
    urllib.request.urlopen(url + "/outra")
    raise AssertionError("esperava 404")
except urllib.error.HTTPError as e:
    assert e.code == 404

del os.environ["HEALTH_CHECK"]
assert start_health_server(lambda: True) is None  # sem HEALTH_PORT nem HEALTH_CHECK: desligado
server.shutdown()
print("SUCCESS: health check validado!")
