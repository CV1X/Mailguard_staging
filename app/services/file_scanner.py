"""Attachment malware / threat scanner — antivirus layer for Cargo360.

Scans EVERY attachment for:
  - Known malware via ClamAV (INSTREAM over the local socket — sends bytes, so it
    works regardless of which user owns the file on disk; falls back to clamdscan CLI).
  - VBA macros in Office docs (oletools/olevba) — flags auto-exec + suspicious macros.
  - Dangerous archives: unpacks .zip and scans each member; flags encrypted archives
    (can't be inspected) and executable / double-extension members.
  - Executables / scripts by content.

Returns a per-attachment verdict dict. Defensive: never raises (a scanner failure
must not drop a real email). Side-effect free apart from reading the file.
"""
from __future__ import annotations
import io
import os
import re
import socket
import struct
import subprocess
import zipfile
from typing import Any, Dict, List, Optional

CLAMD_SOCKET = os.getenv("CLAMD_SOCKET", "/var/run/clamav/clamd.ctl")
MAX_BYTES = int(os.getenv("MG_SCAN_MAX_BYTES", str(25 * 1024 * 1024)))   # clamd StreamMaxLength
ARCHIVE_MAX_MEMBERS = 2000
ARCHIVE_MAX_DEPTH = 2

_EXE_EXT = {".exe", ".scr", ".bat", ".cmd", ".com", ".pif", ".vbs", ".js", ".jse",
            ".jar", ".iso", ".lnk", ".ps1", ".msi", ".hta", ".wsf", ".cpl", ".dll", ".sh"}
_MACRO_EXT = {".docm", ".xlsm", ".xltm", ".dotm", ".pptm", ".potm", ".xlsb"}
_OFFICE_EXT = {".doc", ".xls", ".ppt", ".docx", ".xlsx", ".pptx"} | _MACRO_EXT
_DOUBLE_EXT = re.compile(r"\.(pdf|doc|docx|xls|xlsx|jpg|jpeg|png|txt|csv)\.(exe|scr|bat|cmd|com|pif|vbs|js|jar|lnk|hta|ps1)$", re.I)


def _ext(name: str) -> str:
    name = (name or "").strip().lower()
    return os.path.splitext(name)[1]


# ───────────────────────── ClamAV ─────────────────────────
def _clamd_instream(data: bytes) -> Optional[str]:
    """Scan bytes via clamd INSTREAM. Returns signature name if infected, '' if clean,
    None if clamd unavailable."""
    if len(data) > MAX_BYTES:
        return None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(30)
        s.connect(CLAMD_SOCKET)
        s.sendall(b"zINSTREAM\x00")
        chunk = 8192
        for i in range(0, len(data), chunk):
            part = data[i:i + chunk]
            s.sendall(struct.pack("!L", len(part)) + part)
        s.sendall(struct.pack("!L", 0))  # end of stream
        resp = b""
        while True:
            b = s.recv(4096)
            if not b:
                break
            resp += b
            if b.endswith(b"\x00"):
                break
        s.close()
        text = resp.decode("utf-8", "replace").strip("\x00").strip()
        if text.endswith("OK"):
            return ""
        m = re.search(r":\s*(.+)\s+FOUND", text)
        if m:
            return m.group(1).strip()
        if "FOUND" in text:
            return text
        return ""  # ERROR/empty -> treat as clean-but-unknown (None handled by caller)
    except Exception:
        return None


def _clamdscan_cli(path: str) -> Optional[str]:
    try:
        r = subprocess.run(["clamdscan", "--no-summary", "--fdpass", path],
                           capture_output=True, text=True, timeout=60)
        out = (r.stdout or "") + (r.stderr or "")
        if "FOUND" in out:
            m = re.search(r":\s*(.+)\s+FOUND", out)
            return m.group(1).strip() if m else "malware"
        if r.returncode == 0:
            return ""
        return None
    except Exception:
        return None


def clam_scan_bytes(data: bytes, path: Optional[str] = None) -> Optional[str]:
    sig = _clamd_instream(data)
    if sig is not None:
        return sig
    if path:
        return _clamdscan_cli(path)
    return None


# ───────────────────────── Macros ─────────────────────────
def _macro_scan(path: str) -> Dict[str, Any]:
    out = {"has_macros": False, "autoexec": False, "suspicious": [], "error": None}
    try:
        from oletools.olevba import VBA_Parser
        vp = VBA_Parser(path)
        if vp.detect_vba_macros():
            out["has_macros"] = True
            for (_f, _s, _name, _code) in vp.extract_macros():
                pass
            results = vp.analyze_macros() or []
            for kind, keyword, desc in results:
                k = (kind or "").lower()
                if k == "autoexec":
                    out["autoexec"] = True
                if k in ("suspicious", "ioc"):
                    out["suspicious"].append(f"{keyword}")
        vp.close()
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


# ───────────────────────── Archives ─────────────────────────
def _archive_scan(path: str, depth: int = 0) -> Dict[str, Any]:
    out = {"is_archive": False, "encrypted": False, "members": 0, "threats": [], "error": None}
    if not zipfile.is_zipfile(path):
        return out
    out["is_archive"] = True
    try:
        zf = zipfile.ZipFile(path)
        infos = zf.infolist()[:ARCHIVE_MAX_MEMBERS]
        out["members"] = len(infos)
        for zi in infos:
            if zi.is_dir():
                continue
            if zi.flag_bits & 0x1:               # encrypted entry
                out["encrypted"] = True
                continue
            name = zi.filename
            ext = _ext(name)
            if _DOUBLE_EXT.search(name):
                out["threats"].append({"member": name, "code": "double_extension"})
            if ext in _EXE_EXT:
                out["threats"].append({"member": name, "code": "executable_in_archive", "ext": ext})
            try:
                if zi.file_size <= MAX_BYTES:
                    data = zf.read(zi)
                    sig = clam_scan_bytes(data)
                    if sig:
                        out["threats"].append({"member": name, "code": "malware", "signature": sig})
                    elif depth < ARCHIVE_MAX_DEPTH and zipfile.is_zipfile(io.BytesIO(data)):
                        # nested archive — flag, shallow (avoid zip bombs)
                        out["threats"].append({"member": name, "code": "nested_archive"})
            except RuntimeError:
                out["encrypted"] = True             # password required
            except Exception:
                pass
        zf.close()
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


# ───────────────────────── Orchestrator ─────────────────────────
def scan_file(path: str, filename: str = "", content_type: str = "") -> Dict[str, Any]:
    """Scan one file. verdict ∈ {clean, suspicious, malware, unscannable}."""
    res: Dict[str, Any] = {"verdict": "clean", "threats": [], "clam": None,
                           "macros": None, "archive": None, "size": None}
    try:
        if not path or not os.path.exists(path):
            res["verdict"] = "unscannable"
            res["threats"].append({"code": "file_missing"})
            return res
        size = os.path.getsize(path)
        res["size"] = size
        ext = _ext(filename or path)

        # double extension on the attachment itself
        if _DOUBLE_EXT.search(filename or ""):
            res["threats"].append({"code": "double_extension", "detail": filename})
        if ext in _EXE_EXT:
            res["threats"].append({"code": "executable_attachment", "ext": ext})

        # ClamAV on the whole file
        data = None
        if size <= MAX_BYTES:
            with open(path, "rb") as fh:
                data = fh.read()
            sig = clam_scan_bytes(data, path)
            res["clam"] = "unavailable" if sig is None else (sig or "clean")
            if sig:
                res["threats"].append({"code": "malware", "signature": sig})
        else:
            res["clam"] = "skipped_too_large"
            res["threats"].append({"code": "too_large_to_scan", "size": size})

        # Macros for Office files
        if ext in _OFFICE_EXT:
            m = _macro_scan(path)
            res["macros"] = m
            if m.get("has_macros"):
                if m.get("autoexec") and m.get("suspicious"):
                    res["threats"].append({"code": "malicious_macro", "detail": m["suspicious"][:5]})
                elif m.get("autoexec") or m.get("suspicious"):
                    res["threats"].append({"code": "suspicious_macro",
                                           "detail": (m.get("suspicious") or ["autoexec"])[:5]})
                else:
                    res["threats"].append({"code": "macro_present"})

        # Archives
        arch = _archive_scan(path)
        if arch.get("is_archive"):
            res["archive"] = arch
            if arch.get("encrypted"):
                res["threats"].append({"code": "encrypted_archive"})
            for t in arch.get("threats", []):
                res["threats"].append({"code": "archive_" + t.get("code", "x"),
                                       "member": t.get("member"), "signature": t.get("signature")})

        # ---- verdict ----
        codes = {t.get("code") for t in res["threats"]}
        malware_codes = {"malware", "archive_malware", "malicious_macro", "double_extension",
                         "archive_double_extension", "archive_executable_in_archive"}
        suspicious_codes = {"executable_attachment", "suspicious_macro", "macro_present",
                            "encrypted_archive", "archive_nested_archive", "too_large_to_scan"}
        if codes & malware_codes:
            res["verdict"] = "malware"
        elif codes & suspicious_codes:
            res["verdict"] = "suspicious"
        else:
            res["verdict"] = "clean"
        return res
    except Exception as e:
        res["verdict"] = "clean"   # fail-open on scanner crash (don't drop real mail)
        res["threats"].append({"code": "scan_error", "detail": f"{type(e).__name__}: {e}"})
        return res


def scan_attachment(att: Dict[str, Any]) -> Dict[str, Any]:
    """Scan an attachments-table row (storage_path, name, content_type)."""
    return scan_file(att.get("storage_path") or "", att.get("name") or "",
                     att.get("content_type") or "")
