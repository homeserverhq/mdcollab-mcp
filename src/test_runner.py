"""
End-to-end test harness for HedgeDoc MCP Server.

Flat unconditional execution — a single unrolled list of tests. No loops
over tests, no conditional gating, no skipping. Every test runs every time.
"""

import asyncio
import json
import os
import sys
import time
import uuid
from typing import Any, Optional

import httpx
from toon_mcp import toon_to_json

MCP_SERVER_PORT = os.environ.get("MCP_SERVER_PORT", "")
API_KEY = os.environ.get("API_KEY", "")
MCP_URL = f"http://localhost:{MCP_SERVER_PORT}/mcp"

MCP_HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
}

rid = uuid.uuid4().hex[:8]

results: list[dict[str, Any]] = []
store: dict[str, Any] = {}


class MCPSession:
    def __init__(self, url: str, headers: dict[str, str]):
        self.url = url
        self.base_headers = {**headers, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        self.session_headers = dict(self.base_headers)
        self.client = httpx.AsyncClient(timeout=120.0)
        self._request_id = 0
        self._session_id: str | None = None

    async def __aenter__(self):
        await self._initialize()
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    @staticmethod
    def _parse_sse(body: str) -> list[dict]:
        messages: list[dict] = []
        data_buf: list[str] = []
        for line in body.splitlines():
            if line.startswith("data: "):
                data_buf.append(line[6:])
            elif line.startswith("data:"):
                data_buf.append(line[5:])
            elif line == "" and data_buf:
                try:
                    messages.append(json.loads("".join(data_buf)))
                except json.JSONDecodeError:
                    pass
                data_buf = []
        if data_buf:
            try:
                messages.append(json.loads("".join(data_buf)))
            except json.JSONDecodeError:
                pass
        return messages

    async def _send_notification(self, method: str, params: dict | None = None) -> None:
        payload = {"jsonrpc": "2.0", "method": method}
        if params:
            payload["params"] = params
        response = await self.client.post(self.url, headers=self.session_headers, json=payload)
        if response.status_code not in (200, 202):
            response.raise_for_status()

    async def _send(self, method: str, params: dict | None = None) -> dict:
        self._request_id += 1
        payload = {"jsonrpc": "2.0", "id": self._request_id, "method": method}
        if params:
            payload["params"] = params
        response = await self.client.post(self.url, headers=self.session_headers, json=payload)
        if response.status_code == 202:
            return {}
        response.raise_for_status()

        sid = response.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid
            self.session_headers = {**self.base_headers, "mcp-session-id": sid}

        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            messages = self._parse_sse(response.text)
            data = messages[0] if messages else {}
        else:
            data = response.json()

        if isinstance(data, list):
            data = data[0]
        if isinstance(data, dict) and "error" in data:
            raise Exception(f"JSON-RPC error: {data['error']}")
        return data.get("result", {})

    async def _initialize(self) -> dict:
        result = await self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "hedgedoc-test-runner", "version": "1.0"},
        })
        await self._send_notification("notifications/initialized")
        return result

    async def list_tools(self) -> list[dict]:
        result = await self._send("tools/list")
        return result.get("tools", result)

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        params = {"name": name}
        if arguments:
            params["arguments"] = arguments
        return await self._send("tools/call", params)


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def is_error(result: dict[str, Any]) -> Optional[str]:
    if "error" in result:
        err = result["error"]
        return err.get("message", str(err))
    if result.get("isError"):
        content = result.get("content", [])
        for c in content:
            if c.get("type") == "text":
                txt = c["text"]
                if txt.startswith("Error calling tool"):
                    return txt.split(":", 1)[1].strip() if ":" in txt else txt
                try:
                    data = json.loads(txt)
                except json.JSONDecodeError:
                    return txt
                if isinstance(data, dict):
                    return data.get("error", txt)
    return None


def extract_content(result: dict[str, Any]) -> Any:
    if result.get("isError"):
        return {}
    content = result.get("content", [])
    for c in content:
        if c.get("type") == "text":
            try:
                return json.loads(c["text"])
            except json.JSONDecodeError:
                return c["text"]
    return result.get("_meta", {})


def get_list_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        for key in ("items", "results", "rows", "tree"):
            if key in data:
                val = data[key]
                if isinstance(val, list):
                    return val
                if isinstance(val, str):
                    try:
                        parsed = toon_to_json(val)
                        if isinstance(parsed, list):
                            return parsed
                        if isinstance(parsed, dict):
                            for inner in ("collectives", "pages", "tags", "data"):
                                if inner in parsed and isinstance(parsed[inner], list):
                                    return parsed[inner]
                    except Exception:
                        pass
        return []
    elif isinstance(data, list):
        return data
    return []


def record_result(label: str, tool: str, ok: bool, detail: Optional[str] = None) -> None:
    log(f"  {'PASS' if ok else 'FAIL'} {label}{': ' + detail if detail else ''}")
    results.append({
        "label": label,
        "tool": tool,
        "status": "PASSED" if ok else "FAILED",
        "reason": detail or None,
    })


async def run_test(session: MCPSession, label: str, tool: str, params: dict[str, Any] = None) -> bool:
    params = params if params else {}
    result = await session.call_tool(tool, params)
    data = extract_content(result)
    store[label] = data
    err = is_error(result)
    record_result(label, tool, err is None, err)
    return err is None


async def verify_deleted(session: MCPSession, label: str, tool: str, params: dict[str, Any]) -> bool:
    result = await session.call_tool(tool, params)
    err = is_error(result)
    err_text = err or ""
    ok = (err is not None) and ("not found" in err_text.lower())
    record_result(label, tool, ok, "record still exists after delete" if not ok else None)
    return ok


def note_id(store: dict[str, Any], key: str) -> str:
    entry = store.get(key, {}) or {}
    meta = entry.get("metadata") or {}
    return meta.get("primaryAlias") or meta.get("id") or entry.get("primaryAlias") or entry.get("id") or "nonexistent"


def make_name(base: str) -> str:
    return f"t{rid}-{base}"


async def main():
    print("# Test Report — HedgeDoc MCP Server")
    print(f"\n**Date**: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
    print(f"**Server**: {MCP_URL}")
    print(f"**Run ID**: {rid}")
    print()

    async with MCPSession(MCP_URL, MCP_HEADERS) as session:
        log("\n=== Tool Discovery ===")
        tools_list = await session.list_tools()
        tool_names = [t["name"] for t in tools_list]
        print(f"**Discovered**: {len(tool_names)} tools")
        log(f"Tools: {', '.join(sorted(tool_names))}")

        # ---- Phase 1: List tests (flat) ----
        await run_test(session, "B2 list_all_my_notes", "list_all_my_notes")
        await run_test(session, "B2 list_all_my_media", "list_all_my_media")

        # ---- Phase 2: CRUD cycle (unrolled) ----
        await run_test(session, "C1 create_note", "create_note", {"content": make_name("Test note content")})
        crud_id = note_id(store, "C1 create_note")
        await run_test(session, "C2 get_note_by_id", "get_note_by_id", {"noteIdOrAlias": crud_id})
        await run_test(session, "C3 update_note", "update_note", {"noteIdOrAlias": crud_id, "content": "# Updated\n\nTest content"})
        await run_test(session, "C4 delete_note_by_id", "delete_note_by_id", {"noteIdOrAlias": crud_id})
        await verify_deleted(session, "C5 verify_delete_note", "get_note_by_id", {"noteIdOrAlias": crud_id})

        # ---- Phase 3: Domain-specific tests (unrolled) ----
        await run_test(session, "D0 create_fixture_note", "create_note", {"content": make_name("Fixture note for domain tests")})
        fixture_id = note_id(store, "D0 create_fixture_note")

        await run_test(session, "D1 get_note_content", "get_note_content", {"noteIdOrAlias": fixture_id})
        await run_test(session, "D2 get_note_metadata", "get_note_metadata", {"noteIdOrAlias": fixture_id})
        await run_test(session, "D3 get_note_permissions", "get_note_permissions", {"noteIdOrAlias": fixture_id})

        await run_test(session, "D17 get_my_profile", "get_my_profile")
        current_username = store.get("D17 get_my_profile", {}).get("username", "")

        await run_test(session, "D4 set_note_user_permission", "set_note_user_permission", {"noteIdOrAlias": fixture_id, "userName": current_username, "canEdit": True})
        await run_test(session, "D7 set_note_group_permission", "set_note_group_permission", {"noteIdOrAlias": fixture_id, "groupName": "_EVERYONE", "canEdit": True})
        await run_test(session, "D8 remove_note_group_permission", "remove_note_group_permission", {"noteIdOrAlias": fixture_id, "groupName": "_EVERYONE"})

        await run_test(session, "D9 list_note_revisions", "list_note_revisions", {"noteIdOrAlias": fixture_id})
        await run_test(session, "D10 list_note_media", "list_note_media", {"noteIdOrAlias": fixture_id})

        alias1 = make_name("alias")
        alias2 = make_name("alias-del")
        await run_test(session, "D11 add_alias", "add_alias", {"noteIdOrAlias": fixture_id, "newAlias": alias1})
        await run_test(session, "D12 add_alias_non_primary", "add_alias", {"noteIdOrAlias": fixture_id, "newAlias": alias2})
        await run_test(session, "D13 make_alias_primary", "make_alias_primary", {"alias": alias1, "primaryAlias": True})
        await run_test(session, "D14 remove_alias", "remove_alias", {"alias": alias2})

        await run_test(session, "D15 change_note_owner", "change_note_owner", {"noteIdOrAlias": fixture_id, "newOwner": current_username})

        rev_uuid = (get_list_items(store.get("D9 list_note_revisions", {})) or [{}])[0].get("uuid", "00000000-0000-0000-0000-000000000000")
        await run_test(session, "D16 get_note_revision_by_id", "get_note_revision_by_id", {"noteIdOrAlias": fixture_id, "revisionUuid": rev_uuid})

        # ---- Scope list tests ----
        await run_test(session, "D30 list_notes_scope_my", "list_all_my_notes")
        await run_test(session, "D31 list_notes_scope_shared", "list_all_shared_notes")
        await run_test(session, "D32 list_notes_scope_public", "list_all_public_notes")
        await run_test(session, "D33 list_notes_scope_pinned", "list_all_pinned_notes")

        # ---- Revert to revision ----
        revert_original = make_name("Revert test original")
        revert_mod = "# Modified\n\n" + make_name("revert mod")
        await run_test(session, "D18 create_revert_note", "create_note", {"content": revert_original})
        revert_id = note_id(store, "D18 create_revert_note")
        await run_test(session, "D18b update_for_revert", "update_note", {"noteIdOrAlias": revert_id, "content": revert_mod})
        await run_test(session, "D18r list_revert_revisions", "list_note_revisions", {"noteIdOrAlias": revert_id})
        revert_rev_uuid = (get_list_items(store.get("D18r list_revert_revisions", {})) or [{}])[-1].get("uuid", "00000000-0000-0000-0000-000000000000")
        await run_test(session, "D18c revert_to_original", "revert_to_revision", {"noteIdOrAlias": revert_id, "revisionUuid": revert_rev_uuid})
        rr_content = extract_content(await session.call_tool("get_note_content", {"noteIdOrAlias": revert_id}))
        rr_actual = str(rr_content) if not isinstance(rr_content, str) else rr_content
        record_result("D18d verify_revert_content", "get_note_content", rr_actual == revert_original, f"expected '{revert_original}', got '{rr_actual}'")
        await run_test(session, "D18z cleanup_revert_note", "delete_note_by_id", {"noteIdOrAlias": revert_id})

        # ---- Media URL resolution ----
        url_content = "# Media URL Test\n\n![](media/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee)\n\nAlready absolute: ![](https://example.com/image.png)"
        await run_test(session, "D19 create_media_url_test_note", "create_note", {"content": url_content})
        media_url_id = note_id(store, "D19 create_media_url_test_note")
        media_content = await _content(session, media_url_id)
        media_actual = str(media_content) if not isinstance(media_content, str) else media_content
        media_ok = ("](media/" not in media_actual) and ("media/" in media_actual)
        media_reason = "relative media URL still present" if "](media/" in media_actual else "no media/ in content"
        record_result("D19b verify_media_url_resolution", "get_note_content", media_ok, media_reason if not media_ok else None)
        await run_test(session, "D19z cleanup_media_url_note", "delete_note_by_id", {"noteIdOrAlias": media_url_id})

        # ---- Media by id ----
        media_uuid = (get_list_items(store.get("B2 list_all_my_media", {})) or [{}])[0].get("uuid", "00000000-0000-0000-0000-000000000000")
        await run_test(session, "D20 get_media_by_id", "get_media_by_id", {"uuid": media_uuid})

        # ---- Cleanup ----
        await run_test(session, "D99 cleanup_fixture_note", "delete_note_by_id", {"noteIdOrAlias": fixture_id})

        # ---- Leak detection ----
        _leak_result = extract_content(await session.call_tool("list_all_my_notes", {}))
        _leak_ids = {it.get("primaryAlias") or it.get("id", "") for it in get_list_items(_leak_result) if isinstance(it, dict) and (it.get("primaryAlias") or it.get("id", "")).startswith(f"t{rid}-")}
        record_result("LEAK no_leaks", "leak_detection", len(_leak_ids) == 0, f"{len(_leak_ids)} leaked test note(s)" if _leak_ids else None)

        # ---- Report ----
        passed = sum(1 for r in results if r["status"] == "PASSED")
        failed = sum(1 for r in results if r["status"] == "FAILED")

        print(f"\n## Summary\n")
        print(f"| Status | Count |")
        print(f"|--------|-------|")
        print(f"| PASSED | {passed} |")
        print(f"| FAILED | {failed} |")

        if passed:
            print(f"\n## PASSED ({passed})\n")
            for r in results:
                if r["status"] == "PASSED":
                    print(f"- `{r['tool']}` — {r['label']}")

        if failed:
            print(f"\n## FAILED ({failed})\n")
            for r in results:
                if r["status"] == "FAILED":
                    print(f"### {r['label']}")
                    print(f"- **Error**: {r['reason']}")
                    print()

        print(f"\n---")
        print(f"**Total tests:** {len(results)} | **PASSED:** {passed} | **FAILED:** {failed}")

        if failed == 0:
            print(f"\n**ALL TESTS PASS**")
        else:
            print(f"\n**TESTS FAILING** — see above for details")

async def _content(session: MCPSession, note_id: str) -> Any:
    return extract_content(await session.call_tool("get_note_content", {"noteIdOrAlias": note_id}))


if __name__ == "__main__":
    asyncio.run(main())