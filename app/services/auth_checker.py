"""SPF / DKIM / DMARC + alignment checker — anti-spoofing for Cargo360.

Parses the authentication results that the receiving MTA (Office 365 / Google)
already stamped on each message and that ingestion already captured into
`emails.email_headers.authentication_flags` (Authentication-Results,
Received-SPF, DKIM-Signature, ARC-Authentication-Results). It turns them into an
*enforceable* verdict — the gap today is that these are stored but never applied.

No DNS lookups are performed: we trust the receiving MTA's stamped results, the
same trust model every mail client uses. This is correct because ingestion pulls
from an authenticated O365/Graph mailbox — the headers were written by our own
mail provider, not the sender.

DMARC-FIRST policy (industry standard, avoids false positives):
  - dmarc=pass            -> legitimate, even if SPF softfails (forwarders/relays).
  - dmarc=fail            -> spoofing-grade. Strongest signal.
  - dmarc none/unknown    -> fall back to SPF/DKIM + From-alignment.

Returns a dict (see `evaluate`). Pure, side-effect free, no network.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List, Optional

# Default policy — overridable via settings key 'auth_policy' (jsonb).
DEFAULT_POLICY = {
    "enabled": True,
    # action for a spoofing-grade verdict: 'quarantine_strict' | 'quarantine' | 'score'
    "fail_action": "quarantine_strict",
    "weights": {
        "dmarc_fail": 45,        # explicit DMARC fail = spoofing
        "spf_hardfail": 25,      # SPF fail (not softfail) with no DMARC pass
        "spf_softfail": 8,       # weak signal
        "dkim_fail": 15,
        "no_auth_results": 6,    # cannot verify at all (kept low: internal relays)
        "from_unaligned": 20,    # From domain matches neither SPF nor DKIM domain
        "returnpath_mismatch": 12,  # envelope mailfrom domain != From domain (no DMARC pass)
    },
    # verdict thresholds on the accumulated auth-score
    "suspicious_at": 12,
    "fail_at": 30,
}

_RESULT_TOKENS = ("pass", "fail", "softfail", "neutral", "none",
                  "temperror", "permerror", "bestguesspass", "policy")


def _norm_domain(d: Optional[str]) -> Optional[str]:
    if not d:
        return None
    d = d.strip().strip(">").strip("<").strip().lower()
    # strip a trailing dot, any surrounding quotes/semicolons
    d = d.rstrip(".;,'\" ")
    if "@" in d:                       # in case a full address slipped in
        d = d.split("@", 1)[-1]
    return d or None


def _org_domain(d: Optional[str]) -> Optional[str]:
    """Best-effort organizational domain (last two labels). Not a PSL, but good
    enough for relaxed-alignment comparison (sub.example.com ~ example.com)."""
    d = _norm_domain(d)
    if not d:
        return None
    parts = d.split(".")
    if len(parts) <= 2:
        return d
    # handle common two-level TLDs (co.uk, com.ro etc.) lightly
    two_level = {"co.uk", "org.uk", "gov.uk", "com.ro", "co.jp", "com.au", "co.za"}
    last2 = ".".join(parts[-2:])
    if last2 in two_level and len(parts) >= 3:
        return ".".join(parts[-3:])
    return last2


def _aligned(a: Optional[str], b: Optional[str]) -> Optional[bool]:
    oa, ob = _org_domain(a), _org_domain(b)
    if not oa or not ob:
        return None
    return oa == ob


def _flags_text(em: Dict[str, Any]) -> List[str]:
    hdrs = em.get("email_headers") or {}
    if isinstance(hdrs, str):
        return []
    flags = hdrs.get("authentication_flags") or []
    return [f for f in flags if isinstance(f, str)]


def _grab(rx: str, text: str) -> Optional[str]:
    m = re.search(rx, text, re.IGNORECASE)
    return m.group(1) if m else None


def _result_after(key: str, text: str) -> Optional[str]:
    """Find e.g. 'spf=pass' / 'dkim = fail' and return the token."""
    m = re.search(rf"\b{key}\s*=\s*([a-zA-Z]+)", text, re.IGNORECASE)
    if not m:
        return None
    tok = m.group(1).lower()
    return tok if tok in _RESULT_TOKENS else tok


def evaluate(em: Dict[str, Any], policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Evaluate authentication for one email row (must contain email_headers +
    from_address). Returns the verdict dict; never raises."""
    pol = dict(DEFAULT_POLICY)
    if policy:
        pol.update({k: v for k, v in policy.items() if k != "weights"})
        if isinstance(policy.get("weights"), dict):
            w = dict(DEFAULT_POLICY["weights"]); w.update(policy["weights"]); pol["weights"] = w
    W = pol["weights"]

    out: Dict[str, Any] = {
        "spf": "unknown", "dkim": "unknown", "dmarc": "unknown",
        "mailfrom_domain": None, "header_from_domain": None, "dkim_domain": None,
        "spf_aligned": None, "dkim_aligned": None,
        "score": 0, "reasons": [], "verdict": "pass", "checked": False,
    }
    try:
        from_addr = (em.get("from_address") or "").strip().lower()
        out["header_from_domain"] = _norm_domain(from_addr.split("@", 1)[-1] if "@" in from_addr else None)

        flags = _flags_text(em)
        if not flags:
            # Cannot verify — light signal only (lots of internal/relayed mail).
            out["score"] = W["no_auth_results"]
            out["reasons"].append({"code": "auth_no_results",
                                   "detail": "fără Authentication-Results (nu se poate verifica SPF/DKIM/DMARC)",
                                   "weight": W["no_auth_results"]})
            out["verdict"] = "suspicious" if out["score"] >= pol["suspicious_at"] else "pass"
            return out

        ar = " \n ".join(f for f in flags
                         if f.lower().startswith(("authentication-results", "arc-authentication-results")))
        rspf = " \n ".join(f for f in flags if f.lower().startswith("received-spf"))
        dkim_sig = " \n ".join(f for f in flags if f.lower().startswith("dkim-signature"))
        out["checked"] = True

        # ---- SPF ----
        spf = _result_after("spf", ar) or None
        if not spf and rspf:
            # Received-SPF: <Result> (...)
            m = re.match(r"received-spf:\s*([a-zA-Z]+)", rspf.strip(), re.IGNORECASE)
            spf = m.group(1).lower() if m else None
        out["spf"] = spf or "unknown"
        out["mailfrom_domain"] = _norm_domain(_grab(r"smtp\.mailfrom=([^;\s]+)", ar)
                                              or _grab(r"envelope-from=<?([^;>\s]+)", rspf))

        # ---- DKIM ----
        out["dkim"] = _result_after("dkim", ar) or "unknown"
        out["dkim_domain"] = _norm_domain(_grab(r"header\.d=([^;\s]+)", ar)
                                          or _grab(r"\bd=([^;\s]+)", dkim_sig))

        # ---- DMARC ----
        out["dmarc"] = _result_after("dmarc", ar) or "unknown"
        hf = _norm_domain(_grab(r"header\.from=([^;\s]+)", ar))
        if hf:
            out["header_from_domain"] = hf

        # ---- alignment ----
        out["spf_aligned"] = _aligned(out["mailfrom_domain"], out["header_from_domain"])
        out["dkim_aligned"] = _aligned(out["dkim_domain"], out["header_from_domain"])

        # ---- scoring (DMARC-first) ----
        score = 0
        reasons: List[Dict[str, Any]] = []

        def add(code, detail, w):
            nonlocal score
            score += w
            reasons.append({"code": code, "detail": detail, "weight": w})

        dmarc = out["dmarc"]
        if dmarc in ("pass", "bestguesspass"):
            # Authenticated by DMARC — legitimate even if SPF softfails (forwarders).
            pass
        elif dmarc == "fail":
            add("dmarc_fail",
                f"DMARC=fail (From: {out['header_from_domain'] or '?'}) — spoofing",
                W["dmarc_fail"])
        else:
            # No DMARC verdict — fall back to SPF/DKIM + alignment.
            spf_ok = (out["spf"] == "pass" and out["spf_aligned"] is True)
            dkim_valid = (out["dkim"] == "pass")          # signature verified (any domain)
            dkim_ok = (dkim_valid and out["dkim_aligned"] is True)

            if spf_ok or dkim_ok:
                # Authenticated + aligned by SPF or DKIM → legitimate.
                pass
            elif dkim_valid:
                # Valid DKIM signature but unaligned domain — typical of legit ESPs
                # (Mailchimp/Mandrill/SendGrid sending on behalf of a brand). Flag,
                # don't quarantine: a forged sender can't produce a valid signature.
                add("dkim_unaligned",
                    f"DKIM valid dar nealiniat (d={out['dkim_domain'] or '?'} ≠ From {out['header_from_domain'] or '?'}) — probabil ESP",
                    W["spf_softfail"] + 4)
            else:
                # No valid authentication at all — strongest non-DMARC spoof case.
                if out["spf"] == "fail":
                    add("spf_fail", "SPF=fail (expeditor neautorizat)", W["spf_hardfail"])
                elif out["spf"] == "softfail":
                    add("spf_softfail", "SPF=softfail", W["spf_softfail"])
                if out["dkim"] == "fail":
                    add("dkim_fail", "DKIM=fail (semnătură invalidă)", W["dkim_fail"])
                if out["spf_aligned"] is False or out["dkim_aligned"] is False:
                    add("from_unaligned",
                        f"From ({out['header_from_domain'] or '?'}) nealiniat cu SPF/DKIM",
                        W["from_unaligned"])
                if (out["mailfrom_domain"] and out["header_from_domain"]
                        and _org_domain(out["mailfrom_domain"]) != _org_domain(out["header_from_domain"])):
                    add("returnpath_mismatch",
                        f"Return-Path ({out['mailfrom_domain']}) ≠ From ({out['header_from_domain']})",
                        W["returnpath_mismatch"])

        out["score"] = score
        out["reasons"] = reasons
        if score >= pol["fail_at"] or dmarc == "fail":
            out["verdict"] = "fail"
        elif score >= pol["suspicious_at"]:
            out["verdict"] = "suspicious"
        else:
            out["verdict"] = "pass"
        return out
    except Exception as e:  # never break the pipeline
        out["reasons"].append({"code": "auth_error", "detail": f"{type(e).__name__}: {e}", "weight": 0})
        out["verdict"] = "pass"
        return out
