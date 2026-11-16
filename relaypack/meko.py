"""Meko context layer: a thin MCP client plus an offline stand-in with the same methods.

MekoMCP talks to the Meko MCP endpoint (streamable HTTP, JSON-RPC `tools/call`).
LocalMeko keeps everything in memory with keyword scoring so the whole pipeline
and benchmark run without network or keys (its SQL side is SQLite, using only
statements that also run on Meko's Postgres-compatible YSQL). Both expose the
same calls the agents use, so swapping is one constructor.
"""
from __future__ import annotations

import itertools
import json
import os
import re
import sqlite3

_WORD = re.compile(r"[a-z0-9_]+")


def _terms(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2}


class LocalMeko:
    """In-memory stand-in for Meko (knowledge base, conversations, memory, artifacts, trace)."""

    def __init__(self) -> None:
        self.kb: list[dict] = []
        self.messages: list[dict] = []
        self.memories: list[dict] = []
        self.artifacts: dict[str, str] = {}
        self.usage: list[dict] = []
        self.decisions: list[dict] = []
        self._ids = itertools.count(1)
        self._db = sqlite3.connect(":memory:")
        self._db.row_factory = sqlite3.Row

    @staticmethod
    def _rank(items, query, k):
        q = _terms(query)
        scored = [(len(q & _terms(i["text"])), n, i) for n, i in enumerate(items)]
        scored = [s for s in scored if s[0] > 0]
        scored.sort(key=lambda s: (-s[0], -s[1]))
        return [s[2] for s in scored[:k]]

    def knowledgebase_add(self, text: str, source: str) -> None:
        for para in [p for p in text.split("\n") if p.strip()]:
            self.kb.append({"text": para, "source": source})

    def knowledgebase_search(self, query: str, k: int = 4) -> list[str]:
        return [i["text"] for i in self._rank(self.kb, query, k)]

    def conversation_add_message(self, conversation_id: str, agent: str, text: str,
                                 reasoning: str | None = None) -> None:
        self.messages.append({"conv": conversation_id, "agent": agent, "text": text})
        if reasoning:
            self.decisions.append({"conv": conversation_id, "agent": agent, "reasoning": reasoning})

    def context_search(self, conversation_id: str, query: str, k: int = 3) -> list[str]:
        own = [m for m in self.messages if m["conv"] == conversation_id]
        return [f"[{m['agent']}] {m['text']}" for m in self._rank(own, query, k)]

    def memory_add(self, text: str, scope: str = "agent") -> str:
        mid = f"mem_{next(self._ids)}"
        if not any(m["text"] == text for m in self.memories):
            self.memories.append({"id": mid, "text": text, "scope": scope})
        return mid

    def memory_promote(self, text: str) -> None:
        for m in self.memories:
            if m["text"] == text:
                m["scope"] = "shared"

    def memory_search(self, query: str, k: int = 3) -> list[str]:
        shared = [m for m in self.memories if m["scope"] == "shared"]
        return [m["text"] for m in self._rank(shared, query, k)]

    def artifact_put(self, name: str, content: str, content_type: str = "text/x-python") -> None:
        self.artifacts[name] = content

    def track_token_usage(self, agent: str, input_tokens: int, output_tokens: int) -> None:
        self.usage.append({"agent": agent, "in": input_tokens, "out": output_tokens})

    def reset_memory(self) -> None:
        self.memories.clear()

    def db_write(self, query: str) -> None:
        self._db.executescript(query)

    def db_read(self, query: str) -> list[dict]:
        return [dict(r) for r in self._db.execute(query).fetchall()]




class MekoMCP(LocalMeko):
    """Same interface, backed by the Meko MCP server (needs MEKO_API_KEY).

    Tool names and arguments follow the Meko MCP Server reference
    (https://docs.mekodata.ai/reference/mcp-server/, 32 tools, v2.1+: no `scope`
    arguments). Every call names the datapack; the bench uses one datapack,
    created on first run (MEKO_DATAPACK, default "relaypack-bench").
    Only the standard library is used, so it runs anywhere Python does.
    """

    AGENT_ID = "relaypack"

    def __init__(self, url: str | None = None, api_key: str | None = None,
                 datapack: str | None = None) -> None:
        super().__init__()
        self.url = url or os.environ.get("MEKO_MCP_URL", "https://mcp.mekodata.ai/mcp")
        self.key = api_key or os.environ["MEKO_API_KEY"]
        self.session_id: str | None = None
        self.convs: dict[str, str] = {}
        self.memory_ids: dict[str, str] = {}
        self.last_conv: str | None = None
        self.model = os.environ.get("RELAYPACK_MODEL", "claude-opus-5-5")
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "relaypack", "version": "0.2"}})
        self._notify("notifications/initialized")
        self.datapack_id: str | None = None
        self.catalogue = set(self.tools())
        # Every hosted tool call needs a conversation_id for trace nesting, so set-up runs inside one.
        self.last_conv = _id(self._call("conversation_create", agent_id=self.AGENT_ID,
                                        title="relaypack setup"), "conversation_id")
        self.datapack_id = self._datapack(datapack or os.environ.get("MEKO_DATAPACK", "relaypack-bench"))

    # --- transport -------------------------------------------------------
    def _post(self, payload: dict) -> str:
        import urllib.request

        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        import time
        import urllib.error

        data = json.dumps(payload).encode()
        for attempt in range(6):  # the hosted endpoint returns the odd 502/503/timeout under load
            req = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    if sid := r.headers.get("Mcp-Session-Id"):
                        self.session_id = sid
                    return r.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code < 500 and e.code != 429 or attempt == 5:
                    raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt == 5:
                    raise
            time.sleep(min(60, 3 * 2 ** attempt))
        raise RuntimeError("unreachable")

    def _notify(self, method: str) -> None:
        self._post({"jsonrpc": "2.0", "method": method})

    def _rpc(self, method: str, params: dict):
        import time

        for attempt in range(4):  # the gateway sometimes answers 200 with an empty or HTML body
            body = self._post({"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params})
            if body.lstrip().startswith(("event:", "data:")):
                datas = [l[5:].strip() for l in body.splitlines() if l.startswith("data:")]
                body = next((d for d in reversed(datas) if '"result"' in d or '"error"' in d),
                            datas[-1] if datas else "")
            try:
                msg = json.loads(body)
                break
            except ValueError:
                if attempt == 3:
                    raise
                time.sleep(5 * 2 ** attempt)
        if "error" in msg:
            raise RuntimeError(f"Meko {method}: {msg['error']}")
        return msg.get("result") or {}

    def _call(self, tool: str, /, **args) -> dict | list | str:
        args = {k: v for k, v in args.items() if v is not None}
        if tool not in ("datapack_search", "datapack_create", "datapack_list"):
            if self.datapack_id:
                args.setdefault("datapack_id", self.datapack_id)
        if tool != "conversation_create" and self.last_conv:
            args.setdefault("conversation_id", self.last_conv)
        res = self._rpc("tools/call", {"name": tool, "arguments": args})
        if res.get("isError"):
            raise RuntimeError(f"Meko {tool}: {_first_text(res)}")
        out = res.get("structuredContent", _first_text(res))
        if isinstance(out, dict) and set(out) == {"result"}:  # FastMCP wraps non-object results
            out = out["result"]
        if isinstance(out, str):
            try:
                out = json.loads(out)
            except ValueError:
                return out
        if isinstance(out, dict) and isinstance(out.get("error"), str):
            raise RuntimeError(f"Meko {tool}: {out['error']} {out.get('detail', '')}".strip())
        return out

    def tools(self) -> list[str]:
        return [t["name"] for t in self._rpc("tools/list", {}).get("tools", [])]

    # --- setup -----------------------------------------------------------
    def _datapack(self, name: str) -> str:
        found = self._call("datapack_search", name=name, limit=1)
        rows = found.get("datapacks", []) if isinstance(found, dict) else []
        if rows:
            return _id(rows[0])
        return _id(self._call("datapack_create", name=name))

    def _conv(self, logical: str) -> str:
        if logical not in self.convs:
            made = self._call("conversation_create", agent_id=self.AGENT_ID, title=logical, run_id=logical)
            self.convs[logical] = _id(made, "conversation_id")
        self.last_conv = self.convs[logical]
        return self.last_conv

    # --- the calls the agents use ----------------------------------------
    def knowledgebase_add(self, text: str, source: str) -> None:
        import base64
        import hashlib
        import time
        import urllib.request

        data = text.encode("utf-8")
        ticket = self._call("knowledgebase_upload_document", filename=f"{source}.md", size=len(data),
                            content_hash=hashlib.sha256(data).hexdigest(),
                            content_head_base64=base64.b64encode(data[:3072]).decode())
        if not isinstance(ticket, dict) or ticket.get("already_uploaded"):
            return
        url = ticket.get("upload_url") or ticket.get("url")
        fields = ticket.get("fields")
        if fields:  # presigned POST form
            boundary = "relaypack" + hashlib.md5(data).hexdigest()
            parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                     for k, v in fields.items()]
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{source}.md"\r\n'
                         f"Content-Type: text/markdown\r\n\r\n".encode() + data + f"\r\n--{boundary}--\r\n".encode())
            req = urllib.request.Request(url, data=b"".join(parts), method="POST",
                                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        else:
            req = urllib.request.Request(url, data=data, method=ticket.get("method", "PUT"),
                                         headers=ticket.get("headers") or {"Content-Type": "text/markdown"})
        urllib.request.urlopen(req, timeout=60).read()
        key = ticket.get("key") or ticket.get("document_key")
        for _ in range(60):  # wait for indexing so the first search sees the guide
            st = self._call("knowledgebase_document_status", document_key=key)
            state = st.get("state") if isinstance(st, dict) else None
            if state == "completed":
                return
            if state in ("failed", "abandoned", "oversized"):
                raise RuntimeError(f"knowledge upload {state}: {st.get('message')}")
            time.sleep(2)

    def knowledgebase_search(self, query: str, k: int = 4) -> list[str]:
        return _texts(self._call("knowledgebase_search", query=query, limit=k,
                                 agent_id=self.AGENT_ID, conversation_id=self.last_conv))[:k]

    def conversation_add_message(self, conversation_id: str, agent: str, text: str,
                                 reasoning: str | None = None) -> None:
        cid = self._conv(conversation_id)
        if agent == "user":
            self._call("conversation_add_message", conversation_id=cid, agent_id=self.AGENT_ID, input=text, output="")
        else:  # reasoning is the decision trace: why this agent did what it did, shown per turn in the portal
            self._call("conversation_add_message", conversation_id=cid, agent_id=self.AGENT_ID,
                       input=f"hand-off to {agent}", output=f"[{agent}] {text}", reasoning=reasoning,
                       metadata=json.dumps({"agent": agent}))

    def context_search(self, conversation_id: str, query: str, k: int = 3) -> list[str]:
        res = self._call("context_search", query=query, conversation_id=self._conv(conversation_id),
                         agent_id=self.AGENT_ID, limit=k, force_source="conversation")
        return _texts(res.get("conversation", res) if isinstance(res, dict) else res)[:k]

    def memory_add(self, text: str, scope: str = "agent") -> str:  # scope kept for the offline API only
        res = self._call("memory_add", text=text, agent_id=self.AGENT_ID, conversation_id=self.last_conv)
        mid = _id(res, "memory_id") if isinstance(res, (dict, list)) else ""
        if mid:
            self.memory_ids[text] = mid
        return mid

    def memory_promote(self, text: str) -> None:
        if mid := self.memory_ids.get(text):
            self._call("memory_promote", memory_ids=[mid], agent_id=self.AGENT_ID, conversation_id=self.last_conv)

    def memory_search(self, query: str, k: int = 3) -> list[str]:
        return _texts(self._call("memory_search", query=query, limit=k,
                                 agent_id=self.AGENT_ID, conversation_id=self.last_conv))[:k]

    def artifact_put(self, name: str, content: str, content_type: str = "text/x-python") -> None:
        import base64

        self._call("artifact_put", filename=name, content_type=content_type, agent_id=self.AGENT_ID,
                   content_base64=base64.b64encode(content.encode()).decode(), conversation_id=self.last_conv)

    def track_token_usage(self, agent: str, input_tokens: int, output_tokens: int) -> None:
        self._call("track_token_usage", conversation_id=self.last_conv, name=agent, model=self.model,
                   input_tokens=input_tokens, output_tokens=output_tokens,
                   total_tokens=input_tokens + output_tokens)

    def reset_memory(self) -> None:
        """Start each benchmark run with no team lessons, so runs 2..N don't inherit run 1's memory."""
        for _ in range(20):
            res = self._call("memory_delete_all", agent_id=self.AGENT_ID)
            if not isinstance(res, dict) or res.get("complete", True):
                return

    # The hosted MCP may not expose the SQL tools; then the attempt log stays in a local SQLite
    # table with the same schema and is uploaded to the datapack as an artifact by the bench.
    def db_write(self, query: str) -> None:
        if "db_run_write_query" not in self.catalogue:
            return super().db_write(query)
        self._call("db_run_write_query", query=query, conversation_id=self.last_conv)

    def db_read(self, query: str) -> list[dict]:
        if "db_run_read_only_query" not in self.catalogue:
            return super().db_read(query)
        res = self._call("db_run_read_only_query", query=query, conversation_id=self.last_conv)
        return _rows(res)


# --- response helpers ----------------------------------------------------
_TEXT_KEYS = ("memory", "text", "content", "chunk", "output", "snippet", "body")


def _first_text(res: dict) -> str:
    return next((c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"), "")


def _id(obj, *prefer: str) -> str:
    if isinstance(obj, list):
        obj = obj[0] if obj else {}
    if isinstance(obj, dict):
        for key in (*prefer, "id", "datapack_id", "conversation_id", "memory_id"):
            if isinstance(obj.get(key), str):
                return obj[key]
        for v in obj.values():
            if isinstance(v, (dict, list)) and (found := _id(v, *prefer)):
                return found
    return ""


def _texts(obj) -> list[str]:
    """Flatten a search response (any of the bucket/result shapes) into the hit texts, best first."""
    if isinstance(obj, str):
        return [obj] if obj.strip() else []
    if isinstance(obj, list):
        return [t for item in obj for t in _texts(item)]
    if isinstance(obj, dict):
        for key in _TEXT_KEYS:
            if isinstance(obj.get(key), str) and obj[key].strip():
                return [obj[key]]
        for key in ("results", "hits", "items", "memories", "messages", "conversation", "knowledge_base"):
            if key in obj:
                return _texts(obj[key])
    return []


def _rows(obj) -> list[dict]:
    """Rows from a SQL tool response: a list of dicts, or columns + rows."""
    if isinstance(obj, list):
        return [r for r in obj if isinstance(r, dict)]
    if isinstance(obj, dict):
        rows = obj.get("rows") or obj.get("results") or obj.get("data") or []
        cols = obj.get("columns") or obj.get("fields")
        if cols and rows and isinstance(rows[0], (list, tuple)):
            names = [c if isinstance(c, str) else c.get("name") for c in cols]
            return [dict(zip(names, r)) for r in rows]
        return _rows(rows) if isinstance(rows, list) else []
    return []


if __name__ == "__main__":  # python -m relaypack.meko  -> check the live catalogue against what we call
    used = {"datapack_search", "datapack_create", "conversation_create", "conversation_add_message",
            "context_search", "knowledgebase_upload_document", "knowledgebase_document_status",
            "knowledgebase_search", "memory_add", "memory_promote", "memory_search", "artifact_put",
            "track_token_usage", "db_run_write_query", "db_run_read_only_query", "memory_delete_all"}
    m = MekoMCP()
    names = m.catalogue
    print(f"datapack {m.datapack_id}; {len(names)} tools; missing: {sorted(used - names) or 'none'}")
