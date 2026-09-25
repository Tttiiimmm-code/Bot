# Forschungsprotokoll

Festgelegt VOR dem jeweiligen Test. Einträge werden nie nachträglich geändert,
nur ergänzt.

## 2026-09-24 -- Grundregeln

- Entwicklungszeitraum 2016-01-04 bis 2025-09-19, Holdout ab 2025-09-22 gesperrt.
- Kosten: 1 bp pro Seite + SEC-Gebühr, keine Hebelwirkung (max_exposure 1.0).
- Bestehen (Walk-Forward 504/126 Tage über das vorab definierte Grid):
  OOS-Rendite > 0, >= 60 % positive Fenster, >= 200 OOS-Handelstage,
  Profit-Faktor >= 1.2, Deflated Sharpe >= 0.95 (N = alle protokollierten Versuche).

## 2026-09-24 -- Ergebnisse Runde 1 (SPY, QQQ)

- noise_breakout (36 Versuche): OOS +57 % (6,2 % p.a.), Sharpe 0,86, 67 % positive
  Fenster, PF 1,27, Deflated Sharpe 0,78 -> NICHT BESTANDEN (nur DSR verfehlt).
  Auf QQQ alle 18 Varianten nach Kosten positiv (Sharpe 0,59-1,06), SPY schwächer.
- last_half_hour (16 Versuche): brutto ~0, nach Kosten durchgehend negativ -> verworfen.

## 2026-09-24 -- Vorab-Registrierung: Instrumenten-Bestätigung noise_breakout

Frage: Ist der Effekt ein allgemeines Intraday-Momentum auf liquiden ETFs oder ein
Zufallsfund auf QQQ?

- Variante fest = Paper-Default: band_mult 1.0, check_minutes 30, long + short,
  lookback 14, target_vol 0.02. KEINE Auswahl, keine weiteren Varianten.
- Neue Symbole (nie zuvor getestet): IWM, DIA, XLK, XLF, XLE, SMH.
- Gleiche Kosten und Zeitraum wie oben.
- Bestanden, wenn mindestens 4 von 6 Symbolen nach Kosten eine positive Sharpe haben
  UND das gleichgewichtete Portfolio der 6 eine Sharpe >= 0,5 hat.
- Bestanden -> Kandidat für Phase 4 (Holdout + Paper-Trading) als Portfolio
  QQQ/SPY + bestätigte ETFs. Nicht bestanden -> weiter mit Familien D/A.

## 2026-09-24 -- Ergebnis Instrumenten-Bestätigung noise_breakout

- IWM -0,58, DIA -0,69, XLK +0,69, XLF -0,62, XLE -0,37, SMH +0,76 (Sharpe nach Kosten).
- 2/6 positiv, Portfolio-Sharpe -0,11 -> NICHT BESTANDEN. Positiv nur Tech (XLK, SMH,
  wie QQQ). "Nur Tech" wäre eine nachträgliche Erklärung und wird NICHT als Strategie
  übernommen. noise_breakout verworfen.
- Kostensensitivität (Paper-Default, nicht als Versuch gezählt): QQQ Sharpe 1,56 / 1,30 /
  1,05 / 0,54 bei 0 / 0,5 / 1 / 2 bp; SPY 1,10 / 0,77 / 0,43 / -0,24. Vorteil je Trade nur
  3-6 bp brutto, Gewinne konzentriert auf volatile Jahre (2018, 2022).

## 2026-09-24 -- Vorab-Registrierung: Familie D, Gap-Fade auf ETFs

Hypothese: moderate Eröffnungslücken (ohne großen News-Anlass) schließen sich intraday
teilweise wieder.

- Symbole: SPY, QQQ, IWM, DIA, XLK, XLF, XLE, SMH.
- Lücke = Open / Vortagesschluss - 1. Trade nur bei min_gap <= |Lücke| <= 2 %.
- Einstieg zum Open des 9:31-Bars GEGEN die Lückenrichtung.
- Ziel: Vortagesschluss (Limit, gefüllt, wenn ein Bar ihn berührt).
  Stop: Lücke weitet sich um 1x |Lücke| vom Tages-Open aus (gefüllt zum Stop-Kurs bzw.
  zum Bar-Open, falls darüber hinaus eröffnet). Sonst Ausstieg zur Zeitgrenze.
  Ziel und Stop im selben Bar: Stop zählt (konservativ).
- Grid (8 Varianten je Symbol): min_gap {0,25 %, 0,5 %} x Zeitgrenze {12:00, 16:00}
  x {long+short, nur long}. Exposure 1.0.
- Bestehen: dieselben Grundregeln (Walk-Forward über alle 64 Symbol-Varianten).

## 2026-09-24 -- Ergebnis Familie D (Gap-Fade)

- 64 Symbol-Varianten, fast alle negativ (einzig XLE leicht positiv). Walk-Forward OOS
  -24 %, Sharpe -0,59, Deflated Sharpe 0,00 -> NICHT BESTANDEN, verworfen.
  Insgesamt protokollierte Versuche: 122.

## 2026-09-24 -- Vorab-Registrierung: Familie A, ORB auf "Stocks in Play"

Quelle: Zarattini & Aziz (2023), "Can Day Trading Really Be Profitable? Evidence of
Sustainable Long-term Profits from Opening Range Breakout (ORB) Day Trading Strategy".

Universum je Tag (nur Informationen bis zum Entscheidungszeitpunkt):
- alle US-Aktien bei Alpaca inkl. inaktiver/delisteter Symbole (Rest-Survivorship-Bias
  dokumentieren), ohne Symbole mit "." oder "/".
- Tages-Open > 5 $, Ø-Volumen der 14 Vortage > 1 Mio. Stück, ATR(14, Vortage) > 0,50 $.
- Relatives Volumen = Volumen der ersten 5 Minuten / Ø Volumen der ersten 5 Minuten der
  14 Vortage (mind. 10 Vortage vorhanden). Nur RelVol >= 1,0; davon die Top 20.

Handel:
- Opening Range = erste `or_minutes` Minuten. Close > Open -> nur long, Close < Open ->
  nur short, sonst kein Trade.
- Einstieg per Stop-Order am OR-Hoch (long) / OR-Tief (short) nach Ende der OR, gefüllt
  zum Stop-Kurs bzw. zum schlechteren Bar-Open bei Kurslücke.
- Stop = Einstieg -/+ 10 % der ATR(14). Ausstieg per Stop oder zum Handelsschluss.
- Positionsgröße: Risiko 1 % des Kapitals je Trade, gedeckelt auf max_exposure / 20
  je Position (live umsetzbar, Kapital für alle 20 Kandidaten reserviert).

Kosten (Aktien mit weiteren Spreads als ETFs, Stop-Order-Einstieg):
- 1 bp + 0,01 $ je Aktie und Seite + SEC-Gebühr.

Grid (4 Varianten): or_minutes {5, 15} x {long+short, nur long}.
Auswertung für max_exposure 1.0 (Cash-Konto) und 4.0 (wie im Paper), Hauptkriterium 1.0.
Bestehen: dieselben Grundregeln; Walk-Forward über die 4 Varianten.

## 2026-09-25 -- Ergebnis Familie A (ORB, Minuten-Bars, konservative Füllung)

- Alle 8 Läufe deutlich negativ (max_exposure 1.0: Sharpe -3,0 bis -5,3), 85-88 % der
  Trades ausgestoppt. Walk-Forward OOS -58 %, 0 % positive Fenster -> NICHT BESTANDEN.
  Insgesamt protokollierte Versuche: 130.
- Diagnose (nicht als Versuch gezählt): Stop-Abstand im Mittel nur ~0,5 % vom Kurs, 45 %
  der Trades werden laut Minuten-Bar schon im Einstiegs-Bar ausgestoppt. Dort ist die
  Reihenfolge Einstieg/Stop unbekannt; die Simulation nimmt den schlechtesten Fall an.
  Schranke long-only (2018/2021/2024, netto je Trade): konservativ -11/-20/-15 bp,
  optimistisch (Stop im Einstiegs-Bar nur bei Bar-Schluss jenseits des Stops)
  +4/+16/+14 bp. Das Ergebnis hängt also vollständig an der Füllsimulation.

## 2026-09-25 -- Vorab-Registrierung: ORB mit Tick-genauer Füllung im Einstiegs-Bar

Methodenkorrektur, keine neue Strategie: Einstieg und Stop würden live als Broker-Orders
(Stop-Einstieg + Stop-Loss) Tick für Tick gefüllt.

- Nur für Trades, deren Einstiegs-Minute laut Bar auch den Stop berührt: Alpaca-SIP-Trades
  (Ticks) dieser Minute laden. Einstieg = Preis des ersten Ticks jenseits des OR-Levels;
  Stop = Preis des ersten späteren Ticks derselben Minute auf/jenseits des Stops. Kein
  solcher Tick -> Position läuft ab der nächsten Minute normal mit Minuten-Bars weiter.
- Alles andere unverändert (Universum, 4 Varianten, Kosten 1 bp + 0,01 $/Aktie/Seite,
  Positionsdeckel, Kriterien, Walk-Forward). Hauptkriterium max_exposure 1.0.
- Die Läufe zählen als 8 NEUE Versuche (N steigt auf 138).

## 2026-09-25 -- Fehler im ersten Tick-Lauf (Ergebnis ungültig)

- Erster Lauf mit Ticks war ungültig: Ticks sind Rohkurse, die Minuten-Bars split-bereinigt.
  In 11,5 % der mehrdeutigen Minuten lag ein späterer Split dazwischen (Beispiel: Tick 600 $
  vs. Bar 15 $), die Simulation "kaufte" dann zum Rohkurs. Folge: -100 %, Ø -65 bp je Trade.
- Korrektur: Ticks je Minute mit Faktor (Bar-Open + Bar-Close) / (erster + letzter Tick)
  auf das Bar-Niveau skaliert, wenn der Faktor mehr als 5 % von 1 abweicht. Test ergänzt.
- Plausibilitätsprüfung 2021 long-only, brutto je Trade: konservativ -11,7 bp,
  optimistisch +25,1 bp, mit Ticks +14,0 bp (liegt dazwischen). Echte Stops in der
  Einstiegs-Minute: 20 % statt 45 %.
- Die ungültigen Läufe haben dieselben Versuchs-Schlüssel wie der korrigierte Lauf und
  werden in trials.csv durch ihn ersetzt (N bleibt 138).

## 2026-09-25 -- Ergebnis Familie A mit Tick-genauer Füllung (korrigiert)

- max_exposure 1.0: or5_both Sharpe -0,01, or5_long -0,03, or15_both -1,02, or15_long -0,42.
  Vorteil vor Kosten ~ so groß wie die Kosten (~9 bp je Trade) -> netto etwa null.
  Positiv nur 2021/2022, sonst überwiegend negativ.
- Walk-Forward OOS -24 %, Sharpe -0,60, 33 % positive Fenster -> NICHT BESTANDEN.

## 2026-09-25 -- Zwischenfazit nach allen vorab geplanten Familien

Keine der vier Familien (B Noise-Breakout, C Letzte halbe Stunde, D Gap-Fade, A ORB auf
Stocks in Play) besteht die Kriterien. 138 protokollierte Versuche. Holdout (ab
2025-09-22) wurde NICHT geöffnet und steht für einen künftigen Kandidaten weiter zur
Verfügung.
