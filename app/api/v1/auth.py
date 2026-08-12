"""v0.10.0 — Auth: admin login + JWT verification."""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from jose import jwt, JWTError
import bcrypt
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app.config import get_settings

router = APIRouter()
settings = get_settings()


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


def create_token(user_id: int, email: str, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expires_minutes),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def get_current_admin(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    """JWT auth dependency for admin endpoints."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer token required")
    token = authorization[7:]
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as e:
        raise HTTPException(401, f"Invalid token: {str(e)[:80]}")
    user_id = payload.get("sub")
    row = db.execute(text("SELECT id, username, email, role, access_role, is_active FROM admin_users WHERE id=:id"),
                     {"id": int(user_id)}).fetchone()
    if not row or not row._mapping["is_active"]:
        raise HTTPException(401, "User inactive or not found")
    return dict(row._mapping)


@router.post("/auth/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    # IRIS_SSO_DISABLED_LOGIN — v10.18.39 password login disabled, use IRIS SSO
    raise HTTPException(410, "Password login disabled — use IRIS SSO only")
    # (legacy code below preserved but never reached)
    row = db.execute(text("""
        SELECT id, username, email, password_hash, role, is_active
        FROM admin_users WHERE email=:em OR username=:em
    """), {"em": req.email.lower()}).fetchone()
    if not row:
        raise HTTPException(401, "Invalid credentials")
    user = dict(row._mapping)
    if not user["is_active"]:
        raise HTTPException(401, "User inactive")
    if not bcrypt.checkpw(req.password.encode(), user["password_hash"].encode()):
        raise HTTPException(401, "Invalid credentials")
    # Update last login
    db.execute(text("UPDATE admin_users SET last_login_at=NOW() WHERE id=:id"), {"id": user["id"]})
    db.commit()
    # Audit log
    db.execute(text("""
        INSERT INTO audit_log(actor, action, entity_type, entity_id, details)
        VALUES(:a, 'login', 'admin_user', :id, '{"ip":"unknown"}'::jsonb)
    """), {"a": user["username"], "id": user["id"]})
    db.commit()
    token = create_token(user["id"], user["email"], user["role"])
    return LoginResponse(
        access_token=token,
        user={"id": user["id"], "username": user["username"], "email": user["email"], "role": user["role"]}
    )


@router.get("/auth/me")
def me(user=Depends(get_current_admin)):
    # v10.19.0 — expune rolul intern + modulele permise, ca UI-ul sa filtreze
    # tab-urile. Gate-ul REAL ramine require_module() pe endpoint-uri.
    from app.services import access_control as ac
    role = ac.normalize_role(user.get("access_role"))
    out = dict(user)
    out["access_role"] = role
    out["allowed_modules"] = ac.allowed_modules(role)
    out["allowed_subtabs"] = ac.allowed_subtabs(role)
    out["landing_module"] = ac.landing_module(role)
    out["can_manage_roles"] = role in (ac.ROLE_ADMIN, ac.ROLE_DEVELOPER)
    return out


# =====================================================
# v10.18.39 — IRIS SSO endpoint (Razvan 2026-05-20)
# Login only via signed token from IRIS Gateway. No password.
# =====================================================
import os, hmac, hashlib, base64, json, time
from sqlalchemy.exc import IntegrityError

IRIS_SSO_SECRET_RAW = os.getenv("IRIS_SSO_SECRET", "").strip()


class IrisSsoRequest(BaseModel):
    token: str


def _verify_iris_token(token: str) -> dict:
    """Verify signed IRIS token. Format: base64url(payload).hex(hmac_sha256)."""
    if not IRIS_SSO_SECRET_RAW:
        raise HTTPException(500, "IRIS_SSO_SECRET not configured")
    try:
        b64_payload, signature = token.split(".", 1)
    except ValueError:
        raise HTTPException(400, "Invalid token format")
    expected = hmac.new(
        IRIS_SSO_SECRET_RAW.encode(),
        b64_payload.encode(),
        hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "Invalid signature")
    try:
        payload = json.loads(base64.urlsafe_b64decode(b64_payload + "=" * (-len(b64_payload) % 4)).decode())
    except Exception:
        raise HTTPException(400, "Invalid payload")
    exp = payload.get("exp", 0)
    if time.time() > exp:
        raise HTTPException(401, f"Token expired (exp={exp})")
    if time.time() < payload.get("iat", 0) - 60:
        raise HTTPException(401, "Token from future (clock skew)")
    if not payload.get("nonce") or not payload.get("email"):
        raise HTTPException(400, "Missing nonce/email in token")
    return payload


@router.post("/auth/iris-sso", response_model=LoginResponse)
def iris_sso_login(req: IrisSsoRequest, db: Session = Depends(get_db)):
    """Login via IRIS SSO token. No password — verified HMAC + single-use nonce."""
    payload = _verify_iris_token(req.token)
    nonce = payload["nonce"]
    email = payload["email"].lower().strip()

    # Single-use nonce check
    try:
        db.execute(text("INSERT INTO sso_nonces(nonce) VALUES(:n)"), {"n": nonce})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(401, "Nonce already used (replay attack blocked)")

    # Cleanup old nonces (>5min)
    try:
        db.execute(text("DELETE FROM sso_nonces WHERE used_at < NOW() - INTERVAL '5 minutes'"))
        db.commit()
    except Exception:
        db.rollback()

    # Find or create user
    row = db.execute(
        text("SELECT id, username, email, role, access_role, is_active FROM admin_users WHERE email=:em"),
        {"em": email}
    ).fetchone()
    if not row:
        uname = email.split("@")[0]
        base_uname = uname
        suffix = 0
        while db.execute(text("SELECT 1 FROM admin_users WHERE username=:u"), {"u": uname}).fetchone():
            suffix += 1
            uname = f"{base_uname}{suffix}"
        sso_hash_marker = "!IRIS_SSO_ONLY_NO_PASSWORD!"
        role = payload.get("role", "admin")
        # v10.19.0 — deny-by-default: userii noi intra ca 'operator', indiferent
        # ce spune tokenul IRIS.
        # v2.6.0 — daca exista o pre-atribuire in access_role_assignments (setata
        # din Utilizatori inainte ca omul sa se logheze vreodata), o folosim.
        access_role = "operator"
        try:
            _pre = db.execute(
                text("SELECT access_role FROM access_role_assignments WHERE lower(email)=:em"),
                {"em": email}
            ).fetchone()
            if _pre:
                access_role = _pre._mapping["access_role"]
        except Exception:
            db.rollback()  # tabel inexistent (migratie neaplicata) -> operator
        try:
            res = db.execute(text("""
                INSERT INTO admin_users(username, email, password_hash, role, access_role, is_active, created_at)
                VALUES(:u, :em, :ph, :r, :ar, true, NOW())
                RETURNING id, username, email, role, access_role, is_active
            """), {"u": uname, "em": email, "ph": sso_hash_marker, "r": role, "ar": access_role})
            db.commit()
            row = res.fetchone()
        except Exception as e:
            db.rollback()
            raise HTTPException(500, f"User provisioning failed: {e}")

    user = dict(row._mapping)
    if not user["is_active"]:
        raise HTTPException(403, "User inactive")

    db.execute(text("UPDATE admin_users SET last_login_at=NOW() WHERE id=:id"), {"id": user["id"]})
    db.execute(text("""
        INSERT INTO audit_log(actor, action, entity_type, entity_id, details)
        VALUES(:a, :act, 'admin_user', :id, CAST(:det AS jsonb))
    """), {
        "a": user["username"],
        "act": "sso_login",
        "id": user["id"],
        "det": json.dumps({"via": "iris", "email": email, "name": payload.get("name")})
    })
    db.commit()

    jwt_token = create_token(user["id"], user["email"], user["role"])
    from app.services import access_control as ac
    _ar = ac.normalize_role(user.get("access_role"))
    return LoginResponse(
        access_token=jwt_token,
        user={
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "role": user["role"],
            "access_role": _ar,
            "allowed_modules": ac.allowed_modules(_ar),
            "allowed_subtabs": ac.allowed_subtabs(_ar),
            "landing_module": ac.landing_module(_ar),
            "can_manage_roles": _ar in (ac.ROLE_ADMIN, ac.ROLE_DEVELOPER),
        }
    )


# =====================================================
# v10.19.0 — Management roluri interne (Utilizatori -> Roluri acces)
# =====================================================
class SetAccessRoleRequest(BaseModel):
    access_role: str


def _require_role_manager(user):
    """Doar admin/developer pot vedea sau schimba roluri."""
    from app.services import access_control as ac
    actor_role = ac.normalize_role(user.get("access_role"))
    if actor_role not in (ac.ROLE_ADMIN, ac.ROLE_DEVELOPER):
        raise HTTPException(403, "Doar admin sau developer pot gestiona rolurile")
    return actor_role


@router.get("/access/users")
def list_access_users(user=Depends(get_current_admin), db: Session = Depends(get_db)):
    """Toti angajatii (din employee_department_mapping) + rolul lor efectiv.

    Rolul efectiv vine din admin_users daca omul s-a logat deja, altfel din
    pre-atribuirea din access_role_assignments. Oamenii fara cont apar si ei,
    ca sa li se poata seta rolul INAINTE de prima logare.
    """
    from app.services import access_control as ac
    actor_role = _require_role_manager(user)

    rows = db.execute(text("""
        SELECT
            COALESCE(lower(a.email), lower(r.email), lower(e.email))   AS email,
            COALESCE(e.name, a.username)                               AS name,
            e.department                                               AS department,
            a.id                                                       AS user_id,
            a.access_role                                              AS account_role,
            r.access_role                                              AS assigned_role,
            a.is_active                                                AS is_active,
            a.last_login_at                                            AS last_login_at
        FROM employee_department_mapping e
        FULL OUTER JOIN admin_users a               ON lower(a.email) = lower(e.email)
        FULL OUTER JOIN access_role_assignments r   ON lower(r.email) = COALESCE(lower(a.email), lower(e.email))
        WHERE COALESCE(e.enabled, true) = true
          AND COALESCE(a.email, r.email, e.email) IS NOT NULL
        ORDER BY e.department NULLS LAST, COALESCE(e.name, a.username)
    """)).fetchall()

    users = []
    for r in rows:
        m = r._mapping
        effective = m["account_role"] or m["assigned_role"] or ac.DEFAULT_ROLE
        users.append({
            "email": m["email"],
            "name": m["name"],
            "department": m["department"],
            "user_id": m["user_id"],
            "access_role": ac.normalize_role(effective),
            "has_account": m["user_id"] is not None,
            "is_active": m["is_active"],
            "last_login_at": m["last_login_at"],
        })

    depts = sorted({u["department"] for u in users if u["department"]})
    return {
        "actor_role": actor_role,
        "assignable_roles": [r for r in ac.ALL_ROLES if ac.can_assign_role(actor_role, r)],
        "departments": depts,
        "users": users,
    }


class SetRoleByEmailRequest(BaseModel):
    email: str
    access_role: str


class BulkRoleRequest(BaseModel):
    department: str
    access_role: str
    except_emails: list = []


def _apply_role_by_email(db, actor, actor_role, email: str, target_role: str) -> dict:
    """Scrie rolul si in pre-atribuire, si pe cont (daca exista). O singura
    tranzactie per email; apelantul face commit."""
    from app.services import access_control as ac
    email = (email or "").strip().lower()
    if not email:
        raise HTTPException(400, "Email lipsa")
    if not ac.can_assign_role(actor_role, target_role):
        raise HTTPException(403, f"Rolul '{actor_role}' nu poate atribui rolul '{target_role}'")

    acc = db.execute(text("SELECT id, access_role FROM admin_users WHERE lower(email)=:em"),
                     {"em": email}).fetchone()
    old_role = None
    if acc:
        old_role = ac.normalize_role(acc._mapping["access_role"])
        # Un admin nu poate atinge un developer existent.
        if actor_role == ac.ROLE_ADMIN and old_role == ac.ROLE_DEVELOPER:
            raise HTTPException(403, f"Doar un developer poate modifica contul {email}")
        if acc._mapping["id"] == actor["id"]:
            raise HTTPException(403, "Nu iti poti schimba propriul rol")

    db.execute(text("""
        INSERT INTO access_role_assignments(email, access_role, assigned_by, updated_at)
        VALUES(:em, :r, :by, now())
        ON CONFLICT (email) DO UPDATE
           SET access_role = EXCLUDED.access_role,
               assigned_by = EXCLUDED.assigned_by,
               updated_at  = now()
    """), {"em": email, "r": target_role, "by": actor["username"]})

    if acc:
        db.execute(text("UPDATE admin_users SET access_role=:r WHERE id=:id"),
                   {"r": target_role, "id": acc._mapping["id"]})

    db.execute(text("""
        INSERT INTO audit_log(actor, action, entity_type, entity_id, details)
        VALUES(:a, 'access_role_change', 'admin_user', :id, CAST(:det AS jsonb))
    """), {
        "a": actor["username"],
        "id": acc._mapping["id"] if acc else 0,
        "det": json.dumps({"from": old_role, "to": target_role, "target_email": email,
                           "had_account": bool(acc)}),
    })
    return {"email": email, "access_role": target_role, "previous": old_role,
            "had_account": bool(acc)}


@router.put("/access/by-email")
def set_role_by_email(req: SetRoleByEmailRequest,
                      user=Depends(get_current_admin), db: Session = Depends(get_db)):
    """Seteaza rolul pe email — merge si pentru oameni care nu au cont inca."""
    from app.services import access_control as ac
    actor_role = _require_role_manager(user)
    target_role = (req.access_role or "").strip().lower()
    if target_role not in ac.ALL_ROLES:
        raise HTTPException(400, f"Rol invalid: {target_role}")
    if not ac.can_assign_role(actor_role, target_role):
        raise HTTPException(403, f"Rolul '{actor_role}' nu poate atribui rolul '{target_role}'")
    out = _apply_role_by_email(db, user, actor_role, req.email, target_role)
    db.commit()
    return {"ok": True, **out}


@router.post("/access/bulk")
def bulk_set_roles(req: BulkRoleRequest,
                   user=Depends(get_current_admin), db: Session = Depends(get_db)):
    """Atribuie un rol intregului departament, cu exceptii.

    Ex: tot suport_1 -> operator, mai putin bianca.judea (ramine admin).
    """
    from app.services import access_control as ac
    actor_role = _require_role_manager(user)
    target_role = (req.access_role or "").strip().lower()
    if target_role not in ac.ALL_ROLES:
        raise HTTPException(400, f"Rol invalid: {target_role}")
    # Verificarea de escaladare se face O DATA, inainte de lot: altfel un admin
    # care cere 'developer' pe tot departamentul primea 200 cu applied=[] —
    # respins in fapt, dar cu raspuns inselator.
    if not ac.can_assign_role(actor_role, target_role):
        raise HTTPException(403, f"Rolul '{actor_role}' nu poate atribui rolul '{target_role}'")

    skip = {e.strip().lower() for e in (req.except_emails or []) if e and e.strip()}
    rows = db.execute(text("""
        SELECT lower(email) AS email FROM employee_department_mapping
         WHERE department = :d AND enabled = true AND email IS NOT NULL AND email <> ''
    """), {"d": req.department}).fetchall()

    applied, skipped, failed = [], [], []
    for r in rows:
        em = r._mapping["email"]
        if em in skip:
            skipped.append(em)
            continue
        try:
            _apply_role_by_email(db, user, actor_role, em, target_role)
            applied.append(em)
        except HTTPException as e:
            # Un conflict pe un singur om (ex. developer protejat) nu trebuie sa
            # anuleze tot lotul.
            failed.append({"email": em, "reason": e.detail if isinstance(e.detail, str) else str(e.detail)})
    db.commit()
    return {"ok": True, "department": req.department, "access_role": target_role,
            "applied": applied, "skipped": skipped, "failed": failed,
            "count": len(applied)}


@router.put("/access/users/{user_id}/role")
def set_access_role(user_id: int, req: SetAccessRoleRequest,
                    user=Depends(get_current_admin), db: Session = Depends(get_db)):
    """Seteaza rolul intern al unui cont. Admin nu poate crea developeri."""
    from app.services import access_control as ac
    actor_role = ac.normalize_role(user.get("access_role"))
    target_role = (req.access_role or "").strip().lower()

    if target_role not in ac.ALL_ROLES:
        raise HTTPException(400, f"Rol invalid: {target_role}")
    if not ac.can_assign_role(actor_role, target_role):
        raise HTTPException(403, f"Rolul '{actor_role}' nu poate atribui rolul '{target_role}'")

    row = db.execute(text("SELECT id, username, email, access_role FROM admin_users WHERE id=:id"),
                     {"id": user_id}).fetchone()
    if not row:
        raise HTTPException(404, "Utilizator inexistent")
    target = dict(row._mapping)
    old_role = ac.normalize_role(target["access_role"])

    # Un admin nu poate modifica un developer (altfel l-ar putea retrograda si
    # apoi promova pe sine — ocolind can_assign_role).
    if actor_role == ac.ROLE_ADMIN and old_role == ac.ROLE_DEVELOPER:
        raise HTTPException(403, "Doar un developer poate modifica un cont de developer")

    # Nu te poti auto-retrograda: ar lasa sistemul fara ultimul developer.
    if target["id"] == user["id"] and target_role != old_role:
        raise HTTPException(403, "Nu iti poti schimba propriul rol")

    db.execute(text("UPDATE admin_users SET access_role=:r WHERE id=:id"),
               {"r": target_role, "id": user_id})
    db.execute(text("""
        INSERT INTO audit_log(actor, action, entity_type, entity_id, details)
        VALUES(:a, 'access_role_change', 'admin_user', :id, CAST(:det AS jsonb))
    """), {
        "a": user["username"],
        "id": user_id,
        "det": json.dumps({"from": old_role, "to": target_role, "target_email": target["email"]}),
    })
    db.commit()
    return {"ok": True, "id": user_id, "email": target["email"],
            "access_role": target_role, "previous": old_role}
