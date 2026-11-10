"""Máy chủ giả để thử giao diện trên WebKit: phục vụ shell (bản cũ / mới), /filter, /layout; API trả rỗng."""
import http.server, json, sys, os
from urllib.parse import urlparse
WEB, SHELL, PORT = sys.argv[1], sys.argv[2], int(sys.argv[3])
FILES = {"/": SHELL, "/filter": os.path.join(WEB, "index.html"), "/layout": os.path.join(WEB, "layout.html")}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ct):
        self.send_response(code); self.send_header("Content-Type", ct); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        p = urlparse(self.path).path
        if p in FILES: return self._send(200, open(FILES[p], "rb").read(), "text/html; charset=utf-8")
        if p == "/api/license": return self._send(200, json.dumps(dict(ok=True, permanent=True, machine="TEST")).encode(), "application/json")
        if p == "/api/export/status": return self._send(200, b'{"state":"idle"}', "application/json")
        if p in ("/api/photos", "/api/people", "/api/catalog", "/api/export/history"): return self._send(200, b"[]", "application/json")
        if p.startswith("/api/"): return self._send(200, b"{}", "application/json")
        f = os.path.join(WEB, os.path.basename(p))
        if os.path.isfile(f): return self._send(200, open(f, "rb").read(), "image/png" if f.endswith(".png") else "text/css")
        self._send(404, b"", "text/plain")
    do_POST = do_GET
http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
