# HedgeDoc MCP Multitenant Proxy Server

This repository contains a Model Context Protocol (MCP) server that acts as a
secure, multi-tenant proxy between an AI Assistant and the HedgeDoc backend
API. It exposes **29 MCP tools** covering notes, user profile, history, media,
aliases, and system status.

## Features

- **Identity Passthrough** — Extracts the `Authorization: Bearer <token>` header
  from incoming HTTP requests and forwards it to the HedgeDoc API without
  server-side authentication.
- **Multi-Tenancy** — Uses Python `contextvars` to maintain thread-safe user
  identity isolation, ensuring all AI-driven actions are scoped to the
  authenticated user's permissions.
- **Full HedgeDoc Coverage** — 29 tools mapped to HedgeDoc API endpoints across
  5 resource domains.
- **TOON Optimization** — Bulk list responses are automatically compressed
  using TOON (Token-Optimized Object Notation) to reduce token consumption.
- **Efficient Gets** — GET responses return only commonly used fields by default.
  Full objects are available via an `include_all_fields` flag.
- **Tool Tags** — Every tool is tagged by operation type (read/write), access
  level (basic/primary/advanced), and project namespace for filtering.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `HEDGEDOC_BASE_URL` | Yes | Docker-internal URL of the HedgeDoc API (e.g. `http://hedgedoc-backend:3000`) |
| `MCP_SERVER_PORT` | Yes | Port number the MCP server listens on |
| `ALLOW_ALL_AGGREGATE` | No | When `true`, aggregate listing tools honor the `include_all_fields` parameter. Default `false`. |
| `IS_STATEFUL` | No | When `true`, uses stateful Streamable HTTP with session tracking. Default `false` (stateless). |

## Installation & Local Development

1. Ensure you have Python 3.12+ installed.
2. Install dependencies:
   ```bash
   pip install fastmcp httpx pydantic uvicorn toon-mcp-server
   ```
3. Run the server:
   ```bash
   export HEDGEDOC_BASE_URL=http://localhost:7462
   export MCP_SERVER_PORT=5381
   python -m src.main
   ```

## Docker Deployment

```bash
docker build -t hedgedoc-mcp .
docker rm -f hedgedoc-mcp 2>/dev/null
docker run -d --name hedgedoc-mcp --network dock-ext \
    -p 5381:5381 \
    -e HEDGEDOC_BASE_URL="http://hedgedoc-backend:3000" \
    -e MCP_SERVER_PORT=5381 \
    -e ALLOW_ALL_AGGREGATE=true \
    hedgedoc-mcp
```

The MCP server serves at `http://hedgedoc-mcp:5381/mcp` (Streamable HTTP).

## Test Suite

Run the test suite against a running MCP server:

```bash
API_KEY="<bearer-token>" MCP_SERVER_PORT=5381 python -m src.test_runner
```

## Important Notes

- **`include_all_fields`** — Available on all `get_*` and `list_*` tools.
  Default False returns common fields only. Set True for all fields.
- **TOON Compression** — Bulk list responses are automatically compressed.
- **Raw Markdown** — Note creation and updates use raw markdown body,
  not JSON. The `Content-Type` header is set to `text/markdown`.
- **DELETE with Body** — Note deletion sends a JSON body `{ keepMedia }`
  with the DELETE request.
- **History Entries** — HedgeDoc creates history entries via web UI visits,
  not API calls. History tools work on existing history entries.

## Tool Tags Convention

Every tool has exactly 3 tags:
- **Operation**: `read` (GET) or `write` (create/update/delete)
- **Access**: `basic`, `primary`, or `advanced`
- **Namespace**: `hedgedoc`

## Tool Mapping

### Notes Management (16 tools)

- `create_note` — Create a new note from markdown content
- `get_note_by_id` — Get a single note by ID or alias
- `update_note` — Update an existing note's content
- `delete_note_by_id` — Delete a note by ID or alias
- `get_note_content` — Get raw markdown content of a note
- `get_note_metadata` — Get a note's metadata (title, tags, etc.)
- `get_note_permissions` — Get a note's permission settings
- `update_note_permissions` — Update a note's permission settings
- `set_note_user_permission` — Set a user's permission on a note
- `remove_note_user_permission` — Remove a user's permission from a note
- `set_note_group_permission` — Set a group's permission on a note
- `remove_note_group_permission` — Remove a group's permission from a note
- `change_note_owner` — Change the owner of a note
- `list_note_revisions` — List all revisions of a note
- `get_note_revision_by_id` — Get a specific revision by ID
- `list_note_media` — List all media files attached to a note

### Me / Profile (7 tools)

- `get_my_profile` — Get the current user's profile
- `list_all_history` — List the current user's note history
- `get_history_entry` — Get a single history entry
- `update_history_entry` — Update a history entry's pin status
- `delete_history_entry` — Delete a history entry
- `list_all_my_notes` — List all notes owned by the current user
- `list_all_my_media` — List all media files owned by the current user

### Media (2 tools)

- `get_media_by_id` — Get a single media file by UUID
- `delete_media_by_id` — Delete a media file by UUID

### Alias (3 tools)

- `add_alias` — Add an alias to a note
- `make_alias_primary` — Set an alias as primary or non-primary
- `remove_alias` — Remove an alias from a note

### System (1 tool)

- `check_server_status` — Check the HedgeDoc server status and statistics
