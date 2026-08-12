#!/usr/bin/env python3
"""Patch mg-app.js: add NoreplyPanel, Settings tab, and noreplyBadge."""

import sys

MGAPP = "/opt/iris-mailguard/app/ui/vendor/mg-app.js"

with open(MGAPP, "r", encoding="utf-8") as f:
    content = f.read()

# ── Guard ─────────────────────────────────────────────────────────────────────
if "NoreplyPanel" in content:
    print("Already patched. Exit.")
    sys.exit(0)

# ── 1. Componenta NoreplyPanel + noreplyBadge ─────────────────────────────────
NOREPLY_CODE = r"""
function noreplyBadge(e) {
  if (!e || !e.autoreply_sent_at) return null;
  return h("span", {
    className: "badge",
    title: "Mesaj automat trimis la " + new Date(e.autoreply_sent_at).toLocaleString("ro-RO"),
    style: { background: "rgba(59,130,246,0.12)", color: "var(--bl)",
             border: "0.5px solid rgba(59,130,246,0.35)", marginLeft: 4, textTransform: "none" }
  }, "✓ auto-reply");
}

function NoreplyPanel() {
  const [enabled, setEnabled] = React.useState(null);
  const [cfg, setCfg] = React.useState({});
  const [cfgBusy, setCfgBusy] = React.useState(false);
  const [tplText, setTplText] = React.useState("");
  const [tplDefault, setTplDefault] = React.useState("");
  const [tplBusy, setTplBusy] = React.useState(false);
  const [bl, setBl] = React.useState([]);
  const [blInput, setBlInput] = React.useState("");
  const [togBusy, setTogBusy] = React.useState(false);

  function loadAll() {
    api("/api/v1/noreply/toggle").then(function(r) { if (r) setEnabled(!!r.enabled); }).catch(function(){});
    api("/api/v1/noreply/config").then(function(r) { if (r) setCfg(r); }).catch(function(){});
    api("/api/v1/noreply/template").then(function(r) { if (r) { setTplText(r.template || ""); setTplDefault(r.default || ""); } }).catch(function(){});
    api("/api/v1/noreply/blacklist").then(function(r) { if (r) setBl(r.items || []); }).catch(function(){});
  }
  React.useEffect(function() { loadAll(); }, []);

  function toggle() {
    setTogBusy(true);
    api("/api/v1/noreply/toggle", { method: "POST", body: JSON.stringify({ enabled: !enabled }) })
      .then(function(r) { if (r) setEnabled(!!r.enabled); mgToast("success", r && r.message || "OK"); })
      .catch(function(e) { Swal.fire({ icon: "error", title: "Eroare", text: String(e && e.message || e), background: "var(--bg2)", color: "var(--tx)" }); })
      .finally(function() { setTogBusy(false); });
  }

  function saveCfg() {
    if (!cfg.smtp_host || !cfg.smtp_port || !cfg.smtp_user || !cfg.from_address) {
      Swal.fire({ icon: "warning", title: "Campuri obligatorii", text: "Host, Port, User si From address sunt necesare.", background: "var(--bg2)", color: "var(--tx)" }); return;
    }
    setCfgBusy(true);
    api("/api/v1/noreply/config", { method: "PUT", body: JSON.stringify(cfg) })
      .then(function() { mgToast("success", "Config SMTP salvat."); loadAll(); })
      .catch(function(e) { Swal.fire({ icon: "error", title: "Eroare", text: String(e && e.message || e), background: "var(--bg2)", color: "var(--tx)" }); })
      .finally(function() { setCfgBusy(false); });
  }

  function testSmtp() {
    Swal.fire({ title: "Email destinatar test", input: "email", inputLabel: "Adresa unde trimitem testul", showCancelButton: true, background: "var(--bg2)", color: "var(--tx)" })
      .then(function(res) {
        if (!res.isConfirmed || !res.value) return;
        api("/api/v1/noreply/config/test", { method: "POST", body: JSON.stringify({ to_address: res.value }) })
          .then(function() { mgToast("success", "Email de test trimis!"); })
          .catch(function(e) { Swal.fire({ icon: "error", title: "Eroare SMTP", text: String(e && e.message || e), background: "var(--bg2)", color: "var(--tx)" }); });
      });
  }

  function saveTpl() {
    if (!tplText || !tplText.includes("{unsubscribe_url}")) {
      Swal.fire({ icon: "warning", title: "Lipsa {unsubscribe_url}", text: "Sablonul trebuie sa contina variabila {unsubscribe_url} pentru linkul de dezabonare.", background: "var(--bg2)", color: "var(--tx)" }); return;
    }
    setTplBusy(true);
    api("/api/v1/noreply/template", { method: "PUT", body: JSON.stringify({ template: tplText }) })
      .then(function() { mgToast("success", "Sablon salvat."); })
      .catch(function(e) { Swal.fire({ icon: "error", title: "Eroare", text: String(e && e.message || e), background: "var(--bg2)", color: "var(--tx)" }); })
      .finally(function() { setTplBusy(false); });
  }

  function addBl() {
    var em = blInput.trim().toLowerCase();
    if (!em || !em.includes("@")) { mgToast("error", "Email invalid."); return; }
    api("/api/v1/noreply/blacklist", { method: "POST", body: JSON.stringify({ email: em }) })
      .then(function() { setBlInput(""); loadAll(); mgToast("success", "Adaugat in blacklist."); })
      .catch(function(e) { mgToast("error", String(e && e.message || e)); });
  }

  function removeBl(email) {
    api("/api/v1/noreply/blacklist/" + encodeURIComponent(email), { method: "DELETE" })
      .then(function() { loadAll(); mgToast("success", "Eliminat din blacklist."); })
      .catch(function(e) { mgToast("error", String(e && e.message || e)); });
  }

  var inp = { width: "100%", padding: "6px 10px", borderRadius: 6, border: "1px solid var(--bd)", background: "var(--bg)", color: "var(--tx)", fontSize: 13, boxSizing: "border-box" };
  var lbl = { fontSize: 12, color: "var(--t2)", marginBottom: 4, display: "block" };

  return h("div", { style: { display: "flex", flexDirection: "column", gap: 14 } }, [

    h("div", { key: "sw", className: "card", style: { padding: 14, display: "flex", alignItems: "flex-start", gap: 12, flexWrap: "wrap" } }, [
      h("div", { key: "t", style: { flex: 1, minWidth: 240 } }, [
        h("div", { key: "h", style: { fontSize: 14, fontWeight: 700 } }, "Auto-reply no-reply (confirmare primire email)"),
        h("div", { key: "s", style: { fontSize: 12, color: "var(--t2)", marginTop: 3, maxWidth: 680 } },
          enabled
            ? "PORNIT: la fiecare email nou trimis in CTS, expeditorul primeste automat un email de confirmare."
            : "OPRIT: nu se trimite niciun email automat de confirmare.")
      ]),
      h("button", { key: "b", className: "btn", disabled: togBusy || enabled === null, onClick: toggle,
          style: { background: enabled ? "var(--gn)" : "var(--t3)", color: "#fff", whiteSpace: "nowrap" } },
        togBusy ? "..." : (enabled ? "● Activ — Opreste" : "○ Oprit — Porneste"))
    ]),

    h("div", { key: "smtp", className: "card", style: { padding: 14 } }, [
      h("div", { key: "h", style: { fontSize: 14, fontWeight: 700, marginBottom: 12 } }, "Configurare SMTP (cont no-reply)"),
      h("div", { key: "grid", style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 } }, [
        h("label", { key: "host" }, [h("span", { style: lbl }, "SMTP Host"), h("input", { style: inp, value: cfg.smtp_host || "", onChange: function(e) { setCfg(Object.assign({}, cfg, { smtp_host: e.target.value })); } })]),
        h("label", { key: "port" }, [h("span", { style: lbl }, "Port"), h("input", { style: inp, type: "number", value: cfg.smtp_port || 587, onChange: function(e) { setCfg(Object.assign({}, cfg, { smtp_port: parseInt(e.target.value) || 587 })); } })]),
        h("label", { key: "user" }, [h("span", { style: lbl }, "User SMTP"), h("input", { style: inp, value: cfg.smtp_user || "", onChange: function(e) { setCfg(Object.assign({}, cfg, { smtp_user: e.target.value })); } })]),
        h("label", { key: "pass" }, [h("span", { style: lbl }, "Parola (lasă gol pentru a pastra existenta)"), h("input", { style: inp, type: "password", placeholder: cfg.configured ? "••••••••" : "", onChange: function(e) { setCfg(Object.assign({}, cfg, { smtp_password: e.target.value })); } })]),
        h("label", { key: "from", style: { gridColumn: "1 / -1" } }, [h("span", { style: lbl }, "From address (ex: no-reply@cargotrack.ro)"), h("input", { style: inp, value: cfg.from_address || "", onChange: function(e) { setCfg(Object.assign({}, cfg, { from_address: e.target.value })); } })])
      ]),
      h("div", { key: "tls", style: { marginTop: 8, display: "flex", alignItems: "center", gap: 6 } }, [
        h("input", { type: "checkbox", checked: cfg.use_tls !== false, onChange: function(e) { setCfg(Object.assign({}, cfg, { use_tls: e.target.checked })); } }),
        h("span", { style: { fontSize: 13 } }, "Foloseşte TLS/STARTTLS")
      ]),
      h("div", { key: "btns", style: { marginTop: 10, display: "flex", gap: 8 } }, [
        h("button", { key: "sv", className: "btn", disabled: cfgBusy, onClick: saveCfg }, cfgBusy ? "..." : "Salvează configurația"),
        h("button", { key: "test", className: "btn secondary", onClick: testSmtp }, "Testează conexiunea")
      ])
    ]),

    h("div", { key: "tpl", className: "card", style: { padding: 14 } }, [
      h("div", { key: "h", style: { fontSize: 14, fontWeight: 700, marginBottom: 4 } }, "Şablon email auto-reply"),
      h("div", { key: "info", style: { fontSize: 12, color: "var(--t2)", marginBottom: 8 } }, [
        "Variabile disponibile: ",
        h("code", { style: { background: "var(--bg)", padding: "1px 5px", borderRadius: 3 } }, "{unsubscribe_url}"),
        " — link dezabonare (obligatoriu în text)"
      ]),
      h("textarea", { key: "ta", value: tplText, onChange: function(e) { setTplText(e.target.value); },
          rows: 10, style: Object.assign({}, inp, { resize: "vertical", fontFamily: "monospace", fontSize: 12 }) }),
      h("div", { key: "btns", style: { marginTop: 8, display: "flex", gap: 8 } }, [
        h("button", { key: "sv", className: "btn", disabled: tplBusy, onClick: saveTpl }, tplBusy ? "..." : "Salvează şablonul"),
        h("button", { key: "reset", className: "btn secondary", onClick: function() { setTplText(tplDefault); } }, "Resetează la implicit")
      ])
    ]),

    h("div", { key: "bl", className: "card", style: { padding: 14 } }, [
      h("div", { key: "h", style: { fontSize: 14, fontWeight: 700, marginBottom: 10 } }, "Blacklist dezabonare (" + bl.length + " adrese)"),
      h("div", { key: "add", style: { display: "flex", gap: 8, marginBottom: 10 } }, [
        h("input", { style: Object.assign({}, inp, { flex: 1 }), placeholder: "email@domeniu.com", value: blInput, onChange: function(e) { setBlInput(e.target.value); } }),
        h("button", { className: "btn", onClick: addBl }, "Adaugă manual")
      ]),
      bl.length === 0
        ? h("div", { style: { color: "var(--t3)", fontSize: 13 } }, "Nicio adresă în blacklist.")
        : h("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 13 } }, [
            h("thead", null, h("tr", null, [
              h("th", { style: { textAlign: "left", padding: "4px 8px", color: "var(--t2)", fontWeight: 600 } }, "Email"),
              h("th", { style: { textAlign: "left", padding: "4px 8px", color: "var(--t2)", fontWeight: 600 } }, "Data"),
              h("th", { style: { textAlign: "left", padding: "4px 8px", color: "var(--t2)", fontWeight: 600 } }, "Motiv"),
              h("th", null)
            ])),
            h("tbody", null, bl.map(function(item) {
              return h("tr", { key: item.email, style: { borderTop: "1px solid var(--bd)" } }, [
                h("td", { style: { padding: "5px 8px", fontFamily: "monospace" } }, item.email),
                h("td", { style: { padding: "5px 8px", color: "var(--t2)", fontSize: 12 } }, item.added_at ? new Date(item.added_at).toLocaleDateString("ro-RO") : "—"),
                h("td", { style: { padding: "5px 8px", color: "var(--t3)", fontSize: 12 } }, item.reason || "—"),
                h("td", { style: { padding: "5px 8px" } }, h("button", { className: "btn secondary", style: { padding: "2px 8px", fontSize: 11 }, onClick: function() { removeBl(item.email); } }, "Elimină"))
              ]);
            }))
          ])
    ])
  ]);
}

"""

content = content.replace("function Settings() {", NOREPLY_CODE + "function Settings() {")

# ── 2. Tab noreply în SUBS ────────────────────────────────────────────────────
content = content.replace(
    "const SUBS = [ { k:'rules', l:'Reguli' }, { k:'security', l:'Securitate' }, { k:'cts', l:'Conexiune API' }, { k:'backups', l:'Backup-uri' } ];",
    "const SUBS = [ { k:'rules', l:'Reguli' }, { k:'security', l:'Securitate' }, { k:'cts', l:'Conexiune API' }, { k:'backups', l:'Backup-uri' }, { k:'noreply', l:'Mail-uri no-reply' } ];"
)

# ── 3. Case noreply în switch Settings ────────────────────────────────────────
content = content.replace(
    "sub==='cts' ? h(CtsApiPanel, { key:'cts' }) :\n      sub==='security' ? h(SecurityPoliciesPanel, { key:'sec' }) :\n      sub==='backups' ? h(BackupsPanel, { key:'b' }) :",
    "sub==='cts' ? h(CtsApiPanel, { key:'cts' }) :\n      sub==='security' ? h(SecurityPoliciesPanel, { key:'sec' }) :\n      sub==='backups' ? h(BackupsPanel, { key:'b' }) :\n      sub==='noreply' ? h(NoreplyPanel, { key:'noreply' }) :"
)

# ── 4. noreplyBadge în lista emailuri ─────────────────────────────────────────
content = content.replace(
    "h('td', { key: 'fc', style: { whiteSpace: 'nowrap' } }, [h('span', { key: 'b' }, fcBadge(e.fc)), solvedCtsBadge(e, 'sv')]),",
    "h('td', { key: 'fc', style: { whiteSpace: 'nowrap' } }, [h('span', { key: 'b' }, fcBadge(e.fc)), solvedCtsBadge(e, 'sv'), noreplyBadge(e)]),"
)

# ── 5. noreplyBadge în modal detaliu email ────────────────────────────────────
content = content.replace(
    "fcBadge(email.fc),\n                solvedCtsBadge(email, 'sv'),",
    "fcBadge(email.fc),\n                solvedCtsBadge(email, 'sv'),\n                noreplyBadge(email),"
)

with open(MGAPP, "w", encoding="utf-8") as f:
    f.write(content)

print("OK — NoreplyPanel patched into mg-app.js")
