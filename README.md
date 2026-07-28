# HedgeDoc MCP Multitenant Proxy Server

This repository contains a Model Context Protocol (MCP) server that acts
as a secure, multi-tenant proxy between an AI Assistant and the HedgeDoc
backend API. It exposes **24 MCP tools** covering 4 resource domains
with full CRUD and permission management.

## ✨ Features

- **🔑 Identity Passthrough** — Extracts the `Authorization: Bearer <token>`
  header from incoming HTTP requests and forwards it to the HedgeDoc API
  without server-side authentication.
- **👥 Multi-Tenancy** — Uses Python `contextvars` to maintain thread-safe
  user identity isolation, ensuring all AI-driven actions are scoped to
  the authenticated user's permissions.
- **📊 Full HedgeDoc Coverage** — 24 tools mapped to HedgeDoc API endpoints
  across 4 resource domains.
- **⚡ TOON Optimization** — Bulk list responses are automatically compressed
  using TOON (Token-Optimized Object Notation) to reduce token consumption
  and maximize context window efficiency.
- **🚀 Efficient Gets** — GET responses return only commonly used fields by
  default. Full objects are available via an `include_all_fields` flag.
- **🧪 Comprehensive Testing** — 25 automated tests covering all tool
  domains, run via the test runner pipeline.

## 🔧 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `HEDGEDOC_BASE_URL` | Yes | Docker-internal URL of the HedgeDoc API (e.g. `http://hedgedoc-backend:3000`). |
| `MCP_SERVER_PORT` | Yes | Port number the MCP server listens on. |
| `ALLOW_ALL_AGGREGATE` | No | When `true`, aggregate listing tools honor the `include_all_fields` parameter. When `false` (default), the parameter is silently forced to `False` for aggregate list operations. |
| `IS_STATEFUL` | No | When `true`, uses stateful Streamable HTTP with session tracking. When `false` (default), uses stateless mode. |
| `HEDGEDOC_PUBLIC_URL` | No | Public-facing URL for `note_url` in responses. Defaults to `HEDGEDOC_BASE_URL` if not set. |

## 📦 Installation & Local Development

1. Ensure you have Python 3.12+ installed.
2. Install dependencies:
    ```bash
    pip install fastmcp httpx pydantic uvicorn toon-mcp-server
    ```
3. Run the server:
    ```bash
    export HEDGEDOC_BASE_URL=http://localhost:7462
    export HEDGEDOC_PUBLIC_URL=https://hedgedoc.example.com
    export MCP_SERVER_PORT=80
    python -m src.main
    ```

## 🐳 Docker Deployment

Build and run the server using Docker:

```bash
docker build -t hedgedoc-mcp:latest .
docker run -d --name hedgedoc-mcp \
    -e HEDGEDOC_BASE_URL="http://hedgedoc-backend:3000" \
    -e HEDGEDOC_PUBLIC_URL="https://hedgedoc.example.com" \
    -e MCP_SERVER_PORT=80 \
    -e IS_STATEFUL=false \
    hedgedoc-mcp:latest

The MCP server serves at `http://hedgedoc-mcp:80/mcp` (Streamable HTTP).
```

## ⚠️ Important Notes

- **📋 `include_all_fields`** — The `include_all_fields` parameter (available
  on all `get_*` and `list_*` tools) controls whether all available fields
  are included in responses. Defaults to `False` for performance; set to
  `True` only when additional fields are needed.
- **⚡ TOON Compression** — All bulk list responses are automatically
  compressed using TOON to reduce token consumption by 30–60%.
- **📝 Required Fields & Defaults** — Each `create_*` tool requires specific
  key fields. All other fields default to empty strings or reasonable values.
  The owner field is automatically set to the authenticated user for most
  resources.

## 🛠️ API Tool Mapping

The server implements 24 MCP tools organized into the following categories:

### 📄 Notes Core (6 tools)

- `create_note` — Create a new note from markdown content
- `get_note_by_id` — Get a single note by ID or alias
- `update_note` — Update an existing note's content
- `delete_note_by_id` — Delete a note by ID or alias
- `get_note_content` — Get raw markdown content of a note
- `get_note_metadata` — Get a note's metadata (title, tags, etc.)

### 📎 Notes Advanced (7 tools)

- `list_note_media` — List all media files attached to a note
- `list_note_revisions` — List all revisions of a note
- `get_note_revision_by_id` — Get a specific revision by UUID
- `revert_to_revision` — Revert a note to a previous revision
- `add_alias` — Add an alias to a note
- `make_alias_primary` — Set an alias as primary or non-primary
- `remove_alias` — Remove an alias from a note

### 🔐 Notes Permissions (6 tools)

- `get_note_permissions` — Get a note's permission settings
- `set_note_user_permission` — Set a user's permission on a note
- `remove_note_user_permission` — Remove a user's permission from a note
- `set_note_group_permission` — Set a group's permission on a note
- `remove_note_group_permission` — Remove a group's permission from a note
- `change_note_owner` — Change the owner of a note

### 👤 Profile & Media (5 tools)

- `get_my_profile` — Get the current user's profile information
- `list_all_my_notes` — List all notes owned by the current user
- `list_all_my_media` — List all media files owned by the current user
- `get_media_by_id` — Get a single media file by UUID
- `delete_media_by_id` — Delete a media file by UUID
