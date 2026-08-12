-- 2026-06-26: SEED prompturi AI (idempotent, ON CONFLICT DO NOTHING).
-- Backfill al prompturilor de clasificare tunate pe staging, ca sa ajunga pe productie la release.
-- Umple DOAR randurile lipsa pe prod; NU suprascrie prompturi existente acolo (DO NOTHING).
-- NU contine secrete sau settings de stare (graph_refresh_token, o365_delta_link etc. — excluse intentionat).


\restrict NzokYPfIdOrmmqm9sle3uUUBOyyky8YCq8Se4FX9bu1MtAexwTdtVoge9Kg7Pd5




INSERT INTO public.ai_category_prompts VALUES ('informatie', 'Se încadrează la INFORMAȚIE orice email care NU semnalează o problemă/disfuncționalitate activă și NU exprimă nemulțumire față de un esec anterior al companiei, având scop informativ, de coordonare, confirmare sau administrativ.

TIPURI CARE APARȚIN:
1. Cereri de informații sau lămuriri (inclusiv vagi), fără a raporta o eroare sau defecțiune.
2. Solicitări administrative/operaționale: implementare user/șofer, activare serviciu, mutare vehicul, procesare documente, trimitere acte/contracte, furnizare informații, răspunsuri la solicitări de documente.
3. Confirmări și notificări: confirmare plată efectuată, programare, discuție anterioară, trimitere documente, confirmare primire tichet.
4. Actualizări de status operațional: locație vehicul, intrare/ieșire țară, finalizare cursă/descărcare.
5. Redirectionare/transfer: stabilire limbă, transfer la coleg, revenire ulterioară.
6. Apeluri fără obiect: greșeală, pierdut, verificare generală, non-clienți care întreabă ce face compania.
7. Clarificări tehnice fără disfuncționalitate (tonaj, masă, funcționalități platformă, încărcare documente/poze).
8. Clarificări financiare/facturare fără contestare (confirmare plată, suspendare temporară, stabilire facturare, info taxe drum).
9. Comunicări procedurale: modificări procedură, instrucțiuni, suspendări temporare.
10. Confirmări de rezolvare: problemă anterioară s-a rezolvat, fără sesizare nouă. Inclusiv notificări automate de tip ''tichet rezolvat'', ''problemă remediată''.
11. Indisponibilitate și reprogramare: nu poate continua, cere amânare, fără a semnala o problemă.
12. Notificări automate de sistem fără legătură cu o problemă activă a clientului (confirmare creare tichet, confirmare înregistrare vehicul, confirmare ștergere vehicul, confirmare asociere OBU/cont, răspunsuri automate de primire).
13. Emailuri fără conținut substantiv: fără subiect și fără mesaj real, conținând doar semnătură automată, salut scurt sau corp gol.
14. Răspunsuri ale CargoTrack către client (nu ale clientului) sau notificări interne de sistem fără problemă nouă.
15. Transmitere de documente, confirmări de acțiuni sau răspunsuri la solicitări administrative, fără a semnala o problemă.
16. Discuții despre litigii/dosare în instanță sau sume contestate juridic.

TIPURI CARE NU APARȚIN:
- Emailuri în care clientul raportează o eroare, disfuncționalitate, lipsa semnal, card inactiv, suma incorectă, factura greșită, plată eșuată, semnal întrerupt, sold care nu scade, sau orice altă problemă activă.
- Emailuri în care clientul întreabă DE CE apare o situație anormală (suma în minus, două facturi pentru aceeași perioadă, plată pe vehicul greșit, factura fără TVA etc.).
- Emailuri în care clientul raporteaza că o problemă persista sau că nu s-a rezolvat.
- Emailuri în care clientul contestă o factură, o sumă, o taxă sau solicită corectarea unei erori de facturare.
- Emailuri în care clientul raportează că nu poate efectua o acțiune din cauza unei erori (plată eșuată, opțiune lipsă în aplicație, semnal întrerupt, sincronizare imposibilă).
- Notificări automate de tichet intern care descriu o problemă tehnică activă în curs de rezolvare.
- Emailuri care conțin informații despre tranzacții retrase/penalizări aplicate și cer verificare sau contestare.
- Notificări de la autoritati externe (HU-GO, Digitoll, Bulgaria etc.) privind încălcări, penalizări sau utilizare neautorizată a drumurilor.
- Rapoarte zilnice de tranzacții de la procesatori de plăți (ex. EuPlătesc).
- Notificări automate de la sisteme externe (HU-GO, Digitoll etc.) privind înregistrare/ștergere vehicul, asociere/disociere OBU, atribuire vehicul la cont.', '2026-06-26 07:41:13.825269+00', 'raul.covaci') ON CONFLICT DO NOTHING;
INSERT INTO public.ai_category_prompts VALUES ('sesizare', 'Se încadrează la SESIZARE orice email în care clientul semnalează o problemă, disfuncționalitate, eroare sau neconcordanță (tehnică, funcțională, administrativă sau financiară) și așteaptă intervenție/remediere. Sesizarea poate fi exprimată și indirect (''ceva nu e în regulă'', ''de ce apare X?''). Trebuie un element concret defect/eronat/neconcordant sau o notificare externă care necesită acțiune din partea CargoTrack.

TIPURI DE SESIZĂRI:
1. Probleme financiare/administrative: debitări incorecte, facturi greșite, plăți duble, sume necunoscute, discrepanțe între sume, plată atribuită greșit unui vehicul, două facturi pentru aceeași perioadă, facturi fără TVA.
2. Erori de aplicație/software: nu merge descărcarea, dă eroare, nu se actualizează, versiune veche, nu se poate genera token, nu se poate sincroniza, card inactiv în aplicație.
3. Probleme cu dispozitive/carduri: card inactiv/nu funcționează, tahograf nu citește, dispozitiv defect, erori tahograf, semnal lipsă/întrerupt, semnal slab.
4. Probleme de transmisie/vizualizare date: nu transmite, nu se vede mașina, locație greșită, date care nu coincid, transmisie intermitentă, lipsa semnal, sold care nu scade.
5. Probleme de acces/conectivitate: nu pot accesa platforma, nu mă pot loga, cont blocat.
6. Notificări de încălcare/amendă de la autoritati externe (taxe drum, toll violation, HU-GO, Bulgaria, Digitoll etc.) redirectionate către CargoTrack pentru rezolvare.
7. Notificări automate de la sisteme externe (HU-GO, Digitoll etc.) privind înregistrare/ștergere vehicul, asociere/disociere OBU, atribuire vehicul la cont — sunt sesizări operaționale de procesat.
8. Rapoarte zilnice de tranzacții de la procesatori de plăți (ex. EuPlătesc) transmise către CargoTrack.
9. Cereri de ajutor care conțin o defecțiune/eroare raportată (spre deosebire de cereri administrative pure fără problemă).

REGULI CLARE:
- Dacă problema este semnalată PENTRU PRIMA DATĂ → Sesizare.
- Dacă clientul exprima nemulțumire că o problemă ANTERIOARĂ nu a fost rezolvată, cu referire la contactări anterioare esuate → verifica Reclamație.
- O cerere de ajutor (''ajutați-mă'', ''vă rog ajutați'', ''help'') SINGURĂ, fără nicio defecțiune/eroare raportată, NU este Sesizare.
- O cerere administrativă pură (trimite document, activează serviciu, furnizează informație) fără nicio problemă semnalată → NU este Sesizare (este Informație).
- Pentru Sesizare trebuie un element concret defect/eronat/neconcordant sau o notificare externă care necesită acțiune.', '2026-06-26 07:41:13.825269+00', 'raul.covaci') ON CONFLICT DO NOTHING;
INSERT INTO public.ai_category_prompts VALUES ('reclamatie', 'Se încadrează la RECLAMAȚIE orice email în care clientul exprimă nemulțumire explicită față de modul în care compania a gestionat (sau nu) o problemă ANTERIOARĂ. Presupune cel puțin unul din următoarele:
1. Lipsa de reacție la contactări anterioare (''v-am scris și nu a răspuns nimeni'', ''REMINDER'', ''revin la dumneavoastră'', ''am mai primit inca una'').
2. Promisiuni nerespectate (''mi s-a promis că se rezolvă și nu s-a întâmplat'').
3. Problemă repetitivă/nerezolvată – clientul contactează din nou pentru aceeași problemă, inclusiv când menționează explicit că este a doua, a treia oară sau trimite un reminder/follow-up.
4. Nemulțumire privind calitatea serviciului sau eșecul repetat al companiei (''sunt foarte nemulțumit'', ''de câte ori'', ''degeaba'', ''niciodată'').
5. Amenințări de reziliere/plecare ca urmare a unui eșec anterior.
6. Nemulțumire financiară cu referință la un eșec anterior necorectat.

DIFERENȚA FAȚĂ DE SESIZARE:
- Sesizare = problemă semnalată PRIMA DATĂ, fără referință la contactări anterioare esuate.
- Reclamație = clientul a ÎNCERCAT DEJA să obțină rezolvare și compania nu a reacționat adecvat, SAU clientul revine explicit asupra aceleiași probleme nerezolvate (follow-up, reminder, ''revin'', ''am mai primit inca una'' în contextul unei probleme cunoscute).

ATENȚIE:
- Tonul agresiv singur NU e suficient – trebuie referire la un eșec/contactare anterioară.
- Un email care conține doar o întrebare sau o cerere de informații fără nemulțumire față de un eșec anterior este Informație sau Sesizare, chiar dacă tonul este urgent.
- Dacă emailul combină nemulțumire față de lipsa de reacție ȘI o problemă nouă: dacă predomină nemulțumirea → Reclamație; dacă predomină problema nouă → Sesizare.', '2026-06-26 07:41:13.825269+00', 'raul.covaci') ON CONFLICT DO NOTHING;



INSERT INTO public.ai_department_prompts VALUES ('suport_3', 'Suport dedicat pe firul lui Zoli Tyepak.
Tipuri: (1) Emailuri trimise de Zoli Tyepak. (2) Raspunsuri (reply) pe un fir initiat de el sau adresate lui. (3) Solicitari in care el este interlocutorul principal.
Indiciu: expeditorul sau firul contine ''zoli''/''tyepak''.
ATENTIE: contextul persoanei primeaza — subiectul tehnic nu schimba departamentul daca interlocutorul ramane Zoli Tyepak.', '2026-06-24 13:01:10.004536+00', 'raul.covaci') ON CONFLICT DO NOTHING;
INSERT INTO public.ai_department_prompts VALUES ('contabilitate', 'Contabilitate / facturare / evidență financiar-contabilă. Aparțin acestui departament emailurile cu subiect și/sau conținut referitor la: facturi emise de CargoTrack (orice serie: ACTS, ECTS, FS, CHF, TSRR etc.) și chitanțe; extrase de cont și rapoarte zilnice de tranzacții bancare; documente de la cabinete de contabilitate; solicitări de înregistrări contabile, balanțe, situații financiare, fișe partener; ordine de plată (OP-uri) și dovezi de plată cu context clar de plată către CargoTrack (EXCEPȚIE: OP-uri cu seria PPCB, PPBG, PPHU, ASCF merg la suport_1); solicitări de rambursare/returnare sold cu transmitere IBAN; confirmări de plată efectuată; întrebări despre facturi (de ce sunt două, care e scadentă, solicitare copie, contestație); solicitări de amânare/pasire la plată; acte aditionale la contracte cu modificări date firma/J/sediu cu componentă financiară; certificate fiscale proprii ale clientului transmise către CargoTrack; solicitări de virare a banilor din recuperare TVA în cont specific; facturi pentru servicii de recuperare TVA emise de CargoTrack; rapoarte/rezumate zilnice de sume datorate pentru produse toll; invoices externe (engleză/germană) legate de colaborări financiare cu parteneri externi; corespondență financiară internă cu context clar de plată/facturare. NU aparțin: OP-uri cu seria PPCB/PPBG/PPHU/ASCF; emailuri despre rambursare TVA extern, dosare compensare carburant ca serviciu, sau certificate fiscale pentru recuperare TVA extern; facturi de furnizori externi fără legătură cu serviciile CargoTrack; solicitări tehnice pure (activare vehicul, ștergere mașină, probleme platformă, înregistrare vehicule) fără componentă financiară; contracte comerciale noi sau modificări comerciale pure (schimbare J/sediu fără context de plată); solicitări de suspendare/încetare contract fără componentă de plată; emailuri goale/placeholder/notificări de sistem fără context financiar clar; rapoarte Smart Diesel (alimentări, informări credit); solicitări de dezactivare servicii fără componentă de plată; oferte comerciale; corespondență cu autorități externe (VAT registration, SIRET etc.) fără factură CargoTrack; note de compensare sau documente de compensare carburant ca serviciu (doar factura pentru serviciu merge la contabilitate); chitanțe DigiToll sau alte terți pentru taxe drum; solicitări de modificare date firma/J/sediu în contracte de servicii (GPS, toll) fără componentă de plată.', '2026-06-26 08:56:10.649508+00', 'cc-agent:regen-cts') ON CONFLICT DO NOTHING;
INSERT INTO public.ai_department_prompts VALUES ('comercial', 'Departamentul Comercial gestionează: (1) Comenzi și achiziții de produse/servicii (echipamente, dispozitive, soluții de monitorizare, taxe de drum); (2) Oferte comerciale, negocieri și răspunsuri la interesul clientului; (3) Facturi și plăți legate de comenzi și livrări de produse/servicii; (4) Întrebări despre pași și condiții pentru a deveni client sau a implementa soluții. NU aparține: (A) Probleme tehnice cu echipamente (instalare, configurare, funcționare, service, disponibilitate pentru montaj) - suport_1; (B) Modificări de date ale companiei (CUI, sediu, date de contact) - contabilitate; (C) Documente oficiale, procese verbale, contracte în fază de semnare formală - contabilitate; (D) Conturi pe platforme externe sau probleme de livrare de terți - suport_1; (E) Invitații la evenimente, promovări, materiale de marketing - Management General; (F) Rapoarte interne, comentarii de management, task-uri administrative interne - Management General; (G) Feedback sau recenzii pentru alte magazine/platforme - nu aparține; (H) Mesaje de confirmare automată de la platforme externe sau servicii terțe - nu aparține.', '2026-06-26 08:56:44.260168+00', 'cc-agent:regen-cts') ON CONFLICT DO NOTHING;
INSERT INTO public.ai_department_prompts VALUES ('suport_1', 'Tipuri care APARTIN acestui departament:
(1) Facturi emise de CargoTrack catre clienti (orice serie: ACTS, ECTS, FS, CHF, TSRR, etc.) si chitante, trimise de client catre CargoTrack sau reprezentand corespondenta financiara interna. Exceptie: facturile de la furnizori externi (DHL, firme de service, etc.) fara legatura cu serviciile CargoTrack merg la Administrativ.
(2) Extrase de cont si rapoarte zilnice de tranzactii bancare.
(3) Documente si corespondenta de la cabinete/firme de contabilitate (ex. URBAN & ASOCIATII, expert-account, ERP contabilitate).
(4) Solicitari legate de inregistrari contabile, balante, situatii financiare, fise partener.
(5) ORDINE DE PLATA (OP-uri) / dovezi de plata, confirmari electronice de tranzactie, subiecte cu ''paymentId'', ''Confirmare_tranzactie'', ''Confirmare electronica'', ''Copie OP'', ''OP [nume firma]'' — DACA contextul indica o plata catre CargoTrack. Logica: daca seria de factura e PPCB/PPBG/PPHU/ASCF -> suport_1; daca seria e alta identificabila -> contabilitate; daca NU se identifica serie DAR subiectul/contextul indica clar OP sau plata -> contabilitate.
(6) Solicitari de rambursare / returnare sold ramas (ex. sold carGObox, cont Bulgaria, sold general), inclusiv transmitere IBAN pentru restituire sume.
(7) Confirmari de plata efectuata, anunturi ca factura a fost achitata, raspunsuri la notificari de scadenta factura (chiar daca mesajul e scurt/gol aparent, dar contextul threadului e financiar).
(8) Intrebari despre facturi (de ce sunt doua facturi, ce factura e scadenta, solicitare copie factura, solicitare emitere factura anuala, contestatie factura).
(9) Solicitari de amanare / pasire la plata facturilor scadente.
(10) Acte aditionale la contracte cu componenta financiar-contractuala (modificari date firma, J nou, sediu nou). Exceptie: acte aditionale strict comerciale (negociere servicii noi) -> comercial.
(11) Certificate fiscale proprii ale clientului transmise catre CargoTrack. Exceptie: certificat fiscal extern pentru recuperare TVA strain -> recuperare_tva.
(12) Facturi pentru servicii de recuperare TVA emise de CargoTrack catre client.
(13) Rapoarte/rezumate zilnice de sume datorate pentru produse toll.
(14) Invoices externe (in engleza/germana) legate de colaborari financiare cu parteneri externi (ex. Toll4Europe).
(15) Solicitari de virare a banilor din recuperare TVA in cont specific (IBAN).

NU apartin acestui departament:
- Solicitari tehnice pure (activare vehicul, resetare dispozitiv, stergere masina, probleme platforma, inregistrare vehicule, download tahograf, relocalizare GPS, citiri RFID) -> suport_2.
- Contracte de colaborare noi / modificari comerciale pure (fara componenta financiara/contabila) -> comercial.
- Solicitari de suspendare/incetare contract fara componenta de plata -> suport_2 sau comercial.
- Rambursare TVA extern (recuperare TVA din alte tari, dosare compensare carburant ca serviciu) -> recuperare_tva.
- Emailuri despre compensare carburant ca serviciu (documente dosar, contract compensare) -> recuperare_tva sau comercial.
- Taxe de drum (incarcare conturi toll, suspendare taxare, vehicule in vama, amenzi drum, HU-GO, BG-Toll, DigiToll) -> taxe_drum.
- Emailuri goale fara context financiar, notificari externe (Orange, MOL, FAN Courier, etc.), invitații la conferințe, evaluări magazine, feedback-uri -> suport_2 sau alt departament.
- Solicitari de API, integrări Transporeon, probleme tehnice cu platformă -> suport_2.
- Documente fara context clar (PDF-uri goale, imagini fara explicație) -> suport_2 sau alt departament.
- Rapoarte de la furnizori externi (DHL, Ruptela, etc.) cu caracter pur tehnic -> suport_2.
- Notificari de cod de autentificare (Orange, etc.) -> suport_2.
- Solicitari de inregistrare/modificare vehicule in baze de date (placi noi, CNR, inmatriculare) -> mobilitate.
- Solicitari de certificat de calibrare, documente de la institutii publice (CNPP, ANAF) -> operational/administrativ.
- Emailuri de invitatie la workspace, notificari de conferinte, feedback-uri de magazine -> alt departament.', '2026-06-26 08:57:21.136242+00', 'cc-agent:regen-cts') ON CONFLICT DO NOTHING;
INSERT INTO public.ai_department_prompts VALUES ('mobilitate', 'Departamentul Mobilitate gestionează cererile operaționale concrete legate de  documente oficiale ale șoferilor (permise, CIM, declarații IMI, drepturi de reprezentare CNPP), facturi și dovezi de plată pentru servicii generale (nu combustibil/taxe,acte masina ci doar ale soferului).

NU apartine acestui departament un mail care contine documente de masina', '2026-06-26 12:15:44.443411+00', 'raul.covaci') ON CONFLICT DO NOTHING;
INSERT INTO public.ai_department_prompts VALUES ('taxe_drum', 'Departamentul Taxe de drum (taxe_drum) gestionează corespondența financiară și administrativă legată de serviciile de taxe de drum ale CargoTrack. APARTINE acestui departament: (1) Facturi emise de CargoTrack către clienți (orice serie) și chitante, inclusiv solicitări de copie, contestații sau întrebări despre facturi; (2) Ordine de plată (OP-uri) și dovezi de plată către CargoTrack, confirmări electronice de tranzacție — EXCEPTIE: OP-uri cu seria PPCB, PPBG, PPHU sau ASCF merg la suport_1; (3) Confirmări de plată efectuată, anunțuri de achitare, răspunsuri la notificări de scadență; (4) Solicitări de rambursare/returnare sold rămas (carGObox, conturi țări, sold general) și transmitere IBAN pentru restituire; (5) Solicitări de amanare/pasire la plată facturilor scadente; (6) Extrase de cont și rapoarte zilnice de tranzacții bancare/toll (ex. rapoarte ITS Bulgaria cu sume datorate); (7) Documente și corespondență de la cabinete/firme de contabilitate; (8) Solicitări legate de înregistrări contabile, balanțe, situații financiare, fișe partener; (9) Acte adiționale la contracte cu componentă financiară-contractuală (modificări date firma, J nou, sediu nou); (10) Certificate fiscale și documente fiscale proprii ale clientului transmise CargoTrack; (11) Solicitări de virare a banilor din recuperare TVA în cont specific (IBAN); (12) Facturi pentru servicii de recuperare TVA emise de CargoTrack; (13) Invoices externe (engleză/germană) legate de colaborări financiare cu parteneri (ex. Toll4Europe); (14) Emailuri goale/fără conținut cu context financiar clar (plată, OP, factura, scadență); (15) Întrebări și clarificări ale clienților privind taxele de drum datorate, soldul contului de taxe, sau tranzacții în conturi de taxe (e-toll, HU-GO, ITS Bulgaria, Digitoll etc.) — NU alertări/avertismente directe de la operatori; (16) Solicitări de suspendare/reactivare taxării pe anumite țări pentru vehicule specifice cu context de plată sau gestionare cont. NU APARTIN: solicitări tehnice pure (activare vehicul, ștergere mașină, probleme platformă, înregistrare vehicule noi) — suport_1; contracte de colaborare noi sau modificări comerciale pure — comercial; suspendare/încetare contract fără componentă de plată — suport_1/comercial; rambursare TVA extern, dosare compensare carburant ca serviciu — recuperare_tva/comercial; facturi de furnizori externi fără legătură cu serviciile CargoTrack — Administrativ; alertări/avertismente directe de la operatori de taxe de drum (HU-GO, hu-go, ITS Bulgaria, Digitoll etc.) privind încălcări sau amenzi — suport_1; rapoarte operaționale de OBU-uri și conturi de la parteneri externi — mobilitate; întrebări despre funcționalități de aplicație, reîncărcare cont, activare dispozitive — suport_1; probleme cu monitorizare GPS sau dispozitive de urmărire — suport_1.', '2026-06-26 08:56:37.204845+00', 'cc-agent:regen-cts') ON CONFLICT DO NOTHING;
INSERT INTO public.ai_department_prompts VALUES ('suport_2', 'Cereri de resetare/restartare dispozitiv, reconfigurare echipament, descărcare date tahograf, verificare transmisie dispozitiv, probleme de conectivitate/localizare dispozitiv, citiri RFID-BOX. APARTINE: (1) Emailuri prin care clientul solicita resetare, restartare, reconfigurare sau descărcare date tahograf pentru un dispozitiv specific (cu identificator vehicul/IMEI/număr înmatriculare). (2) Cereri de verificare stare dispozitiv, transmisie, conectivitate sau relocalizare cu mențiune explicită de resetare/restartare. (3) Solicitări de citiri/date din echipamente de monitorizare (RFID-BOX, sonde nivel). NU APARTINE: (A) Emailuri cu date de alimentare/consum din sisteme automate (Smart Diesel, OMV) sau dovezi de plată/limite de credit - mergi pe contabilitate. (B) Cereri de certificat de calibrare senzor fără context de defectiune dispozitiv - mergi pe operational. (C) Defecțiuni generale ale dispozitivului (erori, scurgeri combustibil, probleme de măsurare) fără solicitare explicită de resetare/reconfigurare - mergi pe suport_1. (D) Emailuri goale, cu doar confirmări scurte ("Bine", "E pornită", "Tot nu merge") sau răspunsuri fără context de acțiune - mergi pe suport_1. (E) Cereri de integrare API, configurare LCM, probleme OBD, descărcare directă din aparat, comenzi SMS tehnice - mergi pe suport_1. (F) Emailuri de la furnizori externi (Ruptela, Orange) cu confirmări de ticket, notificări automate, coduri de autentificare sau răspunsuri tehnice generale - mergi pe suport_1. (G) Emailuri interne de transmitere ticket către departamentul tehnic fără solicitare directă de client - mergi pe suport_1.', '2026-06-26 08:56:20.301186+00', 'cc-agent:regen-cts') ON CONFLICT DO NOTHING;
INSERT INTO public.ai_department_prompts VALUES ('recuperare_tva', 'Departament: Recuperare TVA (recuperare_tva)

APARTIN acestui departament:
(1) Corespondență de la cabinete/firme de contabilitate externe legate de recuperare TVA sau dosare de compensare carburant (contract, documente dosar, activări conturi A.R.R., confirmări de plată pentru serviciul de compensare).
(2) Certificate fiscale și documente fiscale ale clientului transmise către CargoTrack în context de recuperare TVA.
(3) Emailuri goale/fără conținut/doar semnătură cu subiect care indică clar recuperare TVA sau compensare carburant.
(4) Notificări/confirmări de plată din sistemele externe (A.R.R., autorități fiscale) privind dosarele de compensare carburant sau recuperare TVA.

NU APARTIN acestui departament:
- Facturi emise de CargoTrack, note de compensare, confirmări de plată pentru servicii de recuperare TVA/compensare carburant -> contabilitate
- Solicitări de virare a banilor din recuperare TVA în cont specific (IBAN) -> contabilitate
- Intrebări despre facturi CargoTrack, solicitări de copie factura, contestații -> contabilitate
- Emailuri despre VAT registration, SIRET, înregistrări fiscale în alte țări -> contabilitate
- Solicitări comerciale pentru încheierea de contracte noi (fără context de dosare existente) -> comercial
- Contracte de colaborare transmise de CargoTrack către client (inițierea relației) -> suport_1
- Emailuri fără conținut cu subiecte generice (invitații workspace, notificări marketing, redirecționări externe, oferte terți) -> suport_1
- Orice altă corespondență financiară, facturi, ordine de plată, extrase de cont -> contabilitate', '2026-06-26 08:56:59.039931+00', 'cc-agent:regen-cts') ON CONFLICT DO NOTHING;



\unrestrict NzokYPfIdOrmmqm9sle3uUUBOyyky8YCq8Se4FX9bu1MtAexwTdtVoge9Kg7Pd5

