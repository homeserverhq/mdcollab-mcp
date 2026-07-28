# MCP Server Update Plan — New HedgeDoc Backend

This document describes every change needed to make the HedgeDoc MCP proxy server
compatible with the new HedgeDoc backend.

---

## Tool Inventory

| Before | After | Change |
|--------|-------|--------|
| `Notes Core` — 13 | Notes Core — **10** | Remove 3 tools (batch permissions update removed, history split removed) |
| `Notes Permissions` — 7 | Notes Permissions — **6** | Remove `update_note_permissions` (API endpoint gone) |
| `Me / Profile` — 3 | Me / Profile — **3** | No change |
| `History` — 4 | **Removed entirely** | History API does not exist in new backend |
| `System & Media` — 3 | System & Media — **3** | No change |
| **Total 30** | **Total 25** | Net: **-5 tools** |

---

## 1. History API Completely Removed

**Delete 4 tools:**

| Tool | API Endpoint | Status |
|------|-------------|--------|
| `list_all_history` | `GET /api/v2/me/history` | **Remove** |
| `get_history_entry` | `GET /api/v2/me/history/{noteId}` | **Remove** |
| `update_history_entry` | `PUT /api/v2/me/history/{noteId}` | **Remove** |
| `delete_history_entry` | `DELETE /api/v2/me/history/{noteId}` | **Remove** |

The entire `HistoryService`/`HistoryModule`/`HistoryEntry` entity was deleted from the
HedgeDoc backend. No replacement exists. The `noteService.markNoteAsVisited()` in the
private notes controller is the only remaining history-like function and is not exposed
as a public API endpoint.

**Files to change:**
- `src/client.py` — Remove methods: `list_all_history()`, `get_history_entry()`,
  `update_history_entry()`, `delete_history_entry()`
- `src/client.py` — Remove `COMMON_FIELDS["history"]` from the dict
- `src/client.py` — Remove calls to `_touch_note_history()` since history no longer exists
- `src/client.py` — Remove `_touch_note_history()` method entirely
- `src/main.py` — Remove 4 tool function definitions and their Pydantic param models
- `src/test_runner.py` — Remove tests D17, D18, D19
- `README.md` — Remove "History" section, decrease tool count by 4

---

## 2. Batch Permissions Update Removed

**Delete 1 tool:**

| Tool | API Endpoint | Status |
|------|-------------|--------|
| `update_note_permissions` | `PUT /notes/{id}/metadata/permissions` | **Remove** |

The bulk permissions endpoint (`sharedToUsers[]` + `sharedToGroups[]`) no longer exists
in either the public or private API. Only individual per-user and per-group endpoints
remain.

**Files to change:**
- `src/client.py` — Remove `update_note_permissions()` method
- `src/main.py` — Remove `update_note_permissions` tool definition and `UpdateNotePermissionsParam` model
- `src/test_runner.py` — Remove test D4
- `README.md` — Notes Core count drops, remove from tool list

---

## 3. Revision IDs: Numeric → UUID v7 Strings

### Affected Tools

| Tool | Old Param | New Param |
|------|-----------|-----------|
| `list_note_revisions` | Returns `id: number` in each revision | Returns `uuid: string` |
| `get_note_revision_by_id` | `revisionId: int` | `revisionUuid: str` |
| `revert_to_revision` | `revisionId: int` | `revisionUuid: str` |

### Route Change

Old: `GET /api/v2/notes/{id}/revisions/{revisionId}` (numeric ID)
New: `GET /api/v2/notes/{id}/revisions/{revisionUuid}` (UUID v7 string)

Example: `/notes/abc/revisions/5` → `/notes/abc/revisions/019fa284-0c74-76f5-8306-7262ca465235`

### DTO Field Change

Old `RevisionMetadataDto`: `{ id: number, length, authorUsernames, title, tags, ... }`
New `RevisionMetadataSchema`: `{ uuid: string, length, createdAt, authorUsernames, authorGuestUuids, title, description, tags }`

Key changes:
- `id` → `uuid`
- Added `authorGuestUuids` (string array of guest UUIDs)
- Added `description` field
- Removed `anonymousAuthorCount` (replaced by `authorGuestUuids`)
- `edits` array removed from `RevisionDto`

### Files to Change

**`src/client.py`:**
- `COMMON_FIELDS["revision"]`: `"id"` → `"uuid"`, add `"description"`
- `get_note_revision_by_id()`: param `revision_id: int` → `revision_uuid: str`, update URL path
- `revert_to_revision()`: param `revision_id: int` → `revision_uuid: str`, update URL path

**`src/main.py`:**
- `GetNoteRevisionParam`: `revisionId: int` → `revisionUuid: str`
- `RevertToRevisionParam`: `revisionId: int` → `revisionUuid: str`
- Update docstrings for both tools

**`src/test_runner.py`:**
- Update revision-related tests to pass UUID strings instead of numeric IDs

---

## 4. Alias DTO: `primaryAlias` → `isPrimaryAlias`, `noteId` Removed

### Response Change

Old: `{ name: "abc", primaryAlias: true, noteId: "qhp87..." }`
New (`AliasSchema`): `{ name: "abc", isPrimaryAlias: true }`

### Request Body Change

Old: `{ noteIdOrAlias: str, newAlias: str }`
New (`AliasCreateSchema`): `{ noteAlias: str, newAlias: str }`

### Files to Change

**`src/client.py`:**
- `COMMON_FIELDS["alias"]`: `"primaryAlias"` → `"isPrimaryAlias"`, remove `"noteId"`
- `add_alias()`: Map `payload["noteIdOrAlias"]` → `noteAlias` in the request body before sending
- `add_alias()`: `result.get("noteId", "")` fallback — `noteId` no longer in AliasDto, but the fallback `payload.get("noteIdOrAlias", "")` still works
- `make_alias_primary()`: same `noteId` extraction issue (same fallback works)

---

## 5. Media DTO: `noteId` → `linkedNoteCount`

### Response Change

Old: `{ uuid, fileName, noteId, username, createdAt }`
New (`MediaUploadSchema`): `{ uuid, fileName, linkedNoteCount, username (nullable), createdAt }`

### Files to Change

**`src/client.py`:**
- `COMMON_FIELDS["media"]`: `"noteId"` → `"linkedNoteCount"`
- `username` is now nullable — the `_add_media_url` helper doesn't use `username` so no change needed

---

## 6. Profile Response: New Fields

### Response Change

Old `GET /me`: `{ username, displayName }`
New (`LoginUserInfoSchema`): `{ username (nullable), displayName, photoUrl (nullable), email (nullable), authProvider }`

### Files to Change

**`src/client.py`:**
- `COMMON_FIELDS["profile"]`: No breaking change — `_filter_fields` only keeps listed fields
- Optionally add `"photoUrl"`, `"email"`, `"authProvider"` to the set for `include_all_fields` functionality

---

## 7. Note Response: No Standalone `id` Field

### Response Change

Old `NoteDto`: had `id: number` at top level.
New `NoteSchema`: `{ content, metadata: NoteMetadataSchema, editedByAtPosition: [...] }`

`NoteMetadataSchema` has no `id` field — it uses `primaryAlias` as the identifier.

### Files to Change

**`src/client.py`:**
- `_add_note_url()`: `note_id = data.get("metadata", {}).get("id", "")` → `data.get("metadata", {}).get("primaryAlias", "")`
- `_touch_note_history()`: same — passes note_id to `GET /api/v2/notes/{id}` which accepts aliases, so primaryAlias works fine.
- `_touch_note_history()`: entire method will be removed (per #1 above), but the extraction logic in `_add_note_url()` still needs fixing.
- `create_note()`: line ~171: `result.get("metadata", {}).get("id", "")` → `result.get("metadata", {}).get("primaryAlias", "")`

### `NoteMetadataSchema` (for reference — used by list responses too):

```typescript
{
  aliases: string[],
  primaryAlias: string,
  title: string,
  description: string,
  tags: string[],
  version: number,
  updatedAt: string (ISO datetime),
  lastUpdatedBy: string | null,
  createdAt: string (ISO datetime),
  editedBy: string[],
  permissions: NotePermissionsSchema
}
```

---

## 8. Change Owner Response: Different DTO

### Response Change

| | Old | New (Public) | New (Private) |
|---|---|---|---|
| Response type | `NoteDto` | `NoteMetadataDto` | `NotePermissionsDto` |

The public API's `changeOwner` now returns `NoteMetadataDto` instead of `NoteDto`.
The MCP's `change_note_owner` currently filters with `COMMON_FIELDS["note"]` = `{"metadata"}`.
Since `NoteMetadataDto` is a flat object (no `{metadata: {...}}` wrapper), the `{"metadata"}`
filter would produce `{}` (empty dict).

**Fix**: Change filter to use `COMMON_FIELDS["note_metadata"]` for the `change_note_owner` tool.

---

## 9. `_touch_note_history` Removal

Since the history API is completely removed, the `_touch_note_history()` method serves no
purpose. It was called after every write operation to force-create a history entry via
`GET /api/v2/notes/{id}`. Without a history API, these calls are wasted.

**Files to change:**
- `src/client.py` — Remove `_touch_note_history()` method
- Remove all 13+ calls to `await self._touch_note_history(...)` scattered across write methods

---

## 10. Complete File Change List

### `src/client.py`

| Line/Area | What to Do |
|-----------|------------|
| `COMMON_FIELDS["revision"]` | `"id"` → `"uuid"`, add `"description"` |
| `COMMON_FIELDS["media"]` | `"noteId"` → `"linkedNoteCount"` |
| `COMMON_FIELDS["alias"]` | `"primaryAlias"` → `"isPrimaryAlias"`, remove `"noteId"` |
| `COMMON_FIELDS["history"]` | **Remove entire line** |
| `_touch_note_history()` | **Remove entire method** |
| Every `await self._touch_note_history(...)` | **Remove all calls** (search for "touch_note_history") |
| `_add_note_url()` | `metadata.id` → `metadata.primaryAlias` |
| `create_note()` | `metadata.id` → `metadata.primaryAlias` |
| `add_alias()` | Map `noteIdOrAlias` → `noteAlias` in request body |
| `update_note_permissions()` | **Remove entire method** |
| `list_all_history()` | **Remove** |
| `get_history_entry()` | **Remove** |
| `update_history_entry()` | **Remove** |
| `delete_history_entry()` | **Remove** |
| `get_note_revision_by_id()` | Param `revision_id: int` → `revision_uuid: str`; update URL |
| `revert_to_revision()` | Param `revision_id: int` → `revision_uuid: str`; update URL |

### `src/main.py`

| Line/Area | What to Do |
|-----------|------------|
| `GetNoteRevisionParam` | `revisionId: int` → `revisionUuid: str` |
| `RevertToRevisionParam` | `revisionId: int` → `revisionUuid: str` |
| `update_note_permissions` tool | **Remove entire function** |
| `list_all_history` tool | **Remove** |
| `get_history_entry` tool | **Remove** |
| `update_history_entry` tool | **Remove** |
| `delete_history_entry` tool | **Remove** |
| Remove unused imports/models | `UpdateNotePermissionsParam`, `GetHistoryEntryParam`, `UpdateHistoryEntryParam` |

### `src/test_runner.py`

| Test ID | Test Name | What to Do |
|---------|-----------|------------|
| D4 | `update_note_permissions` | **Remove** |
| D9 | `list_note_revisions` | Update to check for `uuid` not `id` |
| D15 | `get_note_revision_by_id` | Change numeric revision ID to UUID string |
| D17 | `get_history_entry` | **Remove** |
| D18 | `update_history_entry` | **Remove** |
| D19 | `delete_history_entry` | **Remove** |

### `README.md`

| Section | What to Do |
|---------|------------|
| Title/header | Tool count: `30` → `25` |
| Features list | Test count: `32` → `27` |
| Notes Core section | Remove `update_note_permissions` from list, count drops from 13 to 10 |
| Notes Permissions section | Count drops from 7 to 6 |
| History section | **Remove entire "History (4 tools)" section** |
| System & Media | Stays at 3 tools |

---

## 11. Summary of Test/Metric Changes

| Metric | Old Value | New Value |
|--------|-----------|-----------|
| MCP Tools | 30 | 25 |
| Tests | 32 | 27 |
| Tool categories | 5 | 4 (history removed) |

---

## 12. Tool Mapping (After Changes)

### Notes Core (10 tools)
- `create_note`
- `get_note_by_id`
- `update_note`
- `delete_note_by_id`
- `get_note_content`
- `get_note_metadata`
- `list_note_media`
- `list_note_revisions`
- `get_note_revision_by_id`
- `revert_to_revision`
- `add_alias`
- `make_alias_primary`
- `remove_alias`

### Notes Permissions (6 tools)
- `get_note_permissions`
- `set_note_user_permission`
- `remove_note_user_permission`
- `set_note_group_permission`
- `remove_note_group_permission`
- `change_note_owner`

### Me / Profile (3 tools)
- `get_my_profile`
- `list_all_my_notes`
- `list_all_my_media`

### System & Media (3 tools)
- `check_server_status`
- `get_media_by_id`
- `delete_media_by_id`

**Total: 25 tools**

---

## 13. Implementation Order

1. `src/client.py` — Field renames, method removals, param type changes, alias body mapping, `_touch_note_history` removal, `_add_note_url` fix
2. `src/main.py` — Tool removals, param model changes
3. `src/test_runner.py` — Test removals, revision test updates
4. `docker build -t hedgedoc-mcp .` + `docker run` + test
5. `README.md` — Update counts, sections, tool list
