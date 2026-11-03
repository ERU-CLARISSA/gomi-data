"""取得・書き出しの共通部品。"""
import calendar
import json
import socket
from datetime import date
from email.utils import parsedate_to_datetime

import requests
import urllib3.util.connection

# 開発 PC では IPv6 に接続できずタイムアウト待ちになるため IPv4 に固定する（GitHub Actions でも害はない）
urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

UA = {"User-Agent": "gomi-app-data-pipeline (+https://github.com/ERU-CLARISSA/gomi-data)"}


def http_get(url, timeout=60):
    res = requests.get(url, timeout=timeout, headers=UA)
    res.raise_for_status()
    return res


def last_modified(res, default=None):
    """HTTP の Last-Modified を日付（YYYY-MM-DD）で。なければ default。"""
    v = res.headers.get("Last-Modified")
    return parsedate_to_datetime(v).date().isoformat() if v else default


def month_end(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


def dumps(obj):
    """配信用の JSON。キーの順は作った順のまま、空白なし（同じ中身なら同じバイト列になる）。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
