"""Заглушка OpenAI-совместимой модели для проверки русского слоя через шлюз.

Отвечает фразой с метками людей из запроса в разных падежах; в потоке режет ответ на куски
по 5 символов, чтобы метки и предлоги рвались между кусками. Последний запрос (тело) пишет
в /tmp-файл рядом, чтобы видеть, что ушло наверх.

    uv run python docs/ru/mock_upstream.py 8799
"""

from __future__ import annotations

import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LAST = Path(__file__).with_name("mock_last_request.json")
TEMPLATE = (
    "Готово: возврат оформлен для Персоны_Женщины_{a}. Письмо отправил Персоне_Мужчине_{b}, "
    "договор с Персоной_Мужчиной_{b} в силе. Уважаемая Персона_Женщина_{a}! Думаю о "
    "Персоне_Женщине_{a}. Встречался с Персоной_Женщиной_{a}."
)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # quiet
        pass

    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        LAST.write_text(json.dumps(body, ensure_ascii=False, indent=1))
        text = json.dumps(
            [m for m in body["messages"] if m["role"] != "system"], ensure_ascii=False
        )
        ids = {}
        for m in re.finditer(r"Персон\w*?_(Мужчин|Женщин)\w*?_([0-9a-f]{4,})", text):
            ids.setdefault(m.group(1), m.group(2))
        answer = TEMPLATE.format(a=ids.get("Женщин", "none"), b=ids.get("Мужчин", "none"))
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for i in range(0, len(answer), 5):
                chunk = {
                    "id": "c1",
                    "object": "chat.completion.chunk",
                    "model": "mock",
                    "choices": [
                        {"index": 0, "delta": {"content": answer[i : i + 5]}, "finish_reason": None}
                    ],
                }
                self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
            done = {
                "id": "c1",
                "object": "chat.completion.chunk",
                "model": "mock",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            self.wfile.write(f"data: {json.dumps(done)}\n\ndata: [DONE]\n\n".encode())
            return
        out = {
            "id": "c1",
            "object": "chat.completion",
            "model": "mock",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        data = json.dumps(out, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
