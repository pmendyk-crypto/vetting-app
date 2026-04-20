from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import json
import os
import urllib.error
import urllib.parse
import urllib.request


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"


class GraphInboxError(RuntimeError):
    pass


@dataclass(frozen=True)
class GraphInboxConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    mailbox: str
    intake_folder: str = "RadFlow Intake"
    processed_folder: str = ""
    failed_folder: str = ""
    import_limit: int = 10

    @property
    def is_configured(self) -> bool:
        return bool(self.tenant_id and self.client_id and self.client_secret and self.mailbox)

    @property
    def missing_names(self) -> list[str]:
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("GRAPH_TENANT_ID")
        if not self.client_id:
            missing.append("GRAPH_CLIENT_ID")
        if not self.client_secret:
            missing.append("GRAPH_CLIENT_SECRET")
        if not self.mailbox:
            missing.append("GRAPH_MAILBOX")
        return missing


def load_graph_inbox_config() -> GraphInboxConfig:
    limit_value = (os.environ.get("GRAPH_IMPORT_LIMIT") or "10").strip()
    try:
        import_limit = max(1, min(50, int(limit_value)))
    except ValueError:
        import_limit = 10
    return GraphInboxConfig(
        tenant_id=(os.environ.get("GRAPH_TENANT_ID") or "").strip(),
        client_id=(os.environ.get("GRAPH_CLIENT_ID") or "").strip(),
        client_secret=(os.environ.get("GRAPH_CLIENT_SECRET") or "").strip(),
        mailbox=(os.environ.get("GRAPH_MAILBOX") or "").strip(),
        intake_folder=(os.environ.get("GRAPH_INTAKE_FOLDER") or "RadFlow Intake").strip() or "RadFlow Intake",
        processed_folder=(os.environ.get("GRAPH_PROCESSED_FOLDER") or "").strip(),
        failed_folder=(os.environ.get("GRAPH_FAILED_FOLDER") or "").strip(),
        import_limit=import_limit,
    )


def _read_json_response(request: urllib.request.Request, timeout: int = 30) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        raise GraphInboxError(f"Microsoft Graph request failed ({exc.code}): {details[:500]}") from exc
    except urllib.error.URLError as exc:
        raise GraphInboxError(f"Microsoft Graph request failed: {exc.reason}") from exc
    if not data:
        return {}
    return json.loads(data.decode("utf-8"))


def _read_bytes_response(request: urllib.request.Request, timeout: int = 30) -> bytes:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        raise GraphInboxError(f"Microsoft Graph request failed ({exc.code}): {details[:500]}") from exc
    except urllib.error.URLError as exc:
        raise GraphInboxError(f"Microsoft Graph request failed: {exc.reason}") from exc


def get_graph_token(config: GraphInboxConfig) -> str:
    if not config.is_configured:
        raise GraphInboxError("Graph inbox is not configured.")
    token_url = f"https://login.microsoftonline.com/{urllib.parse.quote(config.tenant_id)}/oauth2/v2.0/token"
    body = urllib.parse.urlencode(
        {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "scope": GRAPH_SCOPE,
            "grant_type": "client_credentials",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        token_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    payload = _read_json_response(request)
    token = str(payload.get("access_token") or "")
    if not token:
        raise GraphInboxError("Microsoft Graph did not return an access token.")
    return token


def _graph_json(token: str, url: str, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    return _read_json_response(request)


def _graph_bytes(token: str, url: str) -> bytes:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Authorization": f"Bearer {token}", "Accept": "message/rfc822"},
    )
    return _read_bytes_response(request)


def _mailbox_path(config: GraphInboxConfig) -> str:
    return f"{GRAPH_BASE_URL}/users/{urllib.parse.quote(config.mailbox, safe='')}"


def _folder_id_by_name(token: str, config: GraphInboxConfig, folder_name: str) -> str:
    normalized = (folder_name or "").strip()
    if not normalized:
        raise GraphInboxError("Mailbox folder name is blank.")
    if normalized.lower() == "inbox":
        return "inbox"

    query = urllib.parse.urlencode({"$top": "100", "$select": "id,displayName"})
    url = f"{_mailbox_path(config)}/mailFolders?{query}"
    while url:
        payload = _graph_json(token, url)
        for item in payload.get("value", []):
            if str(item.get("displayName") or "").strip().lower() == normalized.lower():
                return str(item.get("id") or "")
        url = payload.get("@odata.nextLink") or ""
    raise GraphInboxError(f"Mailbox folder '{normalized}' was not found for {config.mailbox}.")


def list_intake_messages(token: str, config: GraphInboxConfig) -> tuple[str, list[dict[str, Any]]]:
    folder_id = _folder_id_by_name(token, config, config.intake_folder)
    query = urllib.parse.urlencode(
        {
            "$top": str(config.import_limit),
            "$orderby": "receivedDateTime asc",
            "$select": "id,internetMessageId,subject,from,sender,receivedDateTime,hasAttachments,bodyPreview",
        }
    )
    url = f"{_mailbox_path(config)}/mailFolders/{urllib.parse.quote(folder_id, safe='')}/messages?{query}"
    payload = _graph_json(token, url)
    return folder_id, list(payload.get("value", []))


def fetch_message_mime(token: str, config: GraphInboxConfig, message_id: str) -> bytes:
    encoded_message_id = urllib.parse.quote(message_id, safe="")
    url = f"{_mailbox_path(config)}/messages/{encoded_message_id}/$value"
    return _graph_bytes(token, url)


def move_message_to_folder(token: str, config: GraphInboxConfig, message_id: str, folder_name: str) -> str:
    folder_id = _folder_id_by_name(token, config, folder_name)
    encoded_message_id = urllib.parse.quote(message_id, safe="")
    url = f"{_mailbox_path(config)}/messages/{encoded_message_id}/move"
    payload = _graph_json(token, url, method="POST", payload={"destinationId": folder_id})
    return str(payload.get("id") or "")
