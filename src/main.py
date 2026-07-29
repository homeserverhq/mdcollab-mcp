import os
import sys
from contextvars import ContextVar
from typing import Any, Optional

from fastmcp import FastMCP, Context
from pydantic import BaseModel, Field
from toon_mcp import json_to_toon

from .client import HedgeDocClient

_current_user_token: ContextVar[Optional[str]] = ContextVar("current_user_token", default=None)


class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode()
            if auth_header.startswith("Bearer "):
                _current_user_token.set(auth_header[7:])
        await self.app(scope, receive, send)


mcp = FastMCP("HedgeDoc-mcp-server")

_client: Optional[HedgeDocClient] = None


def get_client() -> HedgeDocClient:
    global _client
    if _client is None:
        _client = HedgeDocClient()
    return _client


def get_user_token() -> Optional[str]:
    return _current_user_token.get()


ALLOW_ALL_AGGREGATE = os.getenv("ALLOW_ALL_AGGREGATE", "false").lower() in ("true", "1", "yes")
IS_STATEFUL = os.getenv("IS_STATEFUL", "false").lower() in ("true", "1", "yes")

# =============================================================================
# Pydantic Contract Models
# =============================================================================


class CreateNoteParam(BaseModel):
    content: str
    alias: str = ""


class UpdateNoteParam(BaseModel):
    noteIdOrAlias: str
    content: str


class DeleteNoteParam(BaseModel):
    noteIdOrAlias: str
    keepMedia: bool = True


class SetUserPermissionParam(BaseModel):
    noteIdOrAlias: str
    userName: str
    canEdit: bool


class RemoveUserPermissionParam(BaseModel):
    noteIdOrAlias: str
    userName: str


class SetGroupPermissionParam(BaseModel):
    noteIdOrAlias: str
    groupName: str
    canEdit: bool


class RemoveGroupPermissionParam(BaseModel):
    noteIdOrAlias: str
    groupName: str


class ChangeOwnerParam(BaseModel):
    noteIdOrAlias: str
    newOwner: str


class AddAliasParam(BaseModel):
    noteIdOrAlias: str
    newAlias: str


class MakeAliasPrimaryParam(BaseModel):
    alias: str
    primaryAlias: bool


class RemoveAliasParam(BaseModel):
    alias: str


class RevertToRevisionParam(BaseModel):
    noteIdOrAlias: str
    revisionUuid: str

# =============================================================================
# Notes Tools
# =============================================================================


@mcp.tool(tags={"write", "basic", "hedgedoc"})
async def create_note(
    content: str,
    alias: str = "",
    ctx: Context = None,
) -> dict[str, Any]:
    """Create a new note from markdown content.

    Args:
        content: Raw markdown content of the note.
            (e.g. "# Hello\n\nThis is **bold**")
        alias: Optional URL-friendly path for the note.
            (e.g. "my-note") (Default: "")
    """
    params = CreateNoteParam(content=content, alias=alias)
    return await get_client().create_note(
        params.model_dump(exclude_unset=True), get_user_token(),
        include_all_fields=ALLOW_ALL_AGGREGATE
    )


@mcp.tool(tags={"read", "basic", "hedgedoc"})
async def get_note_by_id(
    noteIdOrAlias: str,
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Get a single note by its ID or alias.

    Args:
        noteIdOrAlias: The unique ID or alias of the note.
            (e.g. "qhp871j4gt3zpn7syphe4q6t7m" or "my-alias")
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    return await get_client().get_note_by_id(
        noteIdOrAlias, get_user_token(), include_all_fields=include_all_fields
    )


@mcp.tool(tags={"write", "primary", "hedgedoc"})
async def update_note(
    noteIdOrAlias: str,
    content: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """Update an existing note's content.

    Args:
        noteIdOrAlias: The unique ID or alias of the note to update.
            (e.g. "qhp871j4gt3zpn7syphe4q6t7m")
        content: New raw markdown content.
            (e.g. "# Updated Title\n\nNew content here")
    """
    params = UpdateNoteParam(noteIdOrAlias=noteIdOrAlias, content=content)
    return await get_client().update_note(
        noteIdOrAlias, params.model_dump(exclude_unset=True), get_user_token(),
        include_all_fields=ALLOW_ALL_AGGREGATE
    )


@mcp.tool(tags={"write", "basic", "hedgedoc"})
async def delete_note_by_id(
    noteIdOrAlias: str,
    keepMedia: bool = True,
    ctx: Context = None,
) -> dict[str, Any]:
    """Delete a note by its ID or alias.

    Args:
        noteIdOrAlias: The unique ID or alias of the note to delete.
            (e.g. "qhp871j4gt3zpn7syphe4q6t7m")
        keepMedia: Preserve uploaded media files after deletion: true or false.
            (Default: true)
    """
    params = DeleteNoteParam(noteIdOrAlias=noteIdOrAlias, keepMedia=keepMedia)
    await get_client().delete_note_by_id(
        noteIdOrAlias, params.model_dump(exclude_unset=True), get_user_token()
    )
    return {"deleted": True, "id": noteIdOrAlias}


@mcp.tool(tags={"read", "primary", "hedgedoc"})
async def get_note_content(
    noteIdOrAlias: str,
    ctx: Context = None,
) -> str:
    """Get the raw markdown content of a note.

    Args:
        noteIdOrAlias: The unique ID or alias of the note.
            (e.g. "qhp871j4gt3zpn7syphe4q6t7m")
    """
    return await get_client().get_note_content(noteIdOrAlias, get_user_token())


@mcp.tool(tags={"read", "primary", "hedgedoc"})
async def get_note_metadata(
    noteIdOrAlias: str,
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Get a note's metadata (title, tags, permissions, etc.).

    Args:
        noteIdOrAlias: The unique ID or alias of the note.
            (e.g. "qhp871j4gt3zpn7syphe4q6t7m")
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    return await get_client().get_note_metadata(
        noteIdOrAlias, get_user_token(), include_all_fields=include_all_fields
    )


@mcp.tool(tags={"read", "primary", "hedgedoc"})
async def get_note_permissions(
    noteIdOrAlias: str,
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Get a note's permission settings.

    Args:
        noteIdOrAlias: The unique ID or alias of the note.
            (e.g. "qhp871j4gt3zpn7syphe4q6t7m")
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    return await get_client().get_note_permissions(
        noteIdOrAlias, get_user_token(), include_all_fields=include_all_fields
    )


@mcp.tool(tags={"write", "primary", "hedgedoc"})
async def set_note_user_permission(
    noteIdOrAlias: str,
    userName: str,
    canEdit: bool,
    ctx: Context = None,
) -> dict[str, Any]:
    """Set a user's permission on a note.

    Granting access does NOT add the note to the target user's history or Web UI. The note URL must be shared separately with the user. Ensure to inform the user of this upon completion.

    Args:
        noteIdOrAlias: The unique ID or alias of the note.
            (e.g. "qhp871j4gt3zpn7syphe4q6t7m")
        userName: Username of the user to set permission for.
            (e.g. "alice")
        canEdit: Whether the user can edit the note: true or false.
    """
    params = SetUserPermissionParam(noteIdOrAlias=noteIdOrAlias, userName=userName, canEdit=canEdit)
    return await get_client().set_note_user_permission(
        noteIdOrAlias, userName, canEdit, get_user_token(),
        include_all_fields=ALLOW_ALL_AGGREGATE
    )


@mcp.tool(tags={"write", "primary", "hedgedoc"})
async def remove_note_user_permission(
    noteIdOrAlias: str,
    userName: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """Remove a user's permission from a note.

    Args:
        noteIdOrAlias: The unique ID or alias of the note.
            (e.g. "qhp871j4gt3zpn7syphe4q6t7m")
        userName: Username of the user to remove permission for.
            (e.g. "alice")
    """
    params = RemoveUserPermissionParam(noteIdOrAlias=noteIdOrAlias, userName=userName)
    return await get_client().remove_note_user_permission(
        noteIdOrAlias, userName, get_user_token()
    )


@mcp.tool(tags={"write", "primary", "hedgedoc"})
async def set_note_group_permission(
    noteIdOrAlias: str,
    groupName: str,
    canEdit: bool,
    ctx: Context = None,
) -> dict[str, Any]:
    """Set a group's permission on a note.

    Granting access does NOT add the note to the target user's history or Web UI. The note URL must be shared separately with the user. Ensure to inform the user of this upon completion.

    Args:
        noteIdOrAlias: The unique ID or alias of the note.
            (e.g. "qhp871j4gt3zpn7syphe4q6t7m")
        groupName: Name of the group: _LOGGED_IN or _EVERYONE.
            (e.g. "_EVERYONE")
        canEdit: Whether the group can edit the note: true or false.
    """
    params = SetGroupPermissionParam(noteIdOrAlias=noteIdOrAlias, groupName=groupName, canEdit=canEdit)
    return await get_client().set_note_group_permission(
        noteIdOrAlias, groupName, canEdit, get_user_token(),
        include_all_fields=ALLOW_ALL_AGGREGATE
    )


@mcp.tool(tags={"write", "primary", "hedgedoc"})
async def remove_note_group_permission(
    noteIdOrAlias: str,
    groupName: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """Remove a group's permission from a note.

    Args:
        noteIdOrAlias: The unique ID or alias of the note.
            (e.g. "qhp871j4gt3zpn7syphe4q6t7m")
        groupName: Name of the group: _LOGGED_IN or _EVERYONE.
            (e.g. "_EVERYONE")
    """
    params = RemoveGroupPermissionParam(noteIdOrAlias=noteIdOrAlias, groupName=groupName)
    return await get_client().remove_note_group_permission(
        noteIdOrAlias, groupName, get_user_token()
    )


@mcp.tool(tags={"write", "advanced", "hedgedoc"})
async def change_note_owner(
    noteIdOrAlias: str,
    newOwner: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """Change the owner of a note.

    Granting access does NOT add the note to the target user's history or Web UI. The note URL must be shared separately with the user. Ensure to inform the user of this upon completion.

    Args:
        noteIdOrAlias: The unique ID or alias of the note.
            (e.g. "qhp871j4gt3zpn7syphe4q6t7m")
        newOwner: Username of the new owner.
            (e.g. "alice")
    """
    params = ChangeOwnerParam(noteIdOrAlias=noteIdOrAlias, newOwner=newOwner)
    return await get_client().change_note_owner(
        noteIdOrAlias, newOwner, get_user_token(),
        include_all_fields=ALLOW_ALL_AGGREGATE
    )


@mcp.tool(tags={"write", "advanced", "hedgedoc"})
async def revert_to_revision(
    noteIdOrAlias: str,
    revisionUuid: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """Revert a note to a previous revision.

    Fetches the specified revision's content and overwrites the note with it.

    Args:
        noteIdOrAlias: The unique ID or alias of the note.
            (e.g. "qhp871j4gt3zpn7syphe4q6t7m")
        revisionUuid: The UUID of the revision to revert to.
            (e.g. "019fa284-0c74-76f5-8306-7262ca465235")
    """
    params = RevertToRevisionParam(noteIdOrAlias=noteIdOrAlias, revisionUuid=revisionUuid)
    return await get_client().revert_to_revision(
        noteIdOrAlias, revisionUuid, get_user_token(),
        include_all_fields=ALLOW_ALL_AGGREGATE
    )


@mcp.tool(tags={"read", "primary", "hedgedoc"})
async def list_note_revisions(
    noteIdOrAlias: str,
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """List all revisions of a note.

    Args:
        noteIdOrAlias: The unique ID or alias of the note.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    data = await get_client().list_note_revisions(
        noteIdOrAlias, get_user_token(),
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False,
    )
    return {"items": json_to_toon(data)}


@mcp.tool(tags={"read", "advanced", "hedgedoc"})
async def get_note_revision_by_id(
    noteIdOrAlias: str,
    revisionUuid: str,
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Get a specific revision of a note by revision UUID.

    Args:
        noteIdOrAlias: The unique ID or alias of the note.
            (e.g. "qhp871j4gt3zpn7syphe4q6t7m")
        revisionUuid: The UUID of the revision to retrieve.
            (e.g. "019fa284-0c74-76f5-8306-7262ca465235")
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    return await get_client().get_note_revision_by_id(
        noteIdOrAlias, revisionUuid, get_user_token(),
        include_all_fields=include_all_fields
    )


@mcp.tool(tags={"read", "primary", "hedgedoc"})
async def list_note_media(
    noteIdOrAlias: str,
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """List all media files attached to a note.

    Args:
        noteIdOrAlias: The unique ID or alias of the note.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    data = await get_client().list_note_media(
        noteIdOrAlias, get_user_token(),
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False,
    )
    return {"items": json_to_toon(data)}

# =============================================================================
# Me/Profile Tools
# =============================================================================


@mcp.tool(tags={"read", "basic", "hedgedoc"})
async def get_my_profile(
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Get the current user's profile information.

    Args:
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    return await get_client().get_my_profile(
        get_user_token(), include_all_fields=include_all_fields
    )


@mcp.tool(tags={"read", "basic", "hedgedoc"})
async def list_all_my_notes(
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """List all notes owned by the current user.

    Args:
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    data = await get_client().list_all_my_notes(
        get_user_token(),
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False,
    )
    return {"items": json_to_toon(data)}


@mcp.tool(tags={"read", "primary", "hedgedoc"})
async def list_all_my_media(
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """List all media files owned by the current user.

    Args:
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    data = await get_client().list_all_my_media(
        get_user_token(),
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False,
    )
    return {"items": json_to_toon(data)}

# =============================================================================
# Media Tools
# =============================================================================


@mcp.tool(tags={"read", "primary", "hedgedoc"})
async def get_media_by_id(
    uuid: str,
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Get a single media file by its UUID.

    Args:
        uuid: The UUID of the media file.
            (e.g. "550e8400-e29b-41d4-a716-446655440000")
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    return await get_client().get_media_by_id(
        uuid, get_user_token(), include_all_fields=include_all_fields
    )


@mcp.tool(tags={"write", "primary", "hedgedoc"})
async def delete_media_by_id(
    uuid: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """Delete a media file by its UUID.

    Args:
        uuid: The UUID of the media file to delete.
            (e.g. "550e8400-e29b-41d4-a716-446655440000")
    """
    await get_client().delete_media_by_id(uuid, get_user_token())
    return {"deleted": True, "id": uuid}

# =============================================================================
# Alias Tools
# =============================================================================


@mcp.tool(tags={"write", "primary", "hedgedoc"})
async def add_alias(
    noteIdOrAlias: str,
    newAlias: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """Add an alias (URL-friendly path) to a note.

    Args:
        noteIdOrAlias: The unique ID or alias of the note.
            (e.g. "qhp871j4gt3zpn7syphe4q6t7m")
        newAlias: The new URL-friendly alias to add.
            (e.g. "my-custom-url")
    """
    params = AddAliasParam(noteIdOrAlias=noteIdOrAlias, newAlias=newAlias)
    return await get_client().add_alias(
        params.model_dump(exclude_unset=True), get_user_token(),
        include_all_fields=ALLOW_ALL_AGGREGATE
    )


@mcp.tool(tags={"write", "advanced", "hedgedoc"})
async def make_alias_primary(
    alias: str,
    primaryAlias: bool,
    ctx: Context = None,
) -> dict[str, Any]:
    """Set an alias as primary or non-primary.

    Args:
        alias: The alias name to update.
            (e.g. "my-custom-url")
        primaryAlias: Whether this alias should be the primary alias: true or false.
    """
    params = MakeAliasPrimaryParam(alias=alias, primaryAlias=primaryAlias)
    return await get_client().make_alias_primary(
        alias, params.model_dump(exclude_unset=True), get_user_token(),
        include_all_fields=ALLOW_ALL_AGGREGATE
    )


@mcp.tool(tags={"write", "primary", "hedgedoc"})
async def remove_alias(
    alias: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """Remove an alias from a note.

    Args:
        alias: The alias name to remove.
            (e.g. "my-custom-url")
    """
    params = RemoveAliasParam(alias=alias)
    await get_client().remove_alias(alias, get_user_token())
    return {"deleted": True, "id": alias}

# =============================================================================
# Entry Point
# =============================================================================


def main():
    if not os.getenv("HEDGEDOC_BASE_URL"):
        print("ERROR: HEDGEDOC_BASE_URL environment variable is required", file=sys.stderr)
        print("Example: export HEDGEDOC_BASE_URL=http://hedgedoc-backend:3000", file=sys.stderr)
        sys.exit(1)

    port_env = os.getenv("MCP_SERVER_PORT")
    if not port_env:
        print("ERROR: MCP_SERVER_PORT environment variable is required", file=sys.stderr)
        print("Example: export MCP_SERVER_PORT=5381", file=sys.stderr)
        sys.exit(1)

    host = "0.0.0.0"
    port = int(port_env)
    path = "/mcp"
    if IS_STATEFUL:
        app = mcp.http_app(path=path)
    else:
        app = mcp.http_app(path=path, stateless_http=True)
    app = AuthMiddleware(app)
    print(f"Starting HedgeDoc MCP server on http://{host}:{port}{path}", file=sys.stderr)
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
