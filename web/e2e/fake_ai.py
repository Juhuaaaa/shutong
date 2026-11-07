"""A stand-in OpenAI-compatible AI for the end-to-end test: reads the fixture names the way a model would.

Usage: python e2e/fake_ai.py <port>
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import re
import sys

TITLES = {"迷宫饭": "迷宫饭", "極道超女": "極道超女", "[大王饶命][Chap.001-Chap.002]": "大王饶命"}


def recognize(payload):
    folder = payload["folder"]
    known = folder in TITLES
    series = {"id": "s1", "title": TITLES.get(folder, folder or "?"), "edition": None, "search_titles": [],
              "confidence": 0.97 if known else 0.3, "reason": "目录名就是书名" if known else "看不出书名"}
    files = []
    for name in payload["files"]:
        leading = re.match(r"^(\d{4}) ", name)
        number = re.search(r"(\d+)\D*$", name.rsplit(".", 1)[0])
        files.append({"name": name, "series": "s1", "unit": "chapter" if leading else "volume",
                      "number": str(int(leading.group(1) if leading else number.group(1))) if (leading or number) else None,
                      "end": None, "label": "", "confidence": 0.95})
    return {"series": [series], "files": files}


def choose(payload):
    candidates = payload["candidates"]
    return {"subject_id": candidates[0]["subject_id"] if candidates else None, "confidence": 0.9, "reason": "第一个候选"}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        system, payload = body["messages"][0]["content"], json.loads(body["messages"][1]["content"])
        answer = choose(payload) if "candidates" in payload else recognize(payload)
        data = json.dumps({"choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}}]},
                          ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
