"""build.run：取得に失敗した元の地域は、公開中の前回のファイルを使い続ける。"""
import functools
import http.server
import json
import sys
import tempfile
import threading
import types
import unittest
from datetime import date
from pathlib import Path

import build

REGION = {
    "schema": "gomi-schedule/1", "id": "99999", "pref": "テスト県", "name": "テスト市", "data_updated": "2026-04-01",
    "sources": [{"name": "テスト", "url": "https://example.jp", "license": "CC BY 4.0"}],
    "categories": {"burnable": {}}, "notes": [],
    "areas": [{"id": "1", "name": "A", "towns": [{"name": "A町"}], "schedules": [
        {"from": "2026-04-01", "to": "2027-03-31", "rules": [{"category": "burnable", "freq": "weekly", "byday": ["MO"]}],
         "exceptions": []}]}],
}


def fake_module(name, convert):
    m = types.ModuleType(f"gomi.sources.{name}")
    m.convert = convert
    sys.modules[m.__name__] = m


class BuildFallbackTest(unittest.TestCase):
    def test_keeps_previous_when_source_fails(self):
        today = date(2026, 11, 3)
        fake_module("_ok", lambda cfg, t: [json.loads(json.dumps(REGION))])
        with tempfile.TemporaryDirectory() as tmp:
            prev, new = Path(tmp, "prev"), Path(tmp, "new")
            build.run(prev, today, sources=[{"id": "test", "module": "_ok"}])
            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(prev))
            handler.log_message = lambda *a: None
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                def broken(cfg, t):
                    raise ConnectionError("取得できない")
                fake_module("_broken", broken)
                report, failed = build.run(new, today, previous_base=f"http://127.0.0.1:{server.server_port}",
                                           sources=[{"id": "test", "module": "_broken"}])
            finally:
                server.shutdown()
                server.server_close()
            self.assertEqual(failed, ["test"])
            index = json.loads((new / "v1/index.json").read_text(encoding="utf-8"))
            self.assertEqual([r["id"] for r in index["regions"]], ["99999"])
            self.assertEqual((new / "v1/regions/99999.json").read_bytes(), (prev / "v1/regions/99999.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
