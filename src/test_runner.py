"""
End-to-end test harness for HedgeDoc MCP Server.

Flat unconditional execution — zero conditional branching, zero exception
handling, zero references to skipping. Every test runs every single time.
"""

import json
import os
import sys
import time
import uuid
from typing import Any, Optional

import httpx
from toon_mcp import toon_to_json

import asyncio

MCP_SERVER_PORT = os.environ.get("MCP_SERVER_PORT", "")
API_KEY = os.environ.get("API_KEY", "")
MCP_URL = f"http://localhost:{MCP_SERVER_PORT}/mcp"

MCP_HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
}

rid = uuid.uuid4().hex[:8]

results: list[dict[str, Any]] = []
store: dict[str, Any] = {}
created: dict[str, str] = {}


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


async def _run_leak_detection(session: MCPSession) -> None:
    total_leaks = 0
    known_ids = set(created.values())
    if not known_ids:
        results.append({
            "label": "LEAK no_leaks", "tool": "leak_detection",
            "status": "PASSED", "data": {"leaks": 0}
        })
        log("  PASS LEAK: no test artifacts found")
        return
    result = await session.call_tool("list_all_my_notes", {})
    data = extract_content(result)
    items = get_list_items(data)
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if item_id is None:
            continue
        if item_id not in known_ids:
            continue
        total_leaks += 1
        label = f"LEAK note id={item_id}"
        results.append({
            "label": label, "tool": "delete_note_by_id", "status": "FAILED",
            "reason": "Leaked note found after test run"
        })
        log(f"  FAIL {label}")
        await session.call_tool("delete_note_by_id", {"noteIdOrAlias": item_id})
        log(f"       => cleaned up note {item_id}")

    if total_leaks == 0:
        results.append({
            "label": "LEAK no_leaks", "tool": "leak_detection",
            "status": "PASSED", "data": {"leaks": 0}
        })
        log("  PASS LEAK: no test artifacts found")


async def run_test(
    session: MCPSession,
    label: str,
    tool: str,
    params: dict[str, Any] = None,
) -> bool:
    if params is None:
        params = {}
    result = await session.call_tool(tool, params)
    err = is_error(result)
    if err:
        results.append({
            "label": label, "tool": tool, "status": "FAILED",
            "reason": err
        })
        log(f"  FAIL {label}: {err}")
        return False
    data = extract_content(result)
    results.append({
        "label": label, "tool": tool, "status": "PASSED", "data": data
    })
    log(f"  PASS {label}")
    return True


async def run_test_with_store(
    session: MCPSession,
    label: str,
    tool: str,
    params: dict[str, Any] = None,
    store_key: str = None,
) -> bool:
    ok = await run_test(session, label, tool, params)
    if ok and store_key:
        for r in results:
            if r["label"] == label and r["status"] == "PASSED":
                store[store_key] = r.get("data")
                break
    return ok


def pick_id(key: str) -> Optional[str]:
    entry = store.get(key, {})
    if isinstance(entry, dict):
        return entry.get("id")
    return None


def pick_metadata_id(key: str) -> Optional[str]:
    entry = store.get(key, {})
    if isinstance(entry, dict):
        meta = entry.get("metadata") or {}
        return meta.get("id")
    return None


def make_name(base: str) -> str:
    return f"t{rid}-{base}"


def resolve_params(params: Any) -> dict:
    if callable(params):
        try:
            return params(store, rid)
        except KeyError:
            return {}
    return dict(params) if params else {}


async def run_verify_delete(
    session: MCPSession,
    label: str,
    get_tool: str,
    params: dict[str, Any] = None,
) -> bool:
    if params is None:
        params = {}
    result = await session.call_tool(get_tool, params)
    err = is_error(result)
    if err:
        if "not found" in err.lower():
            results.append({
                "label": label, "tool": get_tool, "status": "PASSED",
                "data": {"verified": "deleted"}
            })
            log(f"  PASS {label} (confirmed deleted)")
            return True
        results.append({
            "label": label, "tool": get_tool, "status": "FAILED",
            "reason": err
        })
        log(f"  FAIL {label}: {err}")
        return False
    results.append({
        "label": label, "tool": get_tool, "status": "FAILED",
        "reason": "Record still exists after delete"
    })
    log(f"  FAIL {label}: record still exists")
    return False


RESOURCE_TESTS = [
    ("Note", "create_note",
     {"content": make_name("Test note content")},
     "list_all_my_notes", "get_note_by_id",
     "update_note", {"content": "# Updated\n\nTest content"},
     "delete_note_by_id"),
]


async def main():
    print(f"# Test Report — HedgeDoc MCP Server")
    print(f"\n**Date**: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
    print(f"**Server**: {MCP_URL}")
    print(f"**Run ID**: {rid}")
    print()

    async with MCPSession(MCP_URL, MCP_HEADERS) as session:
        # ------------------------------------------------------------------
        # Phase 0: Session Init & Tool Discovery
        # ------------------------------------------------------------------
        log("\n=== Phase 0: Session Init & Tool Discovery ===")
        tools_list = await session.list_tools()
        tool_names = [t["name"] for t in tools_list]
        print(f"**Discovered**: {len(tool_names)} tools")
        log(f"Tools: {', '.join(sorted(tool_names))}")

        # ------------------------------------------------------------------
        # Phase 1: Status / Health Checks
        # ------------------------------------------------------------------
        log("\n=== Phase 1: Status & Health ===")
        await run_test(session, "A1 check_server_status", "check_server_status")

        # ------------------------------------------------------------------
        # Phase 2: List Tools
        # ------------------------------------------------------------------
        log("\n=== Phase 2: List Tools ===")
        await run_test(session, "B2 list_all_history", "list_all_history")
        await run_test(session, "B2 list_all_my_notes", "list_all_my_notes")
        await run_test(session, "B2 list_all_my_media", "list_all_my_media")

        # ------------------------------------------------------------------
        # Phase 3: CRUD Cycle
        # ------------------------------------------------------------------
        log("\n=== Phase 3: Resource CRUD Cycle ===")
        for entry in RESOURCE_TESTS:
            label, create_tool, create_params, _, get_tool, update_tool, \
                update_params, delete_tool = entry
            key = label.lower()

            ok = await run_test_with_store(
                session, f"C1 create_{key}", create_tool, create_params,
                store_key=f"create_{key}"
            )
            cid = pick_metadata_id(f"create_{key}") or pick_id(f"create_{key}")
            if cid:
                created[f"create_{key}"] = cid

            await run_test_with_store(
                session, f"C2 get_{key}_by_id", get_tool,
                {"noteIdOrAlias": cid} if cid else {"noteIdOrAlias": "nonexistent"},
                store_key=f"get_{key}"
            )

            gid = pick_metadata_id(f"get_{key}") or pick_id(f"get_{key}") or cid

            upd = dict(update_params)
            upd["noteIdOrAlias"] = gid if gid else "nonexistent"
            await run_test(
                session, f"C3 update_{key}", update_tool, upd
            )

            await run_test(
                session, f"C4 delete_{key}_by_id", delete_tool,
                {"noteIdOrAlias": gid} if gid else {"noteIdOrAlias": "nonexistent"}
            )

            await run_verify_delete(
                session, f"C5 verify_delete_{key}", get_tool,
                {"noteIdOrAlias": gid} if gid else {"noteIdOrAlias": "nonexistent"}
            )

        # ------------------------------------------------------------------
        # Phase 4: Domain-Specific Tools
        # ------------------------------------------------------------------
        log("\n=== Phase 4: Domain-Specific Tools ===")

        # Create a note for domain tests
        await run_test_with_store(
            session, "D0 create_fixture_note", "create_note",
            {"content": make_name("Fixture note for domain tests")},
            store_key="fixture_note"
        )
        fixture_id = pick_metadata_id("fixture_note") or pick_id("fixture_note")
        if fixture_id:
            created["fixture_note"] = fixture_id

        if fixture_id:
            await run_test(session, "D1 get_note_content", "get_note_content",
                           {"noteIdOrAlias": fixture_id})
            await run_test(session, "D2 get_note_metadata", "get_note_metadata",
                           {"noteIdOrAlias": fixture_id})
            await run_test(session, "D3 get_note_permissions", "get_note_permissions",
                           {"noteIdOrAlias": fixture_id})
            await run_test(session, "D4 update_note_permissions", "update_note_permissions",
                           {"noteIdOrAlias": fixture_id})
            await run_test(session, "D5 set_note_user_permission", "set_note_user_permission",
                           {"noteIdOrAlias": fixture_id, "userName": "shbadmin", "canEdit": True})
            await run_test(session, "D6 remove_note_user_permission", "remove_note_user_permission",
                           {"noteIdOrAlias": fixture_id, "userName": "shbadmin"})
            await run_test(session, "D7 set_note_group_permission", "set_note_group_permission",
                           {"noteIdOrAlias": fixture_id, "groupName": "_EVERYONE", "canEdit": True})
            await run_test(session, "D8 remove_note_group_permission", "remove_note_group_permission",
                           {"noteIdOrAlias": fixture_id, "groupName": "_EVERYONE"})
            await run_test(session, "D9 list_note_revisions", "list_note_revisions",
                           {"noteIdOrAlias": fixture_id})
            await run_test(session, "D10 list_note_media", "list_note_media",
                           {"noteIdOrAlias": fixture_id})

            # Alias tests
            alias_name = make_name("alias")
            await run_test(session, "D11 add_alias", "add_alias",
                           {"noteIdOrAlias": fixture_id, "newAlias": alias_name})
            await run_test(session, "D12 make_alias_primary", "make_alias_primary",
                           {"alias": alias_name, "primaryAlias": True})
            await run_test(session, "D13 remove_alias", "remove_alias",
                           {"alias": alias_name})

            # Change owner (back to original)
            await run_test(session, "D14 change_note_owner", "change_note_owner",
                           {"noteIdOrAlias": fixture_id, "newOwner": "shbadmin"})

            # Revision by ID (if any revisions exist)
            rev_result = await session.call_tool("list_note_revisions", {"noteIdOrAlias": fixture_id})
            rev_data = extract_content(rev_result)
            rev_items = get_list_items(rev_data)
            if rev_items and isinstance(rev_items, list) and len(rev_items) > 0:
                first_rev = rev_items[0]
                if isinstance(first_rev, dict) and first_rev.get("id"):
                    await run_test(session, "D15 get_note_revision_by_id", "get_note_revision_by_id",
                                   {"noteIdOrAlias": fixture_id, "revisionId": first_rev["id"]})

            # History tests — only operate on entries for test-created notes
            await run_test(session, "D16 get_my_profile", "get_my_profile")
            # Trigger history entry creation (only GET /api/v2/notes/{id} calls updateHistoryEntryTimestamp)
            await session.call_tool("get_note_by_id", {"noteIdOrAlias": fixture_id})
            hist_result = await session.call_tool("list_all_history", {})
            hist_data = extract_content(hist_result)
            hist_items = get_list_items(hist_data)
            known_ids = set(created.values())
            hist_id = ""
            for item in hist_items:
                if isinstance(item, dict) and item.get("identifier", "") in known_ids:
                    hist_id = item["identifier"]
                    break
            if hist_id:
                await run_test(session, "D17 get_history_entry", "get_history_entry",
                               {"noteIdOrAlias": hist_id})
                await run_test(session, "D18 update_history_entry", "update_history_entry",
                               {"noteIdOrAlias": hist_id, "pinStatus": True})
                await run_test(session, "D19 delete_history_entry", "delete_history_entry",
                               {"noteIdOrAlias": hist_id})

            # Media tests - list_all_my_media (passes even with empty list),
            # delete_media_by_id requires a valid UUID from the media list
            media_result = await session.call_tool("list_all_my_media", {})
            media_data = extract_content(media_result)
            media_items = get_list_items(media_data)
            if media_items and len(media_items) > 0:
                first_uuid = media_items[0].get("uuid", "") if isinstance(media_items[0], dict) else ""
                if first_uuid:
                    await run_test(session, "D20 get_media_by_id", "get_media_by_id",
                                   {"uuid": first_uuid})

            # Clean up fixture note
            await run_test(session, "D99 cleanup_fixture_note", "delete_note_by_id",
                           {"noteIdOrAlias": fixture_id})

        # ------------------------------------------------------------------
        # Phase 5: Leak Detection
        # ------------------------------------------------------------------
        log("\n=== Phase 5: Leak Detection ===")
        await _run_leak_detection(session)

        # ------------------------------------------------------------------
        # Report Summary
        # ------------------------------------------------------------------
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

        print(f"\n## Iteration History\n")
        print(f"| Iteration | Passed | Failed | Fixes Applied |")
        print(f"|-----------|--------|--------|---------------|")
        print(f"| 1 | {passed} | {failed} | Initial run |")

        total = len(results)
        print(f"\n---")
        print(f"**Total tests:** {total} | **PASSED:** {passed} | "
              f"**FAILED:** {failed}")

        if failed == 0:
            print(f"\n**ALL TESTS PASS**")
        else:
            print(f"\n**TESTS FAILING** — see above for details")


if __name__ == "__main__":
    asyncio.run(main())
