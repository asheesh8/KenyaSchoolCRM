"""A small sqlite3-compatible client for a hosted Turso (libSQL) database.

Vercel functions can't keep a SQLite file, so when TURSO_DATABASE_URL and
TURSO_AUTH_TOKEN are set the app talks to Turso over its HTTP API instead.
Only the slice of the sqlite3 interface this project uses is implemented:
connect().execute / executemany / executescript / commit / close, cursors with
fetchone / fetchall / iteration / lastrowid, and rows that behave like
sqlite3.Row (index by position or column name, dict(row)).
Standard library only.
"""

import base64
import json
import urllib.error
import urllib.request


class Error(Exception):
    pass


class Row:
    __slots__ = ("_cols", "_vals", "_idx")

    def __init__(self, cols, vals, idx):
        self._cols, self._vals, self._idx = cols, vals, idx

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return self._vals[key]
        return self._vals[self._idx[key]]

    def keys(self):
        return list(self._cols)

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)


class Cursor:
    def __init__(self, cols, rows, lastrowid, rowcount):
        idx = {c: i for i, c in enumerate(cols)}
        self._rows = [Row(cols, r, idx) for r in rows]
        self.lastrowid = lastrowid
        self.rowcount = rowcount
        self.description = [(c, None, None, None, None, None, None) for c in cols]

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def __iter__(self):
        return iter(self.fetchall())


def _arg(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray)):
        return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode()}
    return {"type": "text", "value": str(v)}


def _val(cell):
    t = cell.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(cell["value"])
    if t == "float":
        return float(cell["value"])
    if t == "blob":
        return base64.b64decode(cell.get("base64", ""))
    return cell.get("value")


class Connection:
    def __init__(self, url, token, timeout=30):
        url = url.strip()
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        self.endpoint = url.rstrip("/") + "/v2/pipeline"
        self.token = token.strip()
        self.timeout = timeout
        self.row_factory = None  # accepted for sqlite3 compatibility; rows are always Row-like

    def _pipeline(self, requests):
        body = json.dumps({"requests": requests + [{"type": "close"}]}).encode()
        req = urllib.request.Request(self.endpoint, data=body, method="POST", headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise Error(f"Turso HTTP {e.code}: {e.read()[:300].decode('utf-8', 'replace')}") from None
        out = []
        for res in data.get("results", [])[:len(requests)]:
            if res.get("type") != "ok":
                raise Error((res.get("error") or {}).get("message", "Turso error"))
            out.append(res["response"])
        return out

    def execute(self, sql, params=()):
        if isinstance(params, dict):
            stmt = {"sql": sql, "named_args": [{"name": f":{k}", "value": _arg(v)} for k, v in params.items()]}
        else:
            stmt = {"sql": sql, "args": [_arg(p) for p in params]}
        res = self._pipeline([{"type": "execute", "stmt": stmt}])[0]["result"]
        cols = [c.get("name") for c in res.get("cols", [])]
        rows = [[_val(c) for c in row] for row in res.get("rows", [])]
        last = res.get("last_insert_rowid")
        return Cursor(cols, rows, int(last) if last not in (None, "") else None, res.get("affected_row_count", 0))

    def executemany(self, sql, seq):
        seq = list(seq)
        for i in range(0, len(seq), 200):
            self._pipeline([{"type": "execute", "stmt": {"sql": sql, "args": [_arg(p) for p in params]}}
                            for params in seq[i:i + 200]])
        return Cursor([], [], None, len(seq))

    def executescript(self, script):
        self._pipeline([{"type": "sequence", "sql": script}])

    def commit(self):
        pass  # every statement commits on its own

    def rollback(self):
        pass

    def close(self):
        pass


def connect(url, token):
    return Connection(url, token)
