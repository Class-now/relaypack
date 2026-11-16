"""Offline check of the Meko MCP client: run the whole relay against a fake MCP
server that validates every tool call against the documented argument names
(Meko MCP Server reference, 32 tools, v2.1+), so a renamed or retired argument
fails here instead of during the live benchmark.

    python -m unittest tests.test_meko_mcp
"""
import itertools
import json
import unittest

from relaypack import meko as meko_mod
from relaypack.llm import SimLLM
from relaypack.pipeline import Relay
from relaypack.tasks import TASKS

ALLOWED = {  # "Typical inputs" from https://docs.mekodata.ai/reference/mcp-server/
    "datapack_search": {"query", "name", "limit", "cursor", "grant", "sort", "include_total", "conversation_id"},
    "datapack_create": {"name", "conversation_id", "folder_id", "datapack_id"},
    "conversation_create": {"agent_id", "session_id", "datapack_id", "title", "run_id", "metadata"},
    "conversation_add_message": {"conversation_id", "input", "output", "agent_id", "reasoning", "plan",
                                 "metadata", "seed", "datapack_id"},
    "context_search": {"query", "conversation_id", "agent_id", "datapack_id", "limit", "force_source"},
    "knowledgebase_upload_document": {"filename", "size", "content_hash", "content_head_base64",
                                      "conversation_id", "datapack_id"},
    "knowledgebase_document_status": {"document_key", "conversation_id", "datapack_id"},
    "knowledgebase_search": {"query", "conversation_id", "datapack_id", "agent_id", "limit"},
    "memory_add": {"text", "conversation_id", "agent_id", "run_id", "metadata", "messages", "datapack_id"},
    "memory_promote": {"conversation_id", "memory_ids", "agent_id", "datapack_id"},
    "memory_search": {"query", "conversation_id", "agent_id", "limit", "datapack_id", "run_id"},
    "artifact_put": {"filename", "content_base64", "content_type", "conversation_id", "datapack_id", "agent_id"},
    "track_token_usage": {"conversation_id", "name", "input_tokens", "output_tokens", "total_tokens", "model",
                          "message_id", "datapack_id"},
    "memory_delete_all": {"conversation_id", "agent_id", "run_id", "datapack_id"},
    "db_run_write_query": {"datapack_id", "conversation_id", "query"},
    "db_run_read_only_query": {"datapack_id", "conversation_id", "query"},
}


class FakeMeko(meko_mod.MekoMCP):
    HIDDEN: tuple = ()

    def __init__(self):
        self.calls = []
        self.sql = []
        self.reasons = []
        self.store = {"kb": [], "msgs": [], "mem": []}
        self._n = itertools.count(1)
        super().__init__(url="http://fake/mcp", api_key="test")

    def _post(self, payload):
        if "id" not in payload:
            return ""
        result = {}
        if payload["method"] == "tools/call":
            name, args = payload["params"]["name"], payload["params"]["arguments"]
            self.calls.append(name)
            extra = set(args) - ALLOWED[name]
            assert not extra, f"{name}: undocumented args {extra}"
            assert "scope" not in args
            out = self._tool(name, args)
            result = {"content": [{"type": "text", "text": json.dumps(out)}]}
        elif payload["method"] == "tools/list":
            result = {"tools": [{"name": n} for n in ALLOWED if n not in self.HIDDEN]}
        return json.dumps({"jsonrpc": "2.0", "id": payload["id"], "result": result})

    def _tool(self, name, a):
        if name == "datapack_search":
            return {"datapacks": [], "has_more": False}
        if name == "datapack_create":
            return {"datapack_id": "dp_1", "name": a["name"]}
        if name == "conversation_create":
            return {"conversation_id": f"c{next(self._n)}"}
        if name == "knowledgebase_upload_document":
            return {"already_uploaded": True}
        if name == "memory_delete_all":
            self.store["mem"].clear()
            return {"deleted_count": 0, "complete": True}
        if name in ("db_run_write_query", "db_run_read_only_query"):
            self.sql.append(a["query"])
            return {"columns": ["task", "attempts"], "rows": [["t01", 2]]}
        if name == "conversation_add_message":
            if a.get("reasoning"):
                self.reasons.append(a["reasoning"])
            self.store["msgs"].append(a["output"] or a["input"])
            return {"message_id": "m"}
        if name in ("context_search", "knowledgebase_search", "memory_search"):
            pool = self.store["msgs"] if name == "context_search" else self.store["mem"]
            hits = [{"text": t, "score": 1.0} for t in pool[-a.get("limit", 3):]]
            return {"conversation": {"results": hits}} if name == "context_search" else {"results": hits}
        if name == "memory_add":
            self.store["mem"].append(a["text"])
            return {"results": [{"id": f"mem_{next(self._n)}", "memory": a["text"]}]}
        return {"ok": True}


class MekoMCPTest(unittest.TestCase):
    def test_relay_runs_on_documented_calls(self):
        fake = FakeMeko()
        relay = Relay(SimLLM(), "meko", fake)
        results = [relay.run_task(t) for t in TASKS[:4]]
        self.assertTrue(all(r.passed for r in results))
        for tool in ("conversation_add_message", "context_search", "memory_add", "memory_promote",
                     "artifact_put", "track_token_usage", "db_run_write_query"):
            self.assertIn(tool, fake.calls)
        self.assertTrue(fake.memory_ids)
        self.assertTrue(fake.sql[0].startswith("CREATE TABLE IF NOT EXISTS relay_attempts"))
        self.assertTrue(any(q.startswith("INSERT INTO relay_attempts") for q in fake.sql))
        self.assertTrue(any("lesson:" in r for r in fake.reasons))
        self.assertEqual(fake.db_read("SELECT task, attempts FROM x"), [{"task": "t01", "attempts": 2}])

    def test_sql_falls_back_when_hosted_server_lacks_db_tools(self):
        class NoDb(FakeMeko):
            HIDDEN = ("db_run_write_query", "db_run_read_only_query")

        fake = NoDb()
        relay = Relay(SimLLM(), "meko", fake)
        self.assertTrue(all(relay.run_task(t).passed for t in TASKS[:2]))
        self.assertNotIn("db_run_write_query", fake.calls)
        self.assertTrue(fake.db_read("SELECT COUNT(*) AS n FROM relay_attempts")[0]["n"] > 0)

    def test_wrapped_result_and_error(self):
        fake = FakeMeko()
        fake._rpc = lambda m, p: {"structuredContent": {"result": '{"error": "conversation_id_required"}'}}
        with self.assertRaises(RuntimeError):
            fake._call("memory_search", query="x")
        fake._rpc = lambda m, p: {"structuredContent": {"result": '{"results": [{"memory": "m"}]}'}}
        self.assertEqual(meko_mod._texts(fake._call("memory_search", query="x")), ["m"])

    def test_texts_shapes(self):
        self.assertEqual(meko_mod._texts({"results": [{"memory": "a"}, {"text": "b"}]}), ["a", "b"])
        self.assertEqual(meko_mod._texts({"conversation": {"results": [{"content": "c"}]}}), ["c"])


if __name__ == "__main__":
    unittest.main()
