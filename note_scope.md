# Note Scope — Implementation Plan

## Overview

Add a `scope` query parameter to `GET /me/notes` that returns notes from different access scopes: `my`, `shared`, `public`, `pinned`. Default is `my` for backward compatibility.

---

## Backend: `hedgedoc-backend`

### 1. `backend/src/notes/note.service.ts`

**Add `NoteScope` enum:**

```typescript
export enum NoteScope {
  MY = 'my',
  SHARED = 'shared',
  PUBLIC = 'public',
  PINNED = 'pinned',
}
```

**New imports:**

```typescript
import { SpecialGroup } from '@hedgedoc/commons';
import {
  TableNoteGroupPermission,
  FieldNameNoteGroupPermission,
} from '@hedgedoc/database';
import {
  TableNoteUserPermission,
  FieldNameNoteUserPermission,
} from '@hedgedoc/database';
import {
  TableUserPinnedNote,
  FieldNameUserPinnedNote,
} from '@hedgedoc/database';
import { GroupsService } from '../groups/groups.service';
```

**Inject `GroupsService`** (NoteModule already imports GroupsModule):

```typescript
constructor(
    // ... existing injections ...
    private groupsService: GroupsService,
) { }
```

**New methods:**

```typescript
async getSharedNoteIds(userId: number): Promise<number[]> {
    const result = await this.knex(TableNoteUserPermission)
        .select(FieldNameNoteUserPermission.noteId)
        .where(FieldNameNoteUserPermission.userId, userId);
    return result.map((row) => row[FieldNameNoteUserPermission.noteId]);
}

async getPublicNoteIds(): Promise<number[]> {
    const everyoneGroupId = await this.groupsService.getGroupIdByName(SpecialGroup.EVERYONE);
    const result = await this.knex(TableNote)
        .join(
            TableNoteGroupPermission,
            `${TableNote}.${FieldNameNote.id}`,
            `${TableNoteGroupPermission}.${FieldNameNoteGroupPermission.noteId}`,
        )
        .select(`${TableNote}.${FieldNameNote.id}`)
        .where(`${TableNoteGroupPermission}.${FieldNameNoteGroupPermission.groupId}`, everyoneGroupId)
        .andWhere(`${TableNote}.${FieldNameNote.publiclyVisible}`, true);
    return result.map((row) => row[FieldNameNote.id]);
}

async getPinnedNoteIds(userId: number): Promise<number[]> {
    const result = await this.knex(TableUserPinnedNote)
        .select(FieldNameUserPinnedNote.noteId)
        .where(FieldNameUserPinnedNote.userId, userId);
    return result.map((row) => row[FieldNameUserPinnedNote.noteId]);
}
```

**Dispatch method:**

```typescript
async getNoteIdsByScope(scope: NoteScope, userId: number): Promise<number[]> {
    switch (scope) {
        case NoteScope.MY:
            return this.getUserNoteIds(userId);
        case NoteScope.SHARED:
            return this.getSharedNoteIds(userId);
        case NoteScope.PUBLIC:
            return this.getPublicNoteIds();
        case NoteScope.PINNED:
            return this.getPinnedNoteIds(userId);
    }
}
```

---

### 2. `backend/src/api/public/me/me.controller.ts`

**Add imports:**

```typescript
import { Query, BadRequestException } from '@nestjs/common';
import { NoteScope } from '../../../notes/note.service';
```

**Modify `getMyNotes()`:**

```typescript
@Get('notes')
@OpenApi({
    code: 200,
    description: 'Metadata of notes accessible to the user. Scope: my (owned), shared (shared with user), public (public notes), pinned (pinned by user). Default: my.',
    isArray: true,
    schema: NoteMetadataSchema,
})
async getMyNotes(
    @RequestUserId() userId: number,
    @Query('scope') scope: string = 'my',
): Promise<NoteMetadataDto[]> {
    if (!Object.values(NoteScope).includes(scope as NoteScope)) {
        throw new BadRequestException(`Invalid scope: ${scope}. Must be one of: ${Object.values(NoteScope).join(', ')}`);
    }
    const noteIds = await this.notesService.getNoteIdsByScope(scope as NoteScope, userId);
    return await Promise.all(noteIds.map((note) => this.notesService.toNoteMetadataDto(note)));
}
```

---

## MCP Server: `hedgedoc-mcp`

### 3. `src/client.py`

Rename `list_all_my_notes` → `list_notes`, add `scope` parameter:

```python
async def list_notes(
    self,
    scope: str = "my",
    api_key: Optional[str] = None,
    include_all_fields: bool = False,
) -> Any:
    data = await self.get(f"/api/v2/me/notes?scope={scope}", api_key)
    if not include_all_fields:
        data = _filter_fields(data, COMMON_FIELDS["note_metadata"])
    return _denormalize_response(data)
```

### 4. `src/main.py`

Update `list_all_my_notes` tool with `scope` param:

```python
@mcp.tool(tags={"read", "basic", "hedgedoc"})
async def list_all_my_notes(
    scope: str = "my",
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """List notes accessible to the current user.

    Args:
        scope: Which notes to list: "my" (owned), "shared" (shared with me),
            "public" (public notes), "pinned" (pinned notes).
            (Default: "my")
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    data = await get_client().list_notes(
        scope, get_user_token(),
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False,
    )
    return {"items": json_to_toon(data)}
```

### 5. `src/test_runner.py`

Add scope tests after D17 / revert / media-url blocks. Test that each scope returns successfully (even if empty):

```python
# Scope tests for list_all_my_notes
await run_test(session, "D30 list_notes_scope_my", "list_all_my_notes",
               {"scope": "my"})
await run_test(session, "D31 list_notes_scope_shared", "list_all_my_notes",
               {"scope": "shared"})
await run_test(session, "D32 list_notes_scope_public", "list_all_my_notes",
               {"scope": "public"})
await run_test(session, "D33 list_notes_scope_pinned", "list_all_my_notes",
               {"scope": "pinned"})
```

---

## Build & Test Order

1. Edit backend files (note.service.ts, me.controller.ts)
2. Rebuild `hshq/hedgedoc-backend:v2.4` Docker image
3. Restart backend container
4. Edit MCP files (client.py, main.py, test_runner.py)
5. Rebuild `hedgedoc-mcp` Docker image
6. Run tests
