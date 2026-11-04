"""
Rota HTTP de saúde para a plataforma (Kubernetes) saber se o bot está vivo.
Atende /health, /api/v1/health e o caminho em HEALTH_CHECK (variável que a plataforma da Arco injeta).
Liga com HEALTH_PORT; sem ela, liga na 8501 (porta do template) se HEALTH_CHECK existir. Local, sem nenhuma das duas, nada muda.
Responde 200 enquanto a conexão Socket Mode com o Slack estiver aberta e 503 se cair.
"""

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

logger = logging.getLogger("health_service")


DEFAULT_PLATFORM_PORT = 8501


def _paths() -> set:
    extra = (os.environ.get("HEALTH_CHECK") or "").strip().rstrip("/")
    return {"/health", "/api/v1/health"} | ({extra} if extra else set())


def _make_handler(is_healthy: Callable[[], bool]):
    paths = _paths()

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?")[0].rstrip("/") not in paths:
                self.send_response(404)
                self.end_headers()
                return
            try:
                ok = bool(is_healthy())
            except Exception:
                ok = False
            body = json.dumps({"status": "ok" if ok else "disconnected"}).encode()
            self.send_response(200 if ok else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    return HealthHandler


def start_health_server(is_healthy: Callable[[], bool], port: Optional[int] = None) -> Optional[ThreadingHTTPServer]:
    if port is None:
        raw = (os.environ.get("HEALTH_PORT") or "").strip()
        if raw:
            port = int(raw)
        elif (os.environ.get("HEALTH_CHECK") or "").strip():
            port = DEFAULT_PLATFORM_PORT
        else:
            return None
    server = ThreadingHTTPServer(("0.0.0.0", port), _make_handler(is_healthy))
    threading.Thread(target=server.serve_forever, daemon=True, name="health").start()
    logger.info(f"🩺 Health check ativo em http://0.0.0.0:{server.server_address[1]}/health")
    return server
