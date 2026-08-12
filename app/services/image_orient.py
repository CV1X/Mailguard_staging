"""Detectare și corectare orientare imagini via IRIS AI (vision) + Pillow.

Folosit de _build_attachment() din cts.py când flag-ul auto_rotate_images e activ.
Fail-safe: orice eroare → returnează bytes originale, fără excepție.
"""
import base64
import logging
from io import BytesIO

logger = logging.getLogger("mailguard.image_orient")

_SUPPORTED_MIME = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/bmp"}

_SYSTEM_PROMPT = """Ești un sistem de detectare a orientării imaginilor.
Analizează imaginea primită și determină dacă este rotită față de orientarea corectă (cum ar privi un om în mod normal).
Răspunde DOAR cu un număr din: 0, 90, 180, 270
- 0 = orientare corectă (nu trebuie rotită)
- 90 = rotită 90° în sensul acelor de ceasornic față de corect (trebuie rotită 270° pentru a fi dreaptă)
- 180 = întoarsă cu susul în jos (trebuie rotită 180°)
- 270 = rotită 270° în sensul acelor de ceasornic față de corect (trebuie rotită 90° pentru a fi dreaptă)
Răspunde STRICT cu numărul, fără alte cuvinte."""


def maybe_rotate(raw: bytes, mime_type: str) -> bytes:
    """Detectează orientarea imaginii via AI și aplică rotire Pillow dacă e necesar.
    Returnează bytes originale (nemodificate) la orice eroare sau dacă orientarea e 0."""
    if not raw:
        return raw
    mt = (mime_type or "").lower().split(";")[0].strip()
    if mt not in _SUPPORTED_MIME:
        return raw

    degrees = _detect_rotation(raw, mt)
    if degrees == 0:
        return raw

    return _rotate_image(raw, degrees, mt)


def _detect_rotation(raw: bytes, mime_type: str) -> int:
    """Apelează IRIS AI (gemma sau haiku) cu imaginea și returnează gradele de rotire detectate.
    0 la orice eșec."""
    try:
        from app.services import iris_ai
        data_b64 = base64.b64encode(raw).decode("ascii")
        res = iris_ai.run_prompt(
            system=_SYSTEM_PROMPT,
            content="Analizează orientarea acestei imagini și răspunde cu 0, 90, 180 sau 270.",
            attachments=[{"mime_type": mime_type, "data_base64": data_b64}],
            response_format="text",
            model_hint="gemma",
            temperature=0.0,
            max_tokens=10,
            task="image_orient_detect",
            timeout=30.0,
        )
        if not res.get("ok"):
            # fallback la haiku dacă gemma nu suportă vision
            res = iris_ai.run_prompt(
                system=_SYSTEM_PROMPT,
                content="Analizează orientarea acestei imagini și răspunde cu 0, 90, 180 sau 270.",
                attachments=[{"mime_type": mime_type, "data_base64": data_b64}],
                response_format="text",
                model_hint="claude-haiku-4-5-20251001",
                temperature=0.0,
                max_tokens=10,
                task="image_orient_detect",
                timeout=30.0,
            )
        if not res.get("ok"):
            logger.warning("image_orient: AI failed: %s", res.get("error"))
            return 0
        text = (res.get("text") or "").strip()
        # extrage primul număr din răspuns
        import re
        m = re.search(r"\b(0|90|180|270)\b", text)
        if not m:
            logger.debug("image_orient: răspuns neașteptat AI: %r", text[:50])
            return 0
        return int(m.group(1))
    except Exception as e:
        logger.warning("image_orient: excepție la detectare: %s", e)
        return 0


def _rotate_image(raw: bytes, detected_degrees: int, mime_type: str) -> bytes:
    """Rotește imaginea cu unghiul necesar pentru a o readuce la orientare corectă.
    detected_degrees = cât e rotită față de corect → rotim în sens invers.
    Returnează bytes originale la orice eroare Pillow."""
    # Dacă e rotită cu X° față de corect, trebuie rotită cu (360-X)° pentru a fi dreaptă.
    correction = (360 - detected_degrees) % 360
    if correction == 0:
        return raw
    try:
        from PIL import Image
        img = Image.open(BytesIO(raw))
        # expand=True ca să nu taie colțurile la 90/270°
        rotated = img.rotate(correction, expand=True)
        buf = BytesIO()
        fmt = img.format or _mime_to_pillow_format(mime_type)
        save_kwargs = {}
        if fmt == "JPEG":
            save_kwargs["quality"] = 95
        rotated.save(buf, format=fmt, **save_kwargs)
        result = buf.getvalue()
        logger.info("image_orient: rotit %d° (corecție %d°) → %d bytes", detected_degrees, correction, len(result))
        return result
    except Exception as e:
        logger.warning("image_orient: Pillow rotate eșuat (det=%d): %s", detected_degrees, e)
        return raw


def _mime_to_pillow_format(mime_type: str) -> str:
    return {
        "image/jpeg": "JPEG",
        "image/jpg":  "JPEG",
        "image/png":  "PNG",
        "image/webp": "WEBP",
        "image/bmp":  "BMP",
    }.get(mime_type.lower(), "JPEG")
