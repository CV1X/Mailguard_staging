# Vision / OCR este DISPONIBIL (extragere din scanate) — 2026-06-16

Capabilitatea de „vision" (citire text din imagini / PDF scanate fără strat text) e **gata de folosit**.
NU mai e nevoie de nicio aprobare — mesajul „canalul vision (în curs de aprobare)" era un stub în codul
nostru, nu o restricție IRIS. (Aprobat de Razvan: 2026-06-16.)

## Cum o folosești (în `app/services/iris_ai.py` → `run_prompt`)
`run_prompt` acceptă acum parametrul **`attachments`**:

```python
res = run_prompt(
    system="Extrage in JSON campurile din acest talon: placa, vin, marca, model, proprietar.",
    content="",                      # transcript gol e OK când trimiți attachments
    response_format="json",
    model_hint="sonnet",            # OBLIGATORIU extern; NU folosi gemma/local (vision local e oprit)
    task="doc_extract",
    attachments=[{"mime_type": "application/pdf", "data_base64": "<base64 fără prefix data:>"}],
)
```
- Pentru PDF: trimite direct PDF-ul (`application/pdf`) — modelul îl rasterizează singur.
- Pentru poze: `image/jpeg` / `image/png` etc.
- Limite gateway: max 10 atașamente, 20 MB base64/atașament.
- Testat OK (placă + VIN extrase corect dintr-un talon de probă).

## Ce ai de cablat în `app/api/v1/documents.py`
La cele 4 puncte unde extragerea LOCALĂ de text returnează gol (în jur de liniile 434, 550, 723, 973),
în loc de eroare „needs_vision", encodează documentul/pagina în base64 și cheamă
`iris_ai.run_prompt(..., attachments=[...], model_hint="sonnet")`.

## Confidențialitate (de știut)
Imaginile/PDF-urile pleacă **neredactate** la modelul extern. Taloanele/CIV au date personale (CNP,
proprietar). Razvan a confirmat că e acceptabil pentru acest modul.
