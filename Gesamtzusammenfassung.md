# BallastConverter – Gesamtzusammenfassung aller Recherchen (Stand 2026-09-24)

Dieses Dokument fasst alles zusammen, was zwischen dem 2026-09-10 und dem 2026-09-18 recherchiert, gemessen und
getestet wurde, und wird bei neuen Erkenntnissen fortgeschrieben. Die Einzelnotizen mit allen Rohzahlen liegen
lokal in `recherche/` (nicht Teil des Repositories); am Ende steht ein Verzeichnis, welche Datei was enthält.

Material: Flextight X5, 3F-Scans (`.fff`) von Kodak Portra 400, FlexColor 4.8.13 Mac, Nacharbeit in Lightroom.

---

## 0. Das Wichtigste auf einer Seite

1. **ColorNeg ist eine Potenzfunktion je Kanal**: `pos_c = (lo_c / x_c)^g_c − Schwarzpunkt`. Keine Maskensubtraktion,
   keine Matrix, keine Kurve. Die Orangemaske verschwindet durch die kanalweise Normierung auf `lo_c`.
2. **Die Film-Gammas des Plugins sind Datenblattwerte**: `g = 1 / Steigung der Status-M-Kennlinie`. Für Portra 400
   trifft die Plugin-Tabelle das Kodak-Datenblatt E-4050 auf 0,003–0,007.
3. **3F-Rohdaten sind nicht linear**, sondern der Geräteraum des Profils „Flextight X5 & 949.icc“ (effektiv
   Gamma ≈ 1,75, je Kanal leicht verschieden). Linearisierung mit `--in-curve "icc:Flextight X5 & 949.icc"`.
4. **Das Datenblatt-Blau-Gamma (1,57) ist für jeden RGB-Abtaster zu niedrig.** Auf dem X5 will Blau 1,85–1,95,
   bestätigt auf fünf unabhängigen Wegen (Grey-World-Fit, Neutralflächen-Fit, Fuji-Balance-Gerade, Noritsu-Nachbau,
   fremde IT8-auf-Film-Messung negicc). Ursache: RGB-Filter gegen Status-M-Dichte, nicht der Scanner und nicht das Profil.
5. **Rot bleibt offen**: 1,70 / 1,80 / 1,90 / 1,81 je nach Methode. Das entscheidet nur das Auge am Vollbild.
6. **Der konstante Farbstich je Bild ist motivabhängig** (Perzentil-Anker). Filmkonstante Anker (Fuji-Art,
   Filmträger-Balance) waren im Test schlechter, nicht besser. Eine Grau-Balance je Bild (Minilab-Art) trifft dagegen
   die Handkorrektur des Nutzers bis auf 0,07–0,09 Blenden (5.8, 2026-09-23); ob sie in den Konverter kommt oder
   Temp/Tint in Lightroom bleibt, ist Sache des Nutzers.
7. **Kein anderes Programm hat ein besseres Filmmodell.** FlexColor, VueScan, SilverFast, Epson, Frontier, Noritsu,
   OpenEnlarge: alle bestehen aus Ankern je Kanal plus Kurve/Gamma. Übernehmenswert ist nur der
   **Filmträger-Anker je Rolle** (VueScan, OpenEnlarge) und der **Graukeil vom Monitor auf Film** als Messtarget.

Aktuelle Portra-400-Presets im Programm:

| Preset | R | G | B | Herkunft |
|---|---|---|---|---|
| Portra 400 [4056] [5056] [6056] (Plugin) | 1,834 | 1,804 | 1,567 | Plugin-Tabelle |
| Portra 400 (2026) | 1,837 | 1,811 | 1,570 | eigener Fit am Datenblatt E-4050 |
| Portra 400 (X5 fit) | 1,80 | 1,811 | 1,91 | Grey-World-Fit über 7 Scans |
| Portra 400 (X5 neutral) | 1,70 | 1,811 | 1,95 | Fit auf 15 bestätigten Neutralflächen |
| Portra 400 (X5 balance) | 1,90 | 1,811 | 1,85 | Fuji-Balance-Gerade über 7 Scans |
| (Kandidat, nicht eingebaut) | 1,81 | 1,81 | 1,81 | Noritsu-Nachbau |
| Generic | 1,70 | 1,63 | 1,48 | Median der Plugin-Tabelle |

---

## 1. ColorPerfect ColorNeg – Reverse Engineering (2026-09-10)

Quelle: `ColorPerfect64.8bf` (Build 2018-08-28), Ghidra 11.3.2, ImageBase 0x10000000. Werkzeuge und dekompilierter
Code liegen in `~/.cache/cp_re` (`out/*.c`). Hilfetexte im Binary dienten nur zur Benennung. colorperfect.com gilt
laut Nutzer im Zweifel als falsch und wird nicht als Beleg benutzt.

### 1.1 Eingabe
- 16-Bit-Werte 0..32768, geklemmt auf 0x7FFF; 8 Bit × 128.
- `lin[i] = decode(i / 32768)`; decode = GammaC-Kurve des Startfensters. Bei G/L = **L** (Standard) Identität.
- Histogramm je Kanal über die Rohcodes (32768 Bins).

### 1.2 Filmtabelle
- Adresse 0x100784f0, 996 Datensätze à 40 Byte {Hersteller, Name, a, b, c}. Index 0..309 Negativfilme,
  310..995 Digitalkameras (PerfectRAW).
- Leicht verschleiert; die Gammas entstehen aus a, b, c und dem Index i:

      gR = 0.5 * (a + b       - i/100)
      gG = 0.5 * (a - b       - i/100)
      gB = 0.5 * (a + b + 2c  - 3i/100)

- Beispiele: Portra 400NC 1,89/1,82/1,64, Ektar 100 1,84/1,84/1,56, Superia X-TRA 400 1,55/1,45/1,38,
  „B&W Start“ 1/1/1. Alle 310 in `filmgammas.txt`.
- `.negpos`-Dateien speichern die drei Gammas direkt; „Film Gamma“ skaliert alle drei; |Gamma| außerhalb 0,1..10
  setzt alle auf 1,0.

### 1.3 Kern (0x100182e0, mode == 1)

    lo_c = lin[unteres Perzentil p_black]      (Standard 0,5 %; dichteste Stelle, wird Weiß)
    hi_c = lin[oberes  Perzentil p_bpoint]     (Standard 0,5 %; dünnste Stelle/Filmbasis, wird Schwarz)
    LUT_c[i] = (lo_c / lin[i]) ^ g_c
    BPoint    = min_c (lo_c/hi_c)^g_c
    BPColor_c = (lo_c/hi_c)^g_c − BPoint

### 1.4 Pixel-Pipeline (0x1000aa20)
1. LUT, 2. Schwarzpunkt abziehen (`− BPoint − BPColor_c`), 3. (nur PerfectRAW) Kameramatrix,
4. `× 2^(−Black) × CC_c`, 5. optionale Bildwerkzeuge (Gamma über Luminanz, White, Zonen, Sättigung),
6. Untergrenze 3,2e-5, Encode in die Ausgabekurve. Nur 1, 2 und 4 sind die Umwandlung.

### 1.5 Folgerung: Levels = Film-Gamma
Weil die Umwandlung je Kanal eine Potenzfunktion ist, entspricht der Mitteltonregler einer Tonwertkorrektur auf
einem Kanal exakt dem Skalieren des Film-Gammas dieses Kanals (Levels 1,1 auf Rot = g_R · 1,1), und die Graupipette
entspricht CC bzw. einer Korrektur von `lo_c`. Voraussetzung: 16 Bit, kein Clipping (mit Luft konvertieren,
`--black 0.5..1`). Lightroom hat keinen Kanal-Gamma-Regler, deshalb muss dort das Preset stimmen.

Faustformel für Gamma-Korrektur aus einer dunklen Neutralfläche: `Δg_c ≈ log(e) / log(p)` (e = Fehlfaktor im Kanal,
p = Wert der Fläche im Positiv). Gleiche Kanalverhältnisse auf heller und dunkler Fläche = CC-Fall (Pipette),
unterschiedliche = Gamma-Fall.

---

## 2. Kodak Portra 400 – Datenblatt E-4050 (Feb. 2016)

Kennlinien (Seite 4) als Vektorpfade aus dem PDF gelesen, Fehler < 0,01 D. Rohwerte: `portra400_kennlinien.txt`
(Status M, Daylight, Log H Ref −1,44), im Programm als `curves/kodak_portra_400.txt`.

| Kanal | D-min | Steigung −2,2..−0,2 | 1/Steigung | Plugin |
|---|---|---|---|---|
| R | 0,219 | 0,544 | 1,837 | 1,834 |
| G | 0,646 | 0,552 | 1,811 | 1,804 |
| B | 0,867 | 0,637 | 1,570 | 1,567 |

- Herleitung: T ~ H^(−s), pos = (lo/T)^g ~ H^(s·g); linear in H bei g = 1/s.
- Geradlinigkeit über 10 Blenden (log H −2,4..0,56): Abweichung ≤ 0,017 D. Ein Gamma je Kanal ist für diesen Film
  ein sehr gutes Modell.
- Rot leicht gekrümmt (0,51 Schatten → 0,58 Lichter): wenige Prozent Farbdrift, nicht per Gamma korrigierbar.
- Fuß: etwa 0,5 log H (1,7 Blenden) von D-min bis zur Geraden. Der Schwarzanker liegt in diesem Fuß.
- Graukarte normal belichtet: Rot-Dichte 0,77–0,87, d. h. ca. 22–28 % der Basis-Transmission (Plausibilitätscheck).
- Grenze: alles Status M. Ein Scanner sieht die Farbstoffe durch eigene Filter (siehe Abschnitt 6 und 10).

### Datenblatt-Fuß/Schulter als Option (2026-09-13, erweitert 2026-09-18)
- Checkbox „Datasheet toe/shoulder curve“ / `--datasheet-curve`, nur für Portra 400 (2026) und die drei X5-Presets,
  nie für den Plugin-Eintrag. Aus = bitidentisch zum Plugin-Modell (verifiziert).
- Modell: Term = inverse Kennlinie minus ihre Gerade; der Schwarzanker des Scans sitzt an der Datenblattdichte, an
  der der Fuß die halbe Steigung hat (R 0,276 / G 0,702 / B 0,926); lineare Rampe macht den Term an beiden Ankern
  exakt null. `LUT *= 10^term`.
- X5-Presets: Scannerdichte → Datenblattdichte über `gamma · slope`; weicht das in einem Kanal ≥ 0,02 von 1 ab,
  wird die **Grün-Kurve für alle Kanäle** benutzt (rein belichtungsabhängig; Mittelton-Farbverschiebung max. 0,03
  statt 0,06 Blenden). Begründung: negicc zeigt, dass der Portra-Fuß nahezu neutral ist.
- Wirkung: 18-29 mit (2026): Schatten knapp über Schwarz 20–27 % heller, Kanalverhältnisse nur 2–5 % anders,
  Mitten +5 %, Lichter unverändert. 19-57 mit X5 balance: Schatten +0,3..0,6 Blenden, Neutralflächen < 3 %.
- Grenzen: Lage des Fußes ist eine Annahme (kein Filmrand im Bild → wahres D-min unbekannt); Datenblatt = frischer
  Film, Normentwicklung, Status M. Bei High-Key-Bildern kann es schlechter sein.

---

## 3. 3F/FFF-Format und Kodierung (2026-09-10)

### 3.1 Dateiaufbau (18-29_16.fff)
- Big-Endian-TIFF, 3 Seiten: Rohbild 7883×11068×3 uint16, zwei Vorschauen 492×691 (8 und 16 Bit).
- Alle Rohwerte Vielfache von 4 → 14-Bit-Daten im 16-Bit-Container, Maximum 65532. Jeder 4. Code belegt, in allen
  Kanälen gleich (keine nachträgliche Software-Kurve auf ADC-Daten, keine kanalabhängige Kodierung).
- Perforationslöcher gesättigt (65532) → kein Messpunkt. Filmträger R 50324 / G 35208 / B 27492.
- Private Tags: 46277 (Setups binär), 46279 (Version, Scanner FX09269022), 50457 (Setups als plist),
  50458 (8-Bit-Rohthumbnail).

### 3.2 FlexColor-Wissen
- Bis 4.0 „Gamma“-Regler (Standard 2,0); ab 4.5 ersetzt durch „Midtone“ (Gamma = Midtone + 1; altes 2,2 = 1,20).
  Profile sind für Midtone 1,00 kalibriert. Im plist steht weiter „Gamma = 2.0“.
- 3F enthält Rohdaten; Setups verändern sie nicht. Export: 3F laden, „Save…“ schreibt TIFF.

### 3.3 Entscheidender Test (Export A/B)
- **Export A** (Midtone 1,0, alles aus, Convert aus) ist **bitidentisch** mit den 3F-Rohdaten.
- **Export B** (Convert nach Adobe RGB) lässt sich exakt nachrechnen: Rohdaten → **A2B0-LUT** des Profils → Lab →
  Bradford → Adobe RGB. RMS 0,25 % (0,6 von 255 Stufen). Der Matrix/TRC-Weg liegt 5–18 Stufen daneben.
  **FlexColor rechnet mit der LUT.**
- Damit sind die Rohdaten der Geräteraum des Profils. Das Profil enthält seine IT8-Messdaten (528 Felder,
  12.9.2005): Gerätewert ~ Y^(1/1,75). TRC je Kanal R ~x^1,67, G ~x^1,55, B ~x^1,61, in den Schatten flacher
  (~1,2), in den Lichtern steiler (~2,0).
- Fazit: nicht linear, nicht 2,2, nicht 1,8; „nur Rot gammakodiert“ widerlegt; Mac/Windows egal.

### 3.4 LUT gegen TRC (2026-09-16)
- Profil: ICC v2, PCS Lab, A2B0/1/2 (mft2, Gitter 17, 515er Ein-/Ausgangstabellen) **und** Matrix + TRC.
- Die TRC-Tags sind **Polygonzüge** mit Stützstellen bei 0 / 0,1 / 0,2 / 0,3 / 0,5 / 0,7 / 1,0, unter 0,1 eine
  Gerade auf null. Die Roh-Histogramme zeigen dort keinen Sprung → die echte Kodierung ist glatt, das Polygon
  eine Näherung.
- Die aus der LUT abgeleitete Kanalkurve liegt am dichten Ende weit unter der TRC (Faktor TRC/LUT bei Code
  0,1–0,3: R 1,5–1,9, G 1,2–1,3, B 1,35–1,7). Die Weißanker der Scans (R 0,18–0,29, G 0,11–0,19, B 0,08–0,15)
  liegen genau dort.
- Der Konverter benutzt nur die TRC. Ein reiner Potenzfehler der Eingangskurve ist exakt äquivalent zu skalierten
  Film-Gammas; nur die Kurven*form* zählt. Auf den Neutralflächen passt die TRC besser als die LUT-Kurve und als
  Gamma 1,8 (Kosten 0,125 gegen 0,189) → TRC bleibt. Endgültig klären würde es nur ein Keil/IT8 als 3F.

### 3.5 Zweiter 3F vom Labor und Schachbrett (2026-09-18)
- Dasselbe Negativ (19-57_23) vom Labor als Imacon 3F: Roh gegen Roh Steigung 0,983 / 0,991 / 1,003, Verhältnis
  konstant 0,984 / 0,978 / 0,937 → **gleiche Kodierung, kein additiver Offset**, Labor-Scanner ~6 % weniger Blau.
  Offset-Varianten verschlechtern den Neutralfit. Offset-Hypothese erledigt.
- **Eigene X5-Scans haben ein 2×2-Schachbrett** (R 0,2 %, G 0,7 %, B 1,7 %; in den hellsten 1 % Blau bis 3,5 %),
  Vorzeichen hängt vom Zuschnitt ab; der Labor-3F hat keins. Ursache unbekannt. Ein gerader Subsampling-Schritt
  trifft nur eine Phase → Blau-Weißanker 8 % daneben, Vorschau 0,13–0,19 Blenden blauer als das Endbild.
  **Behoben:** Vorschau und `--subsample` nehmen immer einen ungeraden Schritt (Commit a576e96).

---

## 4. FlexColor-Filmsetups „Kodak Portra 400 NC/VC“ (2026-09-13)

- Filmspezifisch sind nur: Shadow und Highlight je Kanal, Gray (Mittelton) je Kanal, Sättigung +15. Alles andere
  neutral (Kurven Identität, ColorCorr 36 Nullen, keine Matrix).
- NC: Shadow 320/4096/6976, Highlight 11328/13952/14912, Gray 123/135/120. VC: 256/3840/7168,
  11840/14336/15040, 118/130/115.
- Endpunkte im invertierten 14-Bit-Raum: `raw16 = (16383 − Wert) · 4`. Es sind Messwerte eines Referenznegativs
  (Basis 0,2–0,25 D dünner als unsere), keine Filmkonstanten; mit RemoveCast = true setzt FlexColor sie ohnehin neu.
- Dichteumfang G/R und B/R: NC 1,24 / 1,39, unser Scan 1,07 / 1,21, Datenblatt 1,02 / 1,17. NC/VC = alte
  Portra-Generation.
- Gray-Semantik ungeklärt (Lesart A trifft B/G 0,84 gegen ColorNeg 0,87, aber nicht R/G).
- **Fazit:** kein Filmmodell, nur ein Levels-Satz. Strukturell dasselbe wie ColorNeg. Das Scannerwissen steckt
  allein im Eingangsprofil.

---

## 5. Gamma-Fit an den eigenen Scans (2026-09-16/17)

### 5.1 Datensatz
10 Scans, gleiches Setup. Die Filmmaske im Rand (G−R, B−R) trennt sie:
- **Portra-7** (G−R 0,26–0,28, B−R 0,47–0,50): 16-116, 16-131, 17-89, 18-29, 18-52, 19-57, 19-62.
- 14-59 (0,30/0,51) und 15-55, 16-74 (0,23–0,24/0,40–0,42): vermutlich andere Filme, nicht im Fit.

### 5.2 Methode
Tonwert-Signatur: Median von R/G und B/G je Halbblenden-Stufe des Positivs (−6 Blenden bis Weißanker). Eine
Pipette je Scan wird herausgerechnet; der Rest ist der **Crossover**, den nur ein Gamma beheben kann. Fit von gR
und gB bei festem gG = 1,811.

### 5.3 Befund mit dem Datenblatt-Preset

    R: -13.8 -14.3 -13.5  -4.3  +3.2  +4.0  +2.3  -1.3  -2.8 -10.3 -11.3  -8.7
    B: +31.4 +23.0 +14.7  +6.7  +2.3  +2.1  -0.0  -7.3 -14.2 -17.0 -15.8 -15.4

- Blau: echter Crossover (Schatten zu blau, Lichter zu gelb), in allen Scans.
- Konstanter Anteil je Scan −33..+18 % in R/G = Motivabhängigkeit der Anker.
- Perzentil 0,1 % gegen 1 % ändert wenig; höhere Perzentile machen kühler. Der „1 % plus global zurückholen“-Trick
  ist nicht der Hebel.

### 5.4 Ergebnisse

| | R | G | B | Kosten |
|---|---|---|---|---|
| Preset | 1,837 | 1,811 | 1,570 | 7,54 |
| Grey-World-Fit Portra-7 | **1,80** | 1,811 | **1,91** | 4,81 |
| ohne die zwei dunkelsten Stufen | 1,87 | | 1,84 | |
| alle 10 Scans | 1,85 | | 1,88 | |

Einzelscans: Blau 1,53 / 1,95 / 2,34 / 2,05 / 1,99 / 1,91 / 1,99 (robust), Rot 1,52–2,03 (motivabhängig).

Sechs Linearisierungen: Blau will **immer 1,90–2,05**; Rot 1,45–1,50 mit der LUT-Kurve, 1,70–1,90 sonst. Nach dem
Fit sind alle ähnlich konsistent (4,1–4,9) → aus Scans allein nicht entscheidbar.

### 5.5 Fit auf bestätigten Neutralflächen
37 Kandidaten vorgeschlagen, 15 vom Nutzer bestätigt (Asphalt, Beton, Pflaster, weiße Farbe, Baumwolle, Gummi).
- Blau in dunklen Flächen +15..+41 %, in hellen −5..−18 %. **Auch Rot hat einen Crossover** (dunkel −8..−26 %);
  die „Rot-Beule“ der Statistik war Haut in den Mitteltönen.
- Fit: Pipette je Scan 1,68 / 2,06; eine Pipette für alle 1,70 / 1,86; Leave-one-out stabil.
- Preset **X5 neutral 1,70 / 1,811 / 1,95**: Rest Blau rms 16 % → 5,9 %, Rot 7,3 % → 5,0 %, Maximum 32 % → 11 %.

### 5.6 Lightroom-Probe und konstanter Stich (2026-09-17)
- X5 neutral nach der WB-Pipette „auf den ersten Blick okay“. Konstanter Stich braucht Temp −6..−9 / Tint +19..+30.
- Deckt sich mit der Messung: B/G im Mittel −24 % (Streuung 20 %), R/G −1 %.
- Ursache: das höhere Blau-Gamma dreht um den Blau-Weißanker (0,1-%-Perzentil, draußen oft Himmel), nicht das Profil.
- Balance am Filmträger verankern wurde getestet und ist **schlechter** (Streuung R 20 %, B 28 %), obwohl die
  Trägerverhältnisse auf ±2 % konstant sind.
- Entscheidung: kein Preset-CC, keine Auto-Pipette; der Stich bleibt der Lightroom-Pipette (Startvorschlag
  Temp −7 / Tint +25, mit Luft konvertieren).

### 5.7 Zweifel
Noritsu- und Sigma-Bild desselben Negativs zeigen den „schwarzen Schuh“ (19-57 #4) viel blauer als den Beton.
Entweder nicht neutral oder Himmelslicht im Schatten. Der Fit ist robust gegen Weglassen (1,68/2,04), aber „dunkle
Schattenfläche als neutral gefittet“ betrifft auch 17-89 #2, 18-29 #4, 19-62 #4. Klären können das nur Bildpaare
(Scan + eigene fertige Korrektur).

### 5.8 Bildpaare Konverter → Lightroom (2026-09-21)
10 Scans, Preset X5 neutral, Weiß/Schwarz 0,1 %; Lightroom-Fassung nur mit Temp/Tint (Mittel −7 / +14), sonst nichts.
- Lightrooms Weißabgleich auf ein TIFF ist kein reiner Faktor: konstant bis −3 Blenden unter Weiß, in den obersten
  zwei Blenden läuft er auf ca. 40 % aus.
- Konverter-Ausgang: Blau fehlt von −5 bis −1 Blenden **konstant** ≈ 0,27 Blenden → Ankerfehler, kein Gammafehler.
  Blau-Gamma 1,95 bestätigt; Rot höchstens +2 % (im Fehler). Kein Anlass für Rot 1,80/1,90.
- Lightroom-Fassung: Mitten neutral, Lichter ≈ 0,1 Blende grünlich-gelb (der Teil, den der auslaufende Weißabgleich
  nicht erreicht), tiefste Tiefen (unter −7 Blenden) Rot +0,2 Blenden, schon im Konverter-Ausgang.
- **Ursache gefunden:** Das 0,1-%-Perzentil des Weißankers wird am Einzelpixel bestimmt; im Blaukanal sind das
  Kornausreißer. Perzentil an 3×3-Blockmitteln statt am Pixel: Positiv R +0,02 / G +0,06 / B +0,19 Blenden, also
  Blau − Grün +0,13 (5×5: +0,15), je Bild 0,06 … 0,29. Das ist etwa die Hälfte des Stichs; der Rest bleibt
  motivabhängig. Korrigiert 5.6 („draußen oft Himmel“): ein großer Teil ist Korn, nicht Motiv.
- Abhilfe eingebaut (2026-09-21): Option „Low-grain anchors“ (GUI-Checkbox, `--grain [N]`, Standard 5×5, Dateiname
  `_lg5`); beide Anker aus Blockmitteln, Bild selbst unverändert, aus = bitidentisch.
- Test an den 10 Paaren (Region = Lightroom-Beschnitt): 5×5 hebt Blau gegen Grün um 0,16 Blenden (0,07 … 0,27), das sind
  40 % der Lightroom-Korrektur von +0,41; Rest +0,25. Streuung der nötigen Blau-Korrektur 0,19 → 0,14. Korrelation
  Kornwirkung ↔ Lightroom-Korrektur je Bild 0,85. 7×7 bringt kaum mehr. Rot −0,04 (15-55: −0,12, falsche Richtung).
- Form des Rests: entsteht ganz in der obersten Blende (B/G −0,07 unter Weiß → −0,28 bei −1 Blende), darunter bis
  −5 Blenden parallel. Also kein Gammafehler: die Gamma-Geraden reichen von −1 bis etwa −6 Blenden; Abweichungen nur
  ganz oben (Blau) und ganz unten (Rot +0,2 unter −7 Blenden).
- Geprüft und als Ursache des Mittelwerts verworfen: Polygon-TRC des Profils. Sie liegt zwischen den Stützstellen bis
  7 %, unter Code 0,1 bis 45 % über einer glatten Kurve, und die Blau-Weißanker liegen dort; glatte Kurve ändert den
  Mittelwert aber nicht (0,13 statt 0,14), nur je Bild −0,2 … +0,16 Blenden (Streuung des Rests 0,14 → 0,10).
- Motivanteil sichtbar: bei 3 von 10 Bildern sitzen Rot- und Blau-Anker auf verschiedenen, farbigen Stellen (Haut,
  rote Gegenstände gegen Weiß/Himmel). Lightrooms Weißabgleich lässt Weiß weiß, die Paare können deshalb nicht
  entscheiden, wie die hellsten Stellen „richtig“ aussähen. Trennen kann das nur ein Keil/IT8 auf Film.
- **Bestätigung am Nutzer-Ergebnis (2026-09-22):** die 10 Scans mit „Low-grain anchors“ 5×5 konvertiert, in
  Lightroom erneut nur Temp/Tint gesetzt. Tatsächliche Wirkung in den Dateien: Blau − Grün +0,16, Rot − Grün −0,04
  Blenden, konstant über die Helligkeit, genau wie im Test. Nötige Blau-Korrektur halbiert: +0,42 → +0,21 Blenden
  (Temp im Mittel −7 → −1, Tint +14 → +12); der Nutzer nahm sogar 0,05 mehr zurück als die Option bewirkt.
  Streuung zwischen den Bildern bleibt 0,17 – die vier Bilder mit dem größten Rest sind dieselben (Motivanteil).
  Nebenbefund: Lightrooms Temp/Tint auf ein TIFF ist linear in Blenden (Restfehler 0,01–0,02):
  R − G = 0,0152·Temp + 0,0064·Tint, B − G = −0,0329·Temp + 0,0141·Tint; für Rückmeldungen reichen also die XMP-Werte.
  Wiederholung der Helligkeitsanalyse mit 5×5-Blöcken: gleiches Ergebnis wie mit 15×15.
- **Grau-Balance je Bild trifft die Handkorrektur (2026-09-23):** Stellt man den Konverter-Ausgang zusätzlich „im
  Mittel grau“ (Minilab-Art, farbschwache Pixelbevölkerung, Fuji-Verfahren 3), entspricht das der Lightroom-Korrektur
  des Nutzers mit Korrelation 0,9 je Bild; Rest im Mittel 0, Streuung 0,07 (R) / 0,09 (B) Blenden, praktisch die
  Wiederholgenauigkeit des Reglers (0,06). Low-grain-Anker allein: Mittel +0,21, Streuung 0,17. Der Nutzer korrigiert
  also faktisch nach Grau-Integral. **Eingebaut** (2026-09-23, Wunsch des Nutzers, Standard an, ebenso die
  Korn-Option): an den 10 Paaren bleibt mit beiden Optionen ein Lightroom-Bedarf von im Mittel R −0,03 / B 0,00,
  Streuung 0,07 / 0,06 Blenden (vorher B +0,42, Streuung 0,18). Begrenzung 0,75 Blenden je Kanal (0,5 griff bei zwei
  normalen Bildern). Der gehobene Kanal clippt oben etwas mehr (0,2–0,6 % der Werte); Belichtung −0,5 gibt Reserve.
- Filmrand als Farbanker, jetzt gegen die echten Korrekturen getestet (Filmkonstante k_c auf (Rand/T)^g): nötige
  Balance streut R 0,19 / B 0,37 Blenden, gegen 0,16 / 0,14 mit kornarmen Perzentilen → klar schlechter, bestätigt 5.6.
  Rollenweise Anker nicht prüfbar (10 Scans aus 10 Rollen).

---

## 6. Wie Laborscanner umwandeln

### 6.1 Fuji Frontier
Quellen: US6160634, US6081343, EP0612183, Mutza ICIS 2006, SP-3000-Handbuch; Vergleich Nikon US5978106/US7359092,
HP US6204940.
- Trennung von **Gradation balance** (D_R und D_B als geglättete Kurven über D_G, Raster 0,05 D) und **einer
  Tonwertkurve** für alle Kanäle.
- Die Balance-Kurve wird über viele Bilder derselben Filmsorte gelernt (nur Pixel nahe am laufenden Mittel;
  Filmsorte aus Barcode), gewichtet gemischt mit Einzelbildanalyse und einer Standardisierung ohne hochgesättigte
  Pixel.
- Anker: einmal aus dem Dreifarbmittel (oder 5 %/95 %), R und B daraus über die Balance-Kurve, **nicht** je Kanal.
- Image Intelligence (Szenenanalyse, Gesichter, Hypertone, 3D-LUT) erklärt, warum Laborscans keine Referenz sind.
- Der Bediener wählt keine Filmsorte (Eingangstyp + Kanal; DX nur für Sonderfilme).
- Nikon: 0,03-%-Perzentile, Gamma je Kanal so, dass die Lichtersteigungen gleich sind. HP: 5 %/95 %, inverse
  Sigmoid + Mittelton-Gamma je Kanal.

**Test am eigenen Material:**
1. Fuji-Anker (Grün + Filmgerade) sind ohne Pipette **schlechter** als Kanalperzentile (Kosten 1,73 gegen 0,92).
   Die Balance schwankt je Rolle um 0,10 (R) / 0,25 (B) Blenden; mit Pipette sind beide Modelle identisch.
2. Balance-Kurve über 7 Scans ist eine **Gerade** (±0,03 D, kein Fuß, keine Schulter je Kanal):
   `D_R = −0,218 + 0,940·D_G`, `D_B = 0,251 + 0,984·D_G` → gR 1,90–1,93, gB 1,84–1,86.
   → Preset **X5 balance 1,90 / 1,811 / 1,85**.
3. Prototyp `frontier_proto.py` (Filmgerade + Grey-World ohne bunte Pixel + ein Gamma): Vorschauen gleichmäßiger
   als X5 neutral (das bei 16-116/16-131/17-89 ins Grünliche kippt); Grauverschiebung je Bild −26..+27 %.
   Vollbild `19-57_23_frontier.tif` zum Vergleich.

### 6.2 Noritsu
Quellen: US7613339, US7272257, US7269282, US7466857/EP1411714, US5555073, Harman-Merkblatt Phoenix 200, LS-600.
- **Kein Filmmodell.** Aus dem Vorscan der Rolle: Dichtehistogramme, Rot und Blau per **Shift und Stretch** auf Grün
  gelegt (Überlappung maximal); `D' = (D + S)·M`. Der Stretch ist das Gamma-Verhältnis, aus dem Bild statt aus
  einer Tabelle. Der Filmträger wird aus dem Histogramm geschätzt, nicht am Rand gemessen.
- Danach Fremdlicht-Erkennung (Kanaldichte gegen Mitteldichte, 45°-Linie), Auto-Kontrast, Chroma. Überläufe werden
  farbtonerhaltend skaliert.
- DX-Datenbank: wählt einen Bediener-Kanal (Y/M/C/D, Kontrast, Chroma, Schärfe). Ob auch Steigungen je Kanal
  darin stehen, war nicht zu belegen (bei Fuji US5017014 ja).
- **Nachbau an unseren Scans:** Stretch R 0,99–1,02, B 0,92–1,06 → **gR 1,81 ± 0,02, gB 1,81 ± 0,07**. Shift
  R +0,23..+0,34 D, B −0,15..−0,29 D. Ein Noritsu würde alle Kanäle gleich (≈ 1,81) invertieren.

### 6.3 Laborbilder von 19-57 als Referenz?
Noritsu-TIFF (bedienerbalanciert) und „Sigma“-TIFF (unbalanciert): Absolutwerte unbrauchbar. Beton R/G / B/G in
Blenden: Datenblatt −0,11/−0,12, X5 fit −0,08/−0,54, X5 neutral +0,02/−0,59, Noritsu −0,31/+0,03.

---

## 7. Scanprogramme (2026-09-18)

| | Filmwissen | Anker | Kurve |
|---|---|---|---|
| BallastConverter (ColorNeg) | Gamma je Kanal aus Tabelle | Perzentil je Kanal | Gerade (Gamma) |
| FlexColor | Levels-Satz eines Referenznegativs | Endpunkte je Kanal, Auto | Mittelton je Kanal + Gamma 2 |
| VueScan | Kennlinien je Film (PhotoCD), optional | Filmsteg („Lock film base color“) oder Perzentil | log + Gamma, je Kanal einstellbar |
| SilverFast NegaFix | RGB-Kurven je Film und Scanner, editierbar | Perzentil je Kanal (Auto-Maske) | freie Kurve je Kanal |
| Epson Scan | keins | Auto-Belichtung je Kanal pro Bild | fest |
| Fuji Frontier | gelernte Balance-Kurve je Film | Dreifarbmittel + Balance | eine Tonwertkurve |
| Noritsu | keins | Histogramm-Shift je Rolle | Histogramm-Stretch je Kanal |
| OpenEnlarge | Farbstoffspektren (13 Filme) | Filmträger je Rolle + skalarer Dmax | ein Gamma für alle + 3×3 im Dichteraum |
| Korova (Knokke) | keins (Looks je Prozess) | je Rolle aus den Stegen, LED-Licht je Film | Gamma je Kanal + logistische Papierkurve, Crossover |
| Negative Lab Pro 3.1 | keins („Film“ = Magenta/Gelb-Offsets) | je Bild, 0,01 %/0,05 % auf 200-px-Vorschau, 2 px weich | Levels im Gamma-Raum + Auto-Gamma + Sigmoide; Balance = Kanal-Gamma (Grauwelt) |

- VueScan: `P = log10(I)^(2.2/G)`; Weißpunkt 1 %, Schwarzpunkt 0 %; Profile aus der PhotoCD-Datenbank, laut Hamrick
  für Farbnegative nur begrenzt brauchbar.
- SilverFast: Filmprofil = RGB-Gradationskurven mit Fuß und Schulter; „Expansion“ = Perzentil-Anker je Kanal; CCR =
  automatische Pipette. Herkunft der Kurven unbekannt.
- Epson: kein Filmwissen, Auto-Belichtung pro Bild (deshalb Sprünge von Bild zu Bild); Rohmodus Gamma 1,8.
- Kein Programm belegt, woher seine Filmkurven stammen, und keines hat eine Antwort auf den scannerabhängigen
  Blau-Crossover.
- **Preset-Zahlen für Portra 400** sind außer bei ColorPerfect nicht zu bekommen (VueScan einkompiliert, NegaFix nur
  mit Installation, PhotoCD-Film-Terms nie veröffentlicht; deren Struktur: mittlere Dichten je Kanal plus
  Steigungskorrekturen für Unter-/Überbelichtung, US5311251).

### OpenEnlarge (Rust/Tauri, MIT)
- `d_c = log10(base_c / scan_c)`, Träger **einmal je Rolle** (automatisch aus dem Steg); eine Kurve für alle Kanäle
  (Gamma 1,59, Knie 0,89, kalibriert an einem 100-Feld-Graukeil vom Monitor auf Fuji C400); Balance als Gain oder
  „subtraktiv“ als Dichte-Maßstab; 3×3-Matrix im Dichteraum aus Farbstoffspektren.
- Ihre Befunde: **Weißanker je Kanal entsättigt dominante Farben** (blauer Briefkasten wurde grau) → Umstieg auf
  skalaren Dmax + Trägeranker. Ein auf einem Bild abgestimmtes Power-Law machte die ganze Bibliothek zu dunkel.
- Übernehmen: Träger-Anker je Rolle, Graukeil vom Monitor als Target. Nicht übernehmen: ein Gamma für alle. Die
  Dye-Spektren (dye_portra400.csv) nützen ohne die Kanalempfindlichkeiten des X5 nichts.

### Korova 1.10 (Soke Engineering, Knokke-Scanner; 2026-09-23, `recherche/Korova.md`)
- Aus dem Binary (GLSL-Shader im Klartext, Hilfetexte): kein Filmmodell, keine Matrix. Simulierter Vergrößerer:
  RGB-LED-Beleuchtung wird **je Filmsorte** so gelöst, dass der Träger neutral aussteuert (Orangemaske analog weg),
  Flat-Field durch den klaren Träger, **Anker je Rolle** aus den Stegen (Autolevels, auch ein Crossover je Kanal),
  dann im Log-Raum: Levels je Kanal → Kopplung (Entsättigung) → Crossover-Parabel (an beiden Ankern null) →
  CMY-Filterverschiebung (Grau-Klick, dichteneutral) → `print_d = 4·sigmoid(4·γ_c·contrast·(n−1))` → 10^−D → Gamma 2,2.
  Dichter als der Weißanker läuft in die Schulter der Sigmoide statt zu clippen. Die README im Paket beschreibt
  eine ACES-ADX-Pipeline, die im Binary nicht existiert.
- Übernehmenswert: **weiche Schulter oberhalb des Weißankers** (betrifft die offene Frage der obersten Blende und
  das Clipping der Auto-Balance), Anker je Rolle (bestätigt), Crossover als Werkzeug, dichteneutrale Balance.
- **Geprüft (2026-09-23, Auswertung Abschnitt 12):** die weiche Schulter macht die hellsten Neutralen +0,1 … +0,2
  Blenden blau (voller Balance-Faktor bis Weiß), Abstand zu Lightroom in den obersten Blenden 0,10 → 0,12–0,18:
  verworfen. Besser ist Lightrooms eigene Form, die Balance in den obersten zwei Blenden auslaufen zu lassen
  (voll bis −2 Blenden, 40 % bei Weiß): Abstand 0,100 → 0,055, Mitten unverändert, Clipping 0,97 → 0,83 %. Einwand des
  Nutzers: die Lightroom-Fassungen sind in den Lichtern keine beurteilte Wahrheit (nur Temp/Tint gesetzt). Deshalb
  **Sichtvergleich** an sechs Bildern (reiner Faktor / Schulter / Auslaufen): **der reine Faktor ist am besten**
  (Nutzer, 2026-09-23). Schulter und Auslaufen nicht eingebaut; die Frage der obersten Blende ist damit entschieden.

### Negative Lab Pro 3.1.1 (Lightroom-Plugin; 2026-09-24, `recherche/NegativeLabPro.md`)
- Aus dem dekompilierten Plugin (Lua) und den mitgelieferten DCP-Profilen: **kein Filmmodell**, keine Matrix; die
  „Film“-Auswahl sind je zwei feste Zahlen (Magenta/Gelb). Ablauf je Bild: Lightroom exportiert eine 200-px-
  Vorschau (Kameraprofil „Negative Lab v2.3“), ImageMagick schneidet 5 % Rand weg, zeichnet 2 px weich;
  **Anker je Kanal** bei 0,01 % (Weiß) und 0,05 % (Schwarz) – praktisch Minimum/Maximum des verschmierten Bilds;
  dazwischen eine **Gerade im gammakodierten Raum** (Levels, 3–9 Stützstellen), dann Auto-Gamma (Histogramm-
  mittel auf 0,5, geklemmt 0,8…1,1), tanh-Sigmoide (Stärke 3), kleine Schwarz/Weiß-Füße, Invertierung, Ausgabe
  als Lightroom-Tonwertkurven je Kanal. **Auto-Weißabgleich immer an:** Grauwelt über Pixel mit Sättigung < 30 %,
  ausgeführt als **Gamma je Kanal für Grün und Blau, Rot fest** (Null an beiden Ankern). Farbarbeit steckt in
  der für alle Kameras gleichen Look-Tabelle des DCP (Sättigung ×0,92, Rot-Orange ×0,54–0,71 und +5–8 % Helligkeit)
  und in nicht lesbaren Lab-LUTs (Frontier/Crystal/Pakon). TIFF-Scans: Gamma-Hilfsprogramm mit **Flextight 1,8**
  → Weißanker je Kanal → Gamma 2,2 (passt zu unserem ≈ 1,75).
- Übernehmen: nichts. Die Anker-Methode bestätigt unsere „low-grain“-Perzentile; die Balance als Kanal-Gamma
  ist „Levels = Filmgamma“ von der anderen Seite, unsere Bildpaare zeigen aber einen Faktor (Sichtvergleich
  2026-09-23); Auto-Helligkeit und Haut-Entsättigung kann Lightroom selbst.

---

## 8. Unabhängige Messung: negicc (IT8 auf Film)

github.com/arufahc/negicc (GPL): reflektives IT8 (coloraid R190808) bei Sonnenlicht auf Portra 400 / 160 /
Ektar 100, 0 / +1 / +2 / −1 Blenden, abfotografiert mit Sony A7RM4 durch Dreibandfilter. Steigungen aus gs0–gs23:

| Portra 400 | R | G | B | R/G | B/G |
|---|---|---|---|---|---|
| Belichtung 0 | 0,452 | 0,580 | 0,595 | 0,78 | 1,03 |
| +1 | 0,445 | 0,568 | 0,574 | 0,78 | 1,01 |
| +2 | 0,457 | 0,567 | 0,580 | 0,81 | 1,02 |
| −1 | 0,457 | 0,568 | 0,586 | 0,80 | 1,03 |
| Datenblatt (Status M) | 0,544 | 0,552 | 0,637 | 0,99 | 1,15 |
| X5 Balance-Gerade | | | | 0,94 | 0,98 |

- **Blau steigt parallel zu Grün** (1,01–1,03), nicht 15 % steiler. Der Blau-Crossover ist also eine Eigenschaft
  jedes RGB-Abtasters gegenüber Status M. Portra 160: 1,06–1,10; Ektar: 0,89–1,08.
- Grün 0,57–0,58 → Gamma 1,72–1,76; unser 1,811 ist plausibel.
- Rot hängt am stärksten vom Rotfilter ab (R/G 0,78–0,81 negicc, 0,94 X5, 0,99 Datenblatt).

---

## 9. Programmzustand

- `ballastconverter.py` (CLI/Bibliothek), `ballastconverter_gui.py` (tkinter, sv_ttk, dunkel, Karten Files /
  Profiles / Film / Conversion, englische Oberfläche), Einstellungen in `~/.ballastconverter.json`.
- GitHub: MIT, Autor „Ballast“; Windows-Build per GitHub Actions (PyInstaller onedir-ZIP wegen Defender-Fehlalarm).
  `recherche/`, `TODO.md`, Scans und Bilder sind gitignored.
- Live-Vorschau (einmal laden, 1600 px, LUT je Kanal), Convert erst nach dem grünen Statistikrahmen.
- Standard: Perzentile 0,1 %, Belichtung 0, Ausgabe 16 Bit mit TRC von AdobeRGB1998.icc, Profil eingebettet.
- Option „Low-grain anchors“ (Checkbox / `--grain`, seit 2026-09-23 Standard an, `--no-grain`): Anker aus
  5×5-Blockmitteln, siehe 5.8.
- Option „Auto colour balance“ (Checkbox / `--no-auto-balance`, Standard an, Namenszusatz `ab`, 2026-09-23): nach
  den Ankern wird die nahe-neutrale Pixelbevölkerung der Statistik-Region im Mittel neutral gestellt (Minilab-Art,
  Fuji-Verfahren 3), Rot und Blau je höchstens 0,75 Blenden, Grün bleibt; Verschiebung im Log und in der
  TIFF-Beschreibung. Aus = bitidentisch. Siehe 5.8.
- Ausgabename `<scan>_<film>_toe_ev-05_w01_b05.tif`; Einstellungen auch in der TIFF-ImageDescription.
- Bewusst entfernt: Film-Gamma-Faktor, CC-Felder, 8 Bit, Schwarzpunkt-Checkbox, Abbrechen, Theme-Umschalter.
- Rezept des ersten Ergebnisses (reproduziert `18-29_16_positiv_portra400.tif` bitidentisch):

      python3 ballastconverter.py 18-29_16.fff OUT.tif --film "Kodak/Portra 400 [4056] [5056] [6056]" \
        --in-curve "icc:Flextight X5 & 949.icc" --black 0.5 --p-black 0.005 --p-bpoint 0.005 \
        --out-curve 2.2 --stats-crop 700 500 7200 10600

  `--stats-crop` begrenzt nur die Perzentile (sonst landet der Schwarzpunkt in den Perforationslöchern).

---

## 10. Gesicherte Erkenntnisse, Verworfenes, Offenes

**Gesichert**
- Modell und Filmtabelle von ColorNeg; Plugin-Gammas = Kehrwert der Status-M-Steigung.
- 3F = Geräteraum des Profils (≈ Gamma 1,75), Export A bitidentisch, FlexColor benutzt die A2B0-LUT.
- Blau-Gamma ≈ Grün-Gamma (1,85–1,95) für RGB-Abtaster; Ursache RGB gegen Status M.
- Ein Gamma je Kanal reicht für die Balance (Gerade ±0,03 D).
- Eigene und fremde 3F sind gleich kodiert; kein Offset.
- Eigener X5: 2×2-Schachbrett → nie mit geradem Schritt unterabtasten.
- Der konstante Gelb-Grün-Stich ist ein Faktor (Anker), kein Gamma; etwa zur Hälfte Filmkorn im Blau-Weißanker (5.8).
- Gammas von „X5 neutral“ (1,70/1,811/1,95) durch Bildpaare bestätigt (nur Temp/Tint nötig, kein helligkeitsabhängiger Stich in den Mitten).

**Verworfen**
- „3F ist linear“ / „Gamma 2,2 bzw. 1,8 je Plattform“ / „nur Rot ist gammakodiert“.
- Additiver Offset (Streulicht/Elektronik) in der Linearisierung.
- Höhere Perzentile oder Clipping-Trick gegen den Stich.
- Filmkonstante Anker (Fuji-Art) und Balance am Filmträger: schlechter als Kanalperzentile.
- Ein Gamma für alle Kanäle (OpenEnlarge).
- Laborscans (Noritsu, Frontier) als Farbreferenz; Preset-Zahlen anderer Programme.
- Auto-Pipette im Konverter (Entscheidung des Nutzers: Pipette in Lightroom).

**Offen**
1. Auto colour balance: oberste Blende per Sichtvergleich entschieden (reiner Faktor). Offen: einfarbige Motive prüfen, sobald welche vorkommen; Rückmeldung an den eigenen lg5+ab-Konvertierungen. Fuß/Schulter-Option weiter am Vollbild beurteilen (Rot-Frage durch 5.8 erledigt: 1,70).
2. Filmträger bzw. Filmrand **je Rolle** als Anker (TODO 3; VueScan/OpenEnlarge-Art), ggf. Noritsu-Trägerschätzung aus
   dem Histogramm, wenn kein Rand mitgescannt ist.
3. Wahre Eingangskurve des X5 messen: Stufenkeil/IT8 als 3F, oder Graukeil vom kalibrierten Monitor auf Film
   (TODO 4). Entscheidet TRC gegen LUT und damit das Rot-Gamma.
4. Bildpaare (Scan + eigene fertige Korrektur) als einzige echte Bestätigung der Gammas; klärt auch die Frage der
   dunklen „Neutral“-Flächen.
5. Ursache des Schachbretts (Scan ohne Schärfung/Nachbearbeitung prüfen).
6. Gray-Semantik der FlexColor-Setups (nur interessehalber).
7. Spektrale Überlappung Farbstoffe/Scannerfilter (3×3-Matrix) bleibt unmodelliert; ohne Target nicht messbar.

---

## 11. Wo was steht

| Datei | Inhalt |
|---|---|
| `recherche/ColorNeg_Umwandlung.md` | Reverse Engineering, Formeln, Adressen |
| `recherche/filmgammas.txt` | alle 310 Film-Gammas des Plugins |
| `recherche/Portra400_Datenblatt.md`, `portra400_kennlinien.txt` | Datenblatt E-4050, Kennlinien |
| `recherche/3f_Analyse.md` | 3F-Format, FlexColor-Gamma/Midtone, Export-A/B-Test |
| `recherche/FlexColor_Portra_Setup.md` | NC/VC-Setups |
| `recherche/gammafit/Auswertung.md` (+ Skripte, `*.txt`, Kontaktbögen, `kandidaten/`) | Gamma-Fit, Linearisierungen, Neutralflächen, Stich |
| `recherche/bildpaare/Auswertung.md` (+ Skripte) | Bildpaare Konverter → Lightroom, Korn im Weißanker |
| `recherche/alternativscans/Auswertung.md` | Labor-3F, Offset, Noritsu/Sigma, Schachbrett |
| `recherche/Frontier_Umwandlung.md`, `recherche/frontier/` | Fuji-Patente, Tests, Prototyp |
| `recherche/Noritsu_Umwandlung.md`, `recherche/noritsu/` | Noritsu-Patente, Nachbau |
| `recherche/Scanprogramme_Umwandlung.md` | VueScan, SilverFast, Epson |
| `recherche/Filmpresets_Portra400.md`, `recherche/negicc/` | Presets anderer Programme, negicc-Messung |
| `recherche/OpenEnlarge.md` | OpenEnlarge |
| `recherche/Korova.md`, `recherche/NegativeLabPro.md` | Korova, Negative Lab Pro (dekompiliert in `~/.cache/cp_re/nlp/`) |
| `TODO.md` | Checkliste |
| `~/.cache/cp_re` | Ghidra, dekompilierter Plugin-Code |
