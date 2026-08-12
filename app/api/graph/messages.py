"""v0.8.0 — Microsoft Graph-compatible API for CTS ADMIN.
Endpoints mimic graph.microsoft.com so CTS ADMIN switches only the base URL.

Auth: header X-Cargo360-API-Key (validated against settings.cts_admin_api_key)
"""
from datetime import datetime
from fastapi import APIRouter, Header, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from app.database import get_db
from app.config import get_settings

router = APIRouter()


def require_cts_key(x_cargo360_api_key: Optional[str] = Header(None)):
    """Validate CTS ADMIN API key from settings table."""
    settings = get_settings()
    if not x_cargo360_api_key:
        raise HTTPException(401, "X-Cargo360-API-Key header required")
    if x_cargo360_api_key != settings.cts_admin_api_key:
        raise HTTPException(401, "Invalid API key")
    return x_cargo360_api_key


def _to_graph_message(row) -> dict:
    """Map mailguard.emails row → Graph Message JSON."""
    r = dict(row._mapping)
    return {
        "id": r["graph_message_id"],
        "internetMessageId": r.get("internet_message_id"),
        "conversationId": r.get("conversation_id"),
        "subject": r.get("subject"),
        "from": {
            "emailAddress": {
                "address": r.get("from_address"),
                "name": r.get("from_name"),
            }
        },
        "toRecipients": [
            {"emailAddress": {"address": e}}
            for e in (r.get("to_addresses") or [])
        ],
        "receivedDateTime": r["received_at"].isoformat() if r.get("received_at") else None,
        "body": {
            "contentType": "html" if r.get("body_html") else "text",
            "content": r.get("body_html") or r.get("body_text") or "",
        },
        "hasAttachments": r.get("has_attachments", False),
        "isRead": r.get("is_read", False),
        "importance": r.get("importance") or "normal",
        # Custom Cargo360 extended properties (Graph singleValueExtendedProperties pattern)
        "singleValueExtendedProperties": [
            {"id": "String {66f5a359-4659-4830-9070-00050ec6ac6e} Name Cargo360-PhishingScore",
             "value": str(r.get("phishing_score") or "")},
            {"id": "String {66f5a359-4659-4830-9070-00050ec6ac6e} Name Cargo360-Category",
             "value": str(r.get("category") or "necunoscut")},
            {"id": "String {66f5a359-4659-4830-9070-00050ec6ac6e} Name Cargo360-Status",
             "value": str(r.get("status") or "")},
            {"id": "String {66f5a359-4659-4830-9070-00050ec6ac6e} Name Cargo360-ClientId",
             "value": str(r.get("client_id") or "")},
        ],
    }


@router.get("/v1.0/users/{user_id}/mailFolders/Inbox/messages")
def list_inbox_messages(
    user_id: str,
    top: int = Query(50, alias="$top", ge=1, le=999),
    skip: int = Query(0, alias="$skip", ge=0),
    filter_: Optional[str] = Query(None, alias="$filter"),
    orderby: Optional[str] = Query(None, alias="$orderby"),
    count: Optional[bool] = Query(None, alias="$count"),
    db: Session = Depends(get_db),
    _key: str = Depends(require_cts_key)
):
    """Graph-compatible list endpoint.
    DOAR emailuri cu status='clean' apar prin acest API.
    Format răspuns identic Graph: {@odata.context, value, @odata.nextLink}
    """
    # Base query: only clean emails + ndr (aggregated) for CTS ADMIN consumption
    sql_base = """
        FROM emails
        WHERE status IN ('clean')
    """
    params = {"limit": top, "offset": skip}
    sql = f"""
        SELECT id, graph_message_id, internet_message_id, conversation_id,
               subject, from_address, from_name, to_addresses,
               received_at, body_html, body_text, has_attachments, is_read,
               importance, phishing_score, category, status, client_id
        {sql_base}
        ORDER BY received_at DESC
        LIMIT :limit OFFSET :offset
    """
    rows = db.execute(text(sql), params).fetchall()
    total = None
    if count:
        total = db.execute(text(f"SELECT COUNT(*) {sql_base}")).scalar()

    response = {
        "@odata.context": f"https://mailguard.cargotrack.ro/v1.0/$metadata#users('{user_id}')/messages",
        "value": [_to_graph_message(r) for r in rows],
    }
    if total is not None:
        response["@odata.count"] = total
    # nextLink if more available
    if len(rows) == top:
        response["@odata.nextLink"] = f"https://mailguard.cargotrack.ro/v1.0/users/{user_id}/mailFolders/Inbox/messages?$top={top}&$skip={skip+top}"
    return response


@router.get("/v1.0/users/{user_id}/messages/{message_id}")
def get_message(
    user_id: str, message_id: str,
    db: Session = Depends(get_db),
    _key: str = Depends(require_cts_key)
):
    """Get single message by graph_message_id."""
    row = db.execute(text("""
        SELECT id, graph_message_id, internet_message_id, conversation_id,
               subject, from_address, from_name, to_addresses,
               received_at, body_html, body_text, has_attachments, is_read,
               importance, phishing_score, category, status, client_id
        FROM emails
        WHERE graph_message_id = :mid AND status IN ('clean')
    """), {"mid": message_id}).fetchone()
    if not row:
        raise HTTPException(404, "Message not found or not delivered")
    return _to_graph_message(row)


@router.get("/v1.0/users/{user_id}/messages/{message_id}/attachments")
def list_attachments(
    user_id: str, message_id: str,
    db: Session = Depends(get_db),
    _key: str = Depends(require_cts_key)
):
    """List attachments for message."""
    rows = db.execute(text("""
        SELECT a.id, a.graph_attachment_id, a.name, a.content_type, a.size_bytes
        FROM attachments a
        JOIN emails e ON e.id = a.email_id
        WHERE e.graph_message_id = :mid AND e.status = 'clean'
    """), {"mid": message_id}).fetchall()
    return {
        "@odata.context": f"https://mailguard.cargotrack.ro/v1.0/$metadata#users('{user_id}')/messages('{message_id}')/attachments",
        "value": [{
            "@odata.type": "#microsoft.graph.fileAttachment",
            "id": r._mapping["graph_attachment_id"] or str(r._mapping["id"]),
            "name": r._mapping["name"],
            "contentType": r._mapping["content_type"],
            "size": r._mapping["size_bytes"],
            "isInline": False,
        } for r in rows]
    }


@router.patch("/v1.0/users/{user_id}/messages/{message_id}")
def patch_message(
    user_id: str, message_id: str, payload: dict,
    db: Session = Depends(get_db),
    _key: str = Depends(require_cts_key)
):
    """Update message — primarily for isRead=true after CTS ADMIN consumed.
    NOTE: In Option C parallel mode, we DO NOT mark as read in Office 365.
    parser-email-op continues to do that. Here we only track in our delivery_queue.
    """
    is_read = payload.get("isRead")
    if is_read is True:
        # Mark as delivered in delivery_queue
        db.execute(text("""
            INSERT INTO delivery_queue(email_id, delivered_to_admin, delivered_at)
            SELECT id, TRUE, NOW() FROM emails WHERE graph_message_id=:mid
            ON CONFLICT (email_id) DO UPDATE SET delivered_to_admin=TRUE, delivered_at=NOW()
        """), {"mid": message_id})
        db.execute(text("UPDATE emails SET is_read=TRUE WHERE graph_message_id=:mid"), {"mid": message_id})
        db.commit()
    return {"id": message_id, "isRead": is_read}
