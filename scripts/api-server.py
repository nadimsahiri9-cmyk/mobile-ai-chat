#!/usr/bin/env python3
"""API serveur pour habib-landing - stats VPS + services"""

import json
import os
import subprocess
import time
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

from collections import deque

HOST = "0.0.0.0"
PORT = 8081
DB_PATH = "/home/node/.n8n/database.sqlite"

# Stockage historique (max 60 points = ~15 min à 15s intervalle)
stats_history = deque(maxlen=60)

N8N_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4NDljOTFiNy05ZGFmLTQ3OWMtYWI3OC1iODAyNmM2NzY1ZjEiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwianRpIjoiNmVhYzg0MjItZDA4OS00MWIzLWI2NGUtMzcxZWFjMTlkNjMyIiwiaWF0IjoxNzgzMjY3NTY1LCJleHAiOjE4OTM0NTYwMDAwMDB9.hurpDl41ZUeQPnf8iQ7ZuXY9q_aBfWb_nWyYrpOzewA"

CONFIG = {
    "openclaw_url": "http://localhost:18789",
    "n8n_url": "http://localhost:5678",
    "n8n_api_v1": "http://localhost:5678/api/v1",
    "gumroad_webhook": "http://localhost:5678/webhook/gumroad-webhook",
    "demo_webhook": "http://localhost:5678/webhook/demo"
}

class APIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        routes = {
            "/api/stats": self.handle_stats,
            "/api/services": self.handle_services,
            "/api/ping": self.handle_ping,
            "/api/n8n/workflows": self.handle_n8n_workflows,
            "/api/stats/history": self.handle_stats_history,
        }
        handler = routes.get(path, self.handle_404)
        handler()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/n8n/activate":
            self.handle_n8n_activate()
        elif path == "/api/n8n/trigger/gumroad":
            self.handle_n8n_trigger("gumroad")
        elif path == "/api/n8n/trigger/demo":
            self.handle_n8n_trigger("demo")
        elif path == "/api/chat":
            self.handle_chat()
        else:
            self.handle_404()

    def json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def handle_ping(self):
        self.json_response({"status": "ok", "timestamp": time.time()})

    def handle_stats(self):
        """Stats système réelles du VPS"""
        stats = {}
        try:
            # Uptime
            out = subprocess.run(["uptime", "-p"], capture_output=True, text=True, timeout=3)
            stats["uptime"] = out.stdout.strip() if out.returncode == 0 else "N/A"

            # Load average
            out = subprocess.run(["cat", "/proc/loadavg"], capture_output=True, text=True, timeout=3)
            load = out.stdout.strip().split() if out.returncode == 0 else ["N/A"]
            stats["load_1m"] = load[0] if len(load) > 0 else "N/A"
            stats["load_5m"] = load[1] if len(load) > 1 else "N/A"
            stats["load_15m"] = load[2] if len(load) > 2 else "N/A"

            # Memory
            out = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=3)
            for line in out.stdout.split("\n"):
                if line.startswith("Mem:"):
                    parts = line.split()
                    stats["mem_total"] = int(parts[1])
                    stats["mem_used"] = int(parts[2])
                    stats["mem_free"] = int(parts[3])
                    stats["mem_pct"] = round(int(parts[2]) / int(parts[1]) * 100, 1)

            # Disk
            out = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=3)
            for line in out.stdout.split("\n"):
                if line.startswith("/dev/"):
                    parts = line.split()
                    stats["disk_total"] = parts[1]
                    stats["disk_used"] = parts[2]
                    stats["disk_free"] = parts[3]
                    stats["disk_pct"] = parts[4]
                elif "overlay" in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        stats["disk_total"] = parts[1]
                        stats["disk_used"] = parts[2]
                        stats["disk_free"] = parts[3]
                        stats["disk_pct"] = parts[4]

            # Docker info (running containers)
            out = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True, timeout=5)
            if out.returncode == 0:
                stats["containers"] = len(out.stdout.strip().split("\n")) if out.stdout.strip() else 0
            else:
                stats["containers"] = "N/A"

        except Exception as e:
            stats["error"] = str(e)

        # Stocker dans l'historique
        stats_history.append({
            "t": time.time(),
            "mem_pct": stats.get("mem_pct", 0),
            "disk_pct": int(stats.get("disk_pct", "0%").replace("%", "") or 0),
            "load_1m": float(stats.get("load_1m", 0))
        })

        self.json_response({"data": stats, "timestamp": time.time()})

    def handle_services(self):
        """Statut des services: OpenClaw, n8n, Caddy"""
        services = {}

        # OpenClaw check
        try:
            import urllib.request
            req = urllib.request.Request(f"{CONFIG['openclaw_url']}/health")
            resp = urllib.request.urlopen(req, timeout=3)
            services["openclaw"] = {"status": "ok", "code": resp.status}
        except Exception as e:
            services["openclaw"] = {"status": "error", "error": str(e)}

        # n8n check
        try:
            req = urllib.request.Request(f"{CONFIG['n8n_url']}/")
            resp = urllib.request.urlopen(req, timeout=3)
            services["n8n"] = {"status": "ok", "code": resp.status}
        except Exception as e:
            services["n8n"] = {"status": "error", "error": str(e)}

        # Caddy check (container)
        try:
            req = urllib.request.Request("http://localhost:8080/")
            resp = urllib.request.urlopen(req, timeout=3)
            services["caddy_container"] = {"status": "ok", "code": resp.status}
        except Exception as e:
            services["caddy_container"] = {"status": "error", "error": str(e)}

        self.json_response({"data": services, "timestamp": time.time()})

    def handle_chat(self):
        """Chat endpoint - envoie le message au webhook n8n Demo pour traitement réel"""
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_len)) if content_len else {}
            msg = body.get("message", "")
            agent = body.get("agent", "Habib")
            
            # Appel au webhook n8n Demo pour traitement
            try:
                req = urllib.request.Request(
                    CONFIG["demo_webhook"],
                    data=json.dumps({"message": msg, "source": "habib-landing", "agent": agent}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                resp = urllib.request.urlopen(req, timeout=10)
                data = json.loads(resp.read().decode())
                reply = data.get("greeting", "") + "\n\n" if data.get("greeting") else ""
                if data.get("body"):
                    reply += f"Message reçu : {json.dumps(data['body'])[:200]}"
                else:
                    reply += f"Message reçu : \"{msg[:80]}...\""
                self.json_response({
                    "reply": reply or "Réponse reçue du workflow n8n.",
                    "agent": agent,
                    "source": "n8n",
                    "n8n_response": data
                })
            except urllib.request.HTTPError as e:
                err = e.read().decode()[:200]
                lower = msg.lower()
                if any(k in lower for k in ["status", "statut", "santé"]):
                    import subprocess
                    out = subprocess.run(["uptime", "-p"], capture_output=True, text=True, timeout=3)
                    uptime = out.stdout.strip() or "N/A"
                    self.json_response({"reply": f"📊 **Statut VPS**\nUptime: {uptime}\n(Données locales - webhook n8n indisponible)", "agent": agent, "source": "local"})
                elif any(k in lower for k in ["workflow", "n8n"]):
                    self.json_response({"reply": "⚡ Va dans l'onglet Workflows pour gérer tes workflows n8n.", "agent": agent, "source": "local"})
                elif any(k in lower for k in ["aide", "help", "commandes"]):
                    self.json_response({"reply": "📋 **Commandes :**\n• `status` → Statut VPS\n• `workflows` → Workflows n8n\n• `disque` → Stockage\n• `uptime` → Charge système\n• `aide` → Cette liste", "agent": agent, "source": "local"})
                else:
                    self.json_response({"reply": f"Message reçu : \"{msg[:80]}...\" n8n momentanément indisponible.", "agent": agent, "source": "local"})
        except Exception as e:
            self.json_response({"error": str(e)}, 400)

    def handle_stats_history(self):
        """Historique des stats (RAM, disque, load)"""
        points = list(stats_history)
        self.json_response({"data": points, "total": len(points)})

    def _n8n_request(self, method, endpoint, data=None):
        """Helper: appelle l'API REST n8n v1"""
        import urllib.request
        url = f"{CONFIG['n8n_api_v1']}{endpoint}"
        headers = {"X-N8N-API-KEY": N8N_API_KEY, "Content-Type": "application/json"}
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        resp = urllib.request.urlopen(req, timeout=5)
        return json.loads(resp.read().decode())

    def handle_n8n_workflows(self):
        """Lister les workflows via l'API REST n8n"""
        try:
            data = self._n8n_request("GET", "/workflows")
            workflows = []
            for w in data.get("data", []):
                workflows.append({
                    "id": w["id"],
                    "name": w["name"],
                    "active": w.get("active", False),
                    "created": w.get("createdAt", "")
                })
            self.json_response({"data": workflows, "total": len(workflows)})
        except Exception as e:
            self.json_response({"error": str(e)}, 500)

    def handle_n8n_activate(self):
        """Activer/désactiver un workflow via l'API REST n8n"""
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_len)) if content_len else {}
            wf_id = body.get("id")
            active = body.get("active", True)
            if not wf_id:
                self.json_response({"error": "id manquant"}, 400)
                return
            action = "activate" if active else "deactivate"
            try:
                result = self._n8n_request("POST", f"/workflows/{wf_id}/{action}")
                self.json_response({"status": "ok", "active": result.get("active", active)})
            except urllib.request.HTTPError as e:
                err_body = e.read().decode()
                self.json_response({"error": err_body}, e.code)
        except Exception as e:
            self.json_response({"error": str(e)}, 500)

    def handle_n8n_trigger(self, wf_name):
        """Déclencher un webhook n8n"""
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len) if content_len > 0 else b"{}"
            
            webhook_url = CONFIG.get(f"{wf_name}_webhook")
            if not webhook_url:
                self.json_response({"error": f"webhook '{wf_name}' inconnu"}, 400)
                return
            
            import urllib.request
            req = urllib.request.Request(
                webhook_url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            resp = urllib.request.urlopen(req, timeout=5)
            self.json_response({"status": "triggered", "webhook": wf_name, "code": resp.status})
        except Exception as e:
            self.json_response({"status": "error", "error": str(e)}, 500)

    def handle_404(self):
        self.json_response({"error": "not found", "paths": ["/api/stats", "/api/services", "/api/ping", "POST /api/webhook/gumroad"]}, 404)

    def log_message(self, format, *args):
        """Silence les logs HTTP"""
        pass

if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), APIHandler)
    print(f"API serveur démarré sur {HOST}:{PORT}")
    print(f"Endpoints: /api/ping /api/stats /api/services POST /api/webhook/gumroad")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
        print("Arrêté")