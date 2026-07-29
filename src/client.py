import datetime as dt
import os
import re
from typing import Any, Optional

import httpx


COMMON_FIELDS: dict[str, set[str]] = {
    "note": {"metadata"},
    "note_metadata": {"primaryAlias", "title", "description", "tags", "version", "updatedAt", "createdAt", "editedBy", "lastUpdatedBy", "permissions"},
    "note_permissions": {"owner", "sharedToUsers", "sharedToGroups"},
    "media": {"uuid", "fileName", "linkedNoteCount", "username"},
    "revision": {"uuid", "length", "authorUsernames", "title", "tags", "description"},
    "profile": {"username", "displayName"},
    "alias": {"name", "isPrimaryAlias"},
}


def _filter_fields(data: Any, common_set: set[str]) -> Any:
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if k in common_set}
    if isinstance(data, list):
        return [_filter_fields(item, common_set) for item in data]
    return data


def _normalize_datetime(value: str) -> str:
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$', value):
        parsed = dt.datetime.fromisoformat(value)
        parsed = parsed.astimezone(dt.timezone.utc)
        return parsed.strftime('%Y-%m-%d %H:%M:%S')
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', value):
        raise ValueError(
            f"Invalid datetime: {value}. Timezone offset is required. "
            "Must use format: 2026-06-22T15:00:00-04:00"
        )
    return value


def _denormalize_datetime(value: str) -> str:
    if re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$', value):
        parsed = dt.datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.strftime('%Y-%m-%dT%H:%M:%S+00:00')
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z$', value):
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.strftime('%Y-%m-%dT%H:%M:%S+00:00')
    return value


def _denormalize_response(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: _denormalize_response(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_denormalize_response(item) for item in data]
    if isinstance(data, str):
        return _denormalize_datetime(data)
    return data


class HedgeDocClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or os.getenv("HEDGEDOC_BASE_URL", "")).rstrip("/")
        self.public_url = (os.getenv("HEDGEDOC_PUBLIC_URL", "") or self.base_url).rstrip("/")
        if not self.base_url:
            raise ValueError(
                "HedgeDoc URL required. Set HEDGEDOC_BASE_URL env var "
                "or pass base_url."
            )

    def _get_headers(self, api_key: Optional[str] = None) -> dict[str, str]:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    async def request(
        self,
        method: str,
        path: str,
        api_key: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        url = f"{self.base_url}{path}"
        headers = self._get_headers(api_key)
        extra_headers = kwargs.pop("extra_headers", {})
        has_body = "content" in kwargs or "json" in kwargs or "data" in kwargs or "files" in kwargs
        if has_body:
            headers["Content-Type"] = kwargs.pop("content_type", "application/json")
        headers.update(extra_headers)
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.request(method, url, headers=headers, **kwargs)
            if response.status_code >= 400:
                body = response.text[:500]
                raise httpx.HTTPStatusError(
                    f"{response.status_code} {response.reason_phrase} for {method} {path}: {body}",
                    request=response.request, response=response,
                )
            if response.status_code == 204:
                return {}
            if response.headers.get("content-type", "").startswith("application/json"):
                return response.json()
            return {"text": response.text}

    async def get(self, path: str, api_key: Optional[str] = None, **kwargs: Any) -> Any:
        return await self.request("GET", path, api_key, **kwargs)

    async def post(self, path: str, api_key: Optional[str] = None, **kwargs: Any) -> Any:
        return await self.request("POST", path, api_key, **kwargs)

    async def put(self, path: str, api_key: Optional[str] = None, **kwargs: Any) -> Any:
        return await self.request("PUT", path, api_key, **kwargs)

    async def delete(self, path: str, api_key: Optional[str] = None, **kwargs: Any) -> Any:
        return await self.request("DELETE", path, api_key, **kwargs)

    def _add_note_url(self, data: Any) -> Any:
        if not self.public_url:
            return data
        if isinstance(data, list):
            return [self._add_note_url(item) for item in data]
        if isinstance(data, dict):
            note_id = data.get("metadata", {}).get("primaryAlias", "") or data.get("primaryAlias", "")
            if note_id:
                data["note_url"] = f"{self.public_url}/n/{note_id}"
        return data

    def _add_media_url(self, data: Any) -> Any:
        if not self.public_url:
            return data
        if isinstance(data, list):
            return [self._add_media_url(item) for item in data]
        if isinstance(data, dict):
            uuid = data.get("uuid", "")
            if uuid:
                data["media_url"] = f"{self.public_url}/media/{uuid}"
        return data

    def _resolve_media_urls(self, content: str) -> str:
        if not self.public_url:
            return content
        return re.sub(
            r'(?<!/)(?<![a-zA-Z0-9+.-])media/([a-f0-9-]{8,})',
            f'{self.public_url}/media/\\1',
            content
        )

    def _resolve_content_field(self, data: Any) -> Any:
        if not self.public_url:
            return data
        if isinstance(data, dict) and "content" in data and isinstance(data["content"], str):
            data = dict(data)
            data["content"] = self._resolve_media_urls(data["content"])
        return data

    # =========================================================================
    # Notes Domain
    # =========================================================================

    async def create_note(
        self,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        content = payload["content"]
        alias = payload.get("alias", "")
        path = f"/api/v2/notes/{alias}" if alias else "/api/v2/notes"
        data = await self.request(
            "POST", path, api_key,
            content=content,
            extra_headers={"Content-Type": "text/markdown"},
        )
        data = self._resolve_content_field(data)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["note"])
        result = _denormalize_response(data)
        return self._add_note_url(result)

    async def get_note_by_id(
        self,
        note_id: str,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        data = await self.get(f"/api/v2/notes/{note_id}", api_key)
        if data is None:
            raise Exception("Resource not found")
        data = self._resolve_content_field(data)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["note"])
        result = _denormalize_response(data)
        return self._add_note_url(result)

    async def update_note(
        self,
        note_id: str,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        content = payload["content"]
        data = await self.request(
            "PUT", f"/api/v2/notes/{note_id}", api_key,
            content=content,
            extra_headers={"Content-Type": "text/markdown"},
        )
        data = self._resolve_content_field(data)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["note"])
        result = _denormalize_response(data)
        return self._add_note_url(result)

    async def delete_note_by_id(
        self,
        note_id: str,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
    ) -> Any:

        return await self.delete(
            f"/api/v2/notes/{note_id}", api_key,
            json={"keepMedia": payload.get("keepMedia", True)},
        )

    async def get_note_content(
        self,
        note_id: str,
        api_key: Optional[str] = None,
    ) -> str:
        data = await self.get(f"/api/v2/notes/{note_id}/content", api_key)
        if isinstance(data, dict):
            result = data.get("text", "")
        else:
            result = str(data)
        return self._resolve_media_urls(result)

    async def get_note_metadata(
        self,
        note_id: str,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        data = await self.get(f"/api/v2/notes/{note_id}/metadata", api_key)
        if data is None:
            raise Exception("Resource not found")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["note_metadata"])
        result = _denormalize_response(data)
        return self._add_note_url(result)

    async def get_note_permissions(
        self,
        note_id: str,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        data = await self.get(f"/api/v2/notes/{note_id}/metadata/permissions", api_key)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["note_permissions"])
        result = _denormalize_response(data)
        if self.public_url and isinstance(result, dict):
            result["note_url"] = f"{self.public_url}/n/{note_id}"
        return result

    async def set_note_user_permission(
        self,
        note_id: str,
        user_name: str,
        can_edit: bool,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        data = await self.put(
            f"/api/v2/notes/{note_id}/metadata/permissions/users/{user_name}",
            api_key,
            json={"canEdit": can_edit},
        )
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["note_permissions"])
        result = _denormalize_response(data)
        if self.public_url and isinstance(result, dict):
            result["note_url"] = f"{self.public_url}/n/{note_id}"

        return result

    async def remove_note_user_permission(
        self,
        note_id: str,
        user_name: str,
        api_key: Optional[str] = None,
    ) -> Any:
        data = await self.delete(
            f"/api/v2/notes/{note_id}/metadata/permissions/users/{user_name}",
            api_key,
        )
        result = _denormalize_response(data)
        if self.public_url and isinstance(result, dict):
            result["note_url"] = f"{self.public_url}/n/{note_id}"

        return result

    async def set_note_group_permission(
        self,
        note_id: str,
        group_name: str,
        can_edit: bool,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        data = await self.put(
            f"/api/v2/notes/{note_id}/metadata/permissions/groups/{group_name}",
            api_key,
            json={"canEdit": can_edit},
        )
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["note_permissions"])
        result = _denormalize_response(data)
        if self.public_url and isinstance(result, dict):
            result["note_url"] = f"{self.public_url}/n/{note_id}"

        return result

    async def remove_note_group_permission(
        self,
        note_id: str,
        group_name: str,
        api_key: Optional[str] = None,
    ) -> Any:
        data = await self.delete(
            f"/api/v2/notes/{note_id}/metadata/permissions/groups/{group_name}",
            api_key,
        )
        result = _denormalize_response(data)
        if self.public_url and isinstance(result, dict):
            result["note_url"] = f"{self.public_url}/n/{note_id}"

        return result

    async def change_note_owner(
        self,
        note_id: str,
        new_owner: str,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        data = await self.put(
            f"/api/v2/notes/{note_id}/metadata/permissions/owner",
            api_key,
            json={"newOwner": new_owner},
        )
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["note"])
        result = _denormalize_response(data)

        return self._add_note_url(result)

    async def list_note_revisions(
        self,
        note_id: str,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        data = await self.get(f"/api/v2/notes/{note_id}/revisions", api_key)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["revision"])
        return _denormalize_response(data)

    async def get_note_revision_by_id(
        self,
        note_id: str,
        revision_uuid: str,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        data = await self.get(
            f"/api/v2/notes/{note_id}/revisions/{revision_uuid}", api_key,
        )
        if data is None:
            raise Exception("Resource not found")
        data = self._resolve_content_field(data)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["revision"])
        return _denormalize_response(data)

    async def revert_to_revision(
        self,
        note_id: str,
        revision_uuid: str,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        data = await self.put(
            f"/api/v2/notes/{note_id}/revisions/{revision_uuid}/revert",
            api_key,
        )
        data = self._resolve_content_field(data)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["note"])
        result = _denormalize_response(data)
        return self._add_note_url(result)

    async def list_note_media(
        self,
        note_id: str,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        data = await self.get(f"/api/v2/notes/{note_id}/media", api_key)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["media"])
        result = _denormalize_response(data)
        return self._add_media_url(result)

    # =========================================================================
    # Me/Profile Domain
    # =========================================================================

    async def get_my_profile(
        self,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        data = await self.get("/api/v2/me", api_key)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["profile"])
        return _denormalize_response(data)

    async def list_all_my_notes(
        self,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        data = await self.get("/api/v2/me/notes", api_key)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["note_metadata"])
        result = _denormalize_response(data)
        return self._add_note_url(result)

    async def list_all_my_media(
        self,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        data = await self.get("/api/v2/me/media", api_key)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["media"])
        result = _denormalize_response(data)
        return self._add_media_url(result)

    # =========================================================================
    # Media Domain
    # =========================================================================

    async def get_media_by_id(
        self,
        uuid: str,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        data = await self.get(f"/api/v2/media/{uuid}", api_key)
        if data is None:
            raise Exception("Resource not found")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["media"])
        result = _denormalize_response(data)
        return self._add_media_url(result)

    async def delete_media_by_id(
        self,
        uuid: str,
        api_key: Optional[str] = None,
    ) -> Any:
        return await self.delete(f"/api/v2/media/{uuid}", api_key)

    # =========================================================================
    # Alias Domain
    # =========================================================================

    async def add_alias(
        self,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        body = {
            "noteAlias": payload.get("noteIdOrAlias", payload.get("noteAlias", "")),
            "newAlias": payload.get("newAlias", ""),
        }
        data = await self.post("/api/v2/alias", api_key, json=body)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["alias"])
        result = _denormalize_response(data)
        result = self._add_note_url(result)
        return result

    async def make_alias_primary(
        self,
        alias: str,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        data = await self.put(
            f"/api/v2/alias/{alias}", api_key,
            json=payload,
        )
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["alias"])
        result = _denormalize_response(data)
        result = self._add_note_url(result)
        return result

    async def remove_alias(
        self,
        alias: str,
        api_key: Optional[str] = None,
    ) -> Any:
        return await self.delete(f"/api/v2/alias/{alias}", api_key)


