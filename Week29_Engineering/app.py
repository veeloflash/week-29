"""Week 29 local review application, using only the Python standard library."""
import argparse
import json
import secrets
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from core import Store, WorkflowError


ROOT = Path(__file__).resolve().parent


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, store, credentials, **kwargs):
        self.store, self.credentials = store, credentials
        super().__init__(*args, **kwargs)

    def send_json(self, status, value):
        self.send_data(status, json.dumps(value).encode(), "application/json; charset=utf-8")

    def send_data(self, status, body, kind):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            if self.path == "/":
                self.send_data(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/flows":
                self.send_json(200, self.store.list_flows())
            elif self.path == "/api/knowledge":
                self.send_json(200, self.store.inventory())
            else:
                self.send_json(404, {"error": "Page not found."})
        except WorkflowError as error:
            self.send_json(409, {"error": str(error)})

    def do_POST(self):
        try:
            host = self.headers.get("Host")
            if host not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
                raise WorkflowError("Unrecognized host.")
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{host}"}:
                raise WorkflowError("Cross-origin requests are blocked.")
            if self.headers.get_content_type() != "application/json":
                raise WorkflowError("Send JSON.")
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 16384:
                raise WorkflowError("Request is missing or too large.")
            value = json.loads(self.rfile.read(size))
            if not isinstance(value, dict):
                raise WorkflowError("Expected an object.")
            token = self.headers.get("Authorization", "").removeprefix("Bearer ")
            actor = next((name for name, key in self.credentials.items()
                          if secrets.compare_digest(key, token)), None)
            if actor is None:
                self.send_json(403, {"error": "Enter an authorized local access token."})
                return
            if self.path == "/api/create":
                flow = self.store.create(value["question"], actor)
                result = self.store.resume(flow["id"], actor)
            elif self.path == "/api/resume":
                result = self.store.resume(value["id"], actor)
            elif self.path == "/api/review":
                result = self.store.review(value["id"], actor, value["decision"], value["reason"],
                                           value["revision"], value["binding"], value.get("edited"))
            elif self.path == "/api/update":
                result = self.store.ingest(value["document"], actor)
            elif self.path == "/api/rollback":
                self.store.rollback(value["document_id"], value["version"], actor, value["reason"])
                result = {"status": "rolled back"}
            else:
                self.send_json(404, {"error": "Unknown operation."})
                return
            self.send_json(200, result)
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            self.send_json(400, {"error": str(error)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "runtime" / "workflow.sqlite")
    parser.add_argument("--port", type=int, default=8029)
    parser.add_argument("--demo", action="store_true", help="Create a pending workflow and print its evidence.")
    args = parser.parse_args()
    store = Store(args.db)
    store.seed()
    if args.demo:
        flow = store.create("Can Employee A approve Expense X under the current policy?")
        print(json.dumps(store.resume(flow["id"]), indent=2))
        return
    credentials = {name: secrets.token_urlsafe(24) for name in ("user", "reviewer-1", "admin")}
    print("Local demo access tokens, regenerated on each start", flush=True)
    for role, token in credentials.items():
        print(f"{role} = {token}", flush=True)
    with ThreadingHTTPServer(("127.0.0.1", args.port),
                             partial(Handler, store=store, credentials=credentials)) as server:
        print(f"Open http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
