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

# Runde 2: Haltedauer über Nacht bis wenige Tage (2026-09-25)

Auf Wunsch des Nutzers nach Runde 1 (keine Day-Trading-Strategie bestanden). Keine Day
Trades mehr -> PDT-Regel greift nicht.

## Zusätzliche Grundregel für Runde 2

Long-Strategien sind schon durch die Aktienmarkt-Prämie "profitabel". Zusätzlich zu den
Grundregeln aus Runde 1 (Walk-Forward, >= 60 % positive Fenster, PF >= 1,2 auf Tagesbasis,
Deflated Sharpe >= 0,95 mit N = alle Versuche beider Runden) muss gelten:
- Alpha gegenüber SPY (Regression der OOS-Tagesrenditen auf SPY-Tagesrenditen) > 0 mit
  t-Wert >= 2.
Ausführung, Kosten und Holdout (ab 2025-09-22 gesperrt) wie in Runde 1. Signale nutzen nur
Daten bis zum Ausführungszeitpunkt.

## Vorab-Registrierung: Familie E, Overnight-Effekt auf ETFs

Quelle: Cooper, Cliff & Gulen (2008); Lou, Polk & Skouras (2019): ein Großteil der
Aktienrendite entsteht über Nacht.
- Kauf zum Schlusskurs (Close des 15:59-Bars, Market-on-Close), Verkauf zum Open des
  nächsten Handelstags. Symbole: SPY, QQQ, IWM, DIA, XLK, XLF, XLE, SMH.
- Varianten: {immer, nur wenn Kurs um 15:50 > SMA200 der Vortages-Schlüsse}.
- 16 Versuche. Kosten 1 bp je Seite + SEC-Gebühr. Hinweis: braucht ein Margin-Konto
  (im Cash-Konto wäre der tägliche Wiederkauf mit unabgewickeltem Geld eine
  Good-Faith-Violation), aber keine Day Trades.

## Vorab-Registrierung: Familie F, RSI(2)-Mean-Reversion auf ETFs

Quelle: Connors & Alvarez (2008), "Short Term Trading Strategies That Work".
- Signal um 15:50: RSI(2) aus den Vortages-Schlüssen plus dem 15:50-Kurs; Einstieg zum
  Schlusskurs desselben Tages, nur wenn 15:50-Kurs > SMA200 der Vortages-Schlüsse.
- Ausstieg zum Schlusskurs des Tages, an dem der 15:50-Kurs das Ausstiegskriterium erfüllt.
- Varianten: Einstieg RSI(2) < {5, 10} x Ausstieg {15:50-Kurs > SMA5, RSI(2) > 70}.
- Symbole wie Familie E -> 32 Versuche. Volle Position (Exposure 1.0) je Symbol-Lauf.

## Vorab-Registrierung: Familie G, Wochen-Umkehr bei liquiden Aktien

Quelle: Lehmann (1990), Jegadeesh (1990); Umkehr kurzfristiger Verlierer.
- Universum je Stichtag (point-in-time): Top 500 nach Ø-Dollar-Volumen der 20 Vortage,
  Kurs > 5 $, aus dem Stocks-in-Play-Tagespanel (inkl. delisteter Symbole).
- Alle 5 Handelstage zum Schluss: Rendite der letzten L Tage; die n schwächsten Aktien
  gleichgewichtet zum nächsten Open kaufen, 5 Handelstage halten, Verkauf zum Open.
- Varianten: n {10, 25} x L {5, 10} -> 4 Versuche.
- Kosten 1 bp + 0,01 $ je Aktie und Seite + SEC-Gebühr. Fehlen Kurse während der Haltedauer
  (Delisting), Ausstieg zum letzten verfügbaren Schluss (Bias dokumentieren).

## 2026-09-25 -- Ergebnisse Runde 2

- E Overnight (16 Versuche): ALLE 16 Varianten einzeln nach Kosten positiv (Sharpe 0,17-1,35,
  mit Trendfilter meist besser). Walk-Forward (wählt je Fenster EIN ETF) jagt SMH und
  bricht 2022 ein: OOS -2,6 %, Sharpe 0,08, Alpha -5,0 % p.a. (t -0,80) -> NICHT BESTANDEN.
- F RSI(2) (32 Versuche): meist positiv, aber nur 30-70 Trades je ETF in 9 Jahren.
  Walk-Forward OOS -22 % (Corona-Crash -33 % in einem Fenster), Alpha -6,9 % p.a.
  (t -1,57) -> NICHT BESTANDEN.
- G Wochen-Umkehr (4 Versuche): Sharpe 0,2-0,3, MaxDD bis -68 %, Walk-Forward OOS -8 %,
  Alpha -7,0 % p.a. (t -0,51), Beta 1,17 -> NICHT BESTANDEN.
- Insgesamt protokollierte Versuche: 190. Holdout weiterhin ungeöffnet.

## 2026-09-25 -- Vorab-Registrierung: E-Portfolio (nachträglich motiviert!)

Motiviert durch das Ergebnis von E (alle 16 Einzelvarianten positiv) -- also datengetrieben
und entsprechend mit Vorsicht zu behandeln. Deshalb: EINE feste Variante, keine Auswahl,
strenge Kriterien, und der Holdout entscheidet am Ende.

- Overnight mit Trendfilter (15:50-Kurs > SMA200) auf allen 8 ETFs gleichzeitig, je 1/8
  des Kapitals (ETFs ohne Signal: Anteil bleibt Cash). Kosten wie E.
- Zählt als 1 neuer Versuch (N = 191).
- Bestehen im Entwicklungszeitraum (ohne Walk-Forward, da keine Parameterwahl):
  Deflated Sharpe >= 0,95 mit N = 191, Alpha ggü. SPY > 0 mit t >= 2, PF (Tage) >= 1,2,
  >= 60 % positive Halbjahre.
- Nur wenn bestanden: Holdout (ab 2025-09-22) EINMAL öffnen. Bestanden dort, wenn Rendite
  > 0 und Alpha > 0. Erst dann Paper-Trading.

## 2026-09-25 -- Ergebnis E-Portfolio

- Entwicklungszeitraum: +94 % (7,75 % p.a.), Sharpe 1,00, MaxDD -13,6 %, PF 1,21,
  Alpha ggü. SPY 5,3 % p.a. (t 2,23), Beta 0,17, 63 % positive Halbjahre.
- Deflated Sharpe 0,000 (N = 191) -> NICHT BESTANDEN. Geprüft, ob das ein Artefakt der
  stark negativen ORB-Versuche ist: auch ohne ORB liegt die Schwelle (erwartete maximale
  Sharpe unter N Zufallsversuchen) bei 1,54 p.a. Eine Sharpe von 1,0 ist nach 191
  Versuchen kein belastbarer Nachweis.
- Holdout NICHT geöffnet.

## 2026-09-25 -- Fazit nach Runde 2

191 protokollierte Versuche in 7 Familien plus einem Folgetest, keiner besteht. Bestes
Ergebnis: Overnight-Portfolio mit Trendfilter (Alpha t = 2,23), statistisch aber nicht von
Glück zu unterscheiden. Jede weitere Suche auf denselben Daten erhöht N und damit die Hürde.

# Runde 3: Krypto (2026-09-25)

Auf Wunsch des Nutzers (nicht an US-Aktien gebunden). Neuer, unabhängiger Datensatz. Nur
Spot, nur long (kein Leerverkauf, kein Hebel), Haltedauer Tage bis Wochen (Börsengebühren
schließen kurzfristigen Handel aus).

## Daten und Universum

- Binance-Spot, USDT-Paare, Tages-Kerzen (UTC), öffentliche Daten: REST (data-api.binance.vision)
  für aktive, Monatsarchive (data.binance.vision) für delistete Paare.
- Universum je Tag (point-in-time): Top 20 nach Ø-Quote-Volumen (USDT) der 30 Vortage, ohne
  Stablecoins, Fiat-Paare, gehebelte Tokens (UP/DOWN/BULL/BEAR) und Wrapped-Tokens. Mindestens
  60 Tage Historie.
- Entwicklungszeitraum bis 2025-09-21, Holdout ab 2025-09-22 gesperrt (wie Runde 1/2).

## Ausführung, Kosten, Kriterien

- Signal zum Tagesschluss (00:00 UTC), Ausführung zum selben Kurs (24/7-Markt, Schluss = Open
  des Folgetags). Kosten 0,25 % je Seite (Taker-Gebühr einer EU-Börse inkl. Slippage) auf den
  Umschlag. Zusätzlich berichtet: 0,10 % (Binance-Niveau) -- nicht entscheidend.
- Annualisierung mit 365 Tagen.
- Walk-Forward: Training 730, Test 182 Kalendertage.
- Bestehen: OOS-Rendite > 0, >= 60 % positive Fenster, PF (Tage) >= 1,2, Deflated Sharpe
  >= 0,95 mit N = ALLE protokollierten Versuche aller Runden (konservativ), Alpha gegenüber
  BTC-Buy-and-Hold > 0 mit t >= 2.

## Vorab-Registrierung: Familie H, Trendfolge auf BTC und ETH

Quelle: u.a. Liu & Tsyvinski (2021), "Risks and Returns of Cryptocurrency" (Zeitreihen-Momentum).
- Voll investiert, solange der Schlusskurs über dem SMA(n) liegt, sonst Cash (USDT).
- Varianten: n {20, 50, 100} x Asset {BTC, ETH} -> 6 Versuche.

## Vorab-Registrierung: Familie I, Querschnitts-Momentum im Top-20-Universum

Quelle: Liu, Tsyvinski & Wu (2022), "Common Risk Factors in Cryptocurrency".
- Wöchentlich (alle 7 Tage) die k Coins mit der höchsten Rendite der letzten L Tage kaufen,
  gleichgewichtet, bis zur nächsten Umschichtung halten.
- Varianten: L {7, 28} x k {3, 5} x Filter {keiner, nur investiert wenn BTC > SMA50} -> 8
  Versuche.

## 2026-09-25 -- Ergebnisse Runde 3 (Krypto)

- Daten: 658 handelbare USDT-Paare, davon 136 delistet (z.B. LUNA-Crash, FTM, WAVES) -- die
  REST-Schnittstelle liefert auch delistete Historie. Filterlücke vor der Auswertung behoben:
  BULL/BEAR (gehebelte BTC-Tokens 2019/20) und USDSB (Stablecoin) waren anfangs enthalten.
- H Trendfolge BTC/ETH (6 Versuche): einzeln Sharpe 0,89-1,30, geringerer MaxDD als Halten
  (-65 % statt -83 %). Walk-Forward OOS +819 %, BTC halten im selben Zeitraum +966 %.
  Alpha 22 % p.a. (t 1,39), 58 % positive Fenster, DSR 0,000 -> NICHT BESTANDEN.
- I Querschnitts-Momentum Top 20 (8 Versuche): ohne BTC-Filter MaxDD bis -99 %. Walk-Forward
  OOS +198 %, fast vollständig aus H1 2021 (+495 %), danach überwiegend negativ; BTC halten
  +1.359 %. Alpha t 0,42 -> NICHT BESTANDEN.
- Insgesamt protokollierte Versuche: 205. Holdout weiterhin ungeöffnet.

## 2026-09-25 -- Fazit nach drei Runden

Über US-Aktien (Intraday und Tage) und Krypto hinweg schlägt keine getestete Regel nach
Kosten verlässlich das bloße Halten des jeweiligen Markts. Die Trend-Regeln reduzieren
Drawdowns, liefern aber kein statistisch belastbares Alpha.

# Runde 4: Gold und Silber (2026-09-25)

Auf Wunsch des Nutzers ("weitersuchen, bis eine profitable Strategie gefunden ist"). Gleiche
Strenge: Vorab-Registrierung, alle Versuche zählen (N startet bei 205), Holdout entscheidet.

- Instrumente: GLD (Gold), SLV (Silber), Alpaca-SIP-Minutendaten 2016-01 bis 2025-09-19.
- Ausführung wie Runde 2: Signal um 15:50, Ausführung zum Schlusskurs (Market-on-Close),
  Verkauf beim Overnight-Handel zum nächsten Open. Kosten 1 bp je Seite + SEC-Gebühr.
- Benchmark: 50/50 GLD/SLV halten (täglich neu gewichtet). Bestehen wie Runde 2: Walk-Forward
  504/126, >= 60 % positive Fenster, PF (Tage) >= 1,2, Deflated Sharpe >= 0,95 (N = alle
  Versuche), Alpha ggü. Benchmark > 0 mit t >= 2.

## Vorab-Registrierung: Familie K, Overnight-Effekt bei Edelmetallen

Hypothese (u.a. Studien zu "gold returns occur outside US trading hours"): Gold/Silber steigen
vor allem während der Asien-/London-Sitzung, also zwischen US-Schluss und US-Open.
- Kauf zum Schluss, Verkauf zum nächsten Open; Varianten {immer, nur über SMA200} x {GLD, SLV}
  -> 4 Versuche.

## Vorab-Registrierung: Familie L, Trendfolge auf Edelmetallen

- Investiert (Schluss bis Schluss), solange der 15:50-Kurs über dem SMA(n) der Vortages-
  Schlüsse liegt. Varianten n {50, 100, 200} x {GLD, SLV} -> 6 Versuche.

## 2026-09-25 -- Ergebnisse Runde 4 (Gold/Silber)

- K Overnight (4 Versuche): GLD über Nacht 5,8 % p.a. vs. GLD halten 12,3 % p.a. -- die
  Hypothese "Gold steigt vor allem außerhalb der US-Handelszeit" bestätigt sich 2016-2025
  nicht. Walk-Forward OOS +67 %, Alpha 2,8 % p.a. (t 0,72), PF 1,14 -> NICHT BESTANDEN.
- L Trendfolge (6 Versuche): GLD Sharpe 0,57-0,75 (halten 0,89), SLV 0,16-0,36 (halten 0,49).
  Walk-Forward OOS +45 %, Alpha -0,7 % p.a. -> NICHT BESTANDEN.
- Insgesamt protokollierte Versuche: 215.

# Runde 5: Multi-Asset-Trendfolge mit ETFs (2026-09-25)

Begründung: Trendfolge auf EINEM Markt (Runden 3/4) senkt Drawdowns, schlägt das Halten aber
nicht. Die Literatur verortet den Vorteil in der Streuung über Anlageklassen (Moskowitz, Ooi
& Pedersen 2012; Faber 2007, "A Quantitative Approach to Tactical Asset Allocation";
Antonacci 2014, "Dual Momentum").

- Universum fest: SPY (US-Aktien), IWM (US-Nebenwerte), EFA (Industrieländer), EEM
  (Schwellenländer), TLT (lange US-Anleihen), IEF (mittlere US-Anleihen), GLD (Gold), DBC
  (Rohstoffe), VNQ (Immobilien). Alpaca-SIP 2016-2025.
- Umschichtung monatlich am letzten Handelstag: Signal um 15:50, Ausführung zum Schlusskurs.
  Kosten 1 bp je Seite + SEC-Gebühr auf den Umschlag. Nicht investierte Anteile: Cash (0 %).
- Benchmark: dieselben 9 ETFs gleichgewichtet halten (monatlich neu gewichtet).
- Bestehen wie Runde 2 (Walk-Forward 504/126, >= 60 % positive Fenster, PF (Tage) >= 1,2,
  Deflated Sharpe >= 0,95 mit N = alle Versuche, Alpha ggü. Benchmark > 0 mit t >= 2).

## Vorab-Registrierung: Familie M

- Signal s {Kurs > SMA200, 12-Monats-Rendite > 0, 6-Monats-Rendite > 0}
  x Gewichtung {absolut: jedes ETF mit positivem Signal 1/9; dual: die 3 ETFs mit der
  höchsten 12-Monats- bzw. 6-Monats-Rendite (beim SMA-Signal: höchste 12M-Rendite), sofern
  Signal positiv, je 1/3} -> 6 Versuche.

## 2026-09-25 -- Ergebnis Runde 5 (Multi-Asset-Trendfolge)

- Alle 6 Varianten Sharpe 0,55-0,74 bei MaxDD -11 bis -18 % (1/9 halten: Sharpe 0,54, MaxDD
  -23 %; SPY halten: Sharpe 0,75, 13,2 % p.a., MaxDD -34 %). "dual" 8 % p.a., "absolute" ~4 %
  p.a. bei ~58 % Investitionsgrad.
- Walk-Forward OOS +44 %, 77 % positive Fenster, PF 1,10, Alpha 2,9 % p.a. (t 0,79) ->
  NICHT BESTANDEN. Bestes Risikoprofil aller Runden, aber kein belastbares Alpha.
- Insgesamt protokollierte Versuche: 221.

# Runde 6: Prämien mit ökonomischer Ursache (2026-09-25)

Begründung: Alle bisher getesteten Preisregeln scheiterten. Diese Runde testet Effekte mit
struktureller Ursache: Monatswechsel (Zuflüsse von Gehältern/Pensionsfonds) und Funding-Prämie
(Nachfrage nach Hebel am Krypto-Terminmarkt).

## Vorab-Registrierung: Familie N, Monatswechsel-Effekt

Quelle: Lakonishok & Smidt (1988); McConnell & Xu (2008), "Equity Returns at the Turn of the
Month".
- Investiert nur an den Tagen des Fensters (Schluss-zu-Schluss-Renditen): die letzten w
  Handelstage des Monats und die ersten 3 des Folgemonats, sonst Cash. Kauf zum Schluss vor
  dem Fenster, Verkauf zum Schluss des 3. Handelstags (Market-on-Close, kalenderbasiert).
- Varianten: w {1, 2} x {SPY, QQQ, IWM} -> 6 Versuche. Kosten 1 bp je Seite + SEC-Gebühr.
- Benchmark: dasselbe ETF halten (Alpha-Test gegen das jeweilige ETF; beim Walk-Forward
  gegen SPY). Bestehen wie Runde 2.

## Vorab-Registrierung: Familie O, Funding-Carry (Krypto, marktneutral)

- Je Coin: 50 % des Kapitals Spot long, 50 % als Sicherheit für eine gleich große Short-
  Position im USDT-Perpetual (Binance). Tagesrendite auf das Gesamtkapital =
  0,5 x (Spot-Rendite - Perp-Rendite + Summe der Funding-Raten des Tages).
- Varianten: Coin {BTC, ETH} x {immer investiert, nur wenn Ø-Funding der letzten 7 Tage
  > 0 (tägliche Entscheidung zum Tagesschluss)} -> 4 Versuche.
- Kosten je Seite: Spot 0,10 %, Perp 0,05 % (Binance-Taker), jeweils auf den halben
  Kapitalanteil. Daten ab 2019-09 (Beginn der Funding-Historie), Holdout wie immer gesperrt.
- Benchmark für den Alpha-Test: BTC halten. Bestehen wie Runde 3 (Walk-Forward 730/182,
  365 Tage Annualisierung).
- Bekannte Risiken außerhalb des Backtests: Ausfall der Börse (vgl. FTX 2022), Liquidation
  der Short-Position bei extremen Kurssprüngen, eingeschränkter Zugang zu Perpetuals für
  Privatkunden in der EU (MiCA). Werden im Ergebnis ausdrücklich bewertet.

## 2026-09-25 -- Ergebnisse Runde 6

- N Monatswechsel (6 Versuche): SPY/QQQ Sharpe 0,31-0,55 bei 19-24 % Investitionsgrad, IWM
  -0,09 bis 0,21. Walk-Forward OOS +53 %, 67 % positive Fenster, PF 1,24, Alpha 3,2 % p.a.
  (t 0,95), DSR 0,000 -> NICHT BESTANDEN (4 von 6 Kriterien).
- O Funding-Carry (4 Versuche): Sharpe 6,5-8,1, CAGR 6,0-8,0 %, MaxDD ca. -1 %. Walk-Forward
  OOS +16,9 % (4,0 % p.a.), 100 % positive Fenster, PF 6,3, Alpha 3,9 % p.a. (t 23,0),
  Beta 0,00, DSR 1,000 (N = 231) -> ALLE KRITERIEN BESTANDEN.
- Plausibilitätsprüfung (keine Versuche): Perp/Spot-Basis Median -0,03 %, Tagesdifferenz der
  Renditen Std 0,06 %; Funding Ø 12,9 % (BTC) bzw. 15,7 % (ETH) p.a. auf die Nominale, an
  ~10 % der Tage negativ. Ertrag entsteht tatsächlich aus Funding, kein Simulationsfehler.
  Aber: Ertrag aufs Kapital je Jahr BTC 8,6 / 15,3 / 2,1 / 3,9 / 6,0 / 1,9 % (2020-2025),
  also seit 2022 in der Größenordnung risikoloser Geldmarktzinsen.

## 2026-09-25 -- Vorab-Registrierung: Holdout-Test Funding-Carry (einmalig)

- Kandidat nach der Walk-Forward-Regel: Variante mit der besten Sharpe in den letzten 730
  Tagen vor dem Holdout.
- Holdout: 2025-09-22 bis zum letzten verfügbaren Tag. Gleiche Kosten und Berechnung.
- Bestanden, wenn (1) Rendite > 0 und (2) annualisierte Rendite > 4 % p.a. (Näherung für
  risikolose USD-Geldmarktzinsen; darunter lohnt das zusätzliche Börsen-/Gegenparteirisiko
  nicht).
- Zusätzlich berichtet (nicht entscheidend): alle 4 Varianten im Holdout, doppelte Kosten.

## 2026-09-25 -- Ergebnis Holdout-Test Funding-Carry (Holdout damit verbraucht)

- Kandidat nach Regel: ETHUSDT, immer investiert (Sharpe letzte 730 Tage 15,3).
- Holdout 2025-09-22 bis 2026-09-25 (369 Tage): +1,21 % (1,20 % p.a.), Sharpe 5,2, MaxDD
  -0,31 %. Kriterium (1) Rendite > 0 erfüllt, Kriterium (2) > 4 % p.a. VERFEHLT
  -> NICHT BESTANDEN.
- Zur Information: BTC immer +1,76 % p.a.; gefilterte Varianten 0,7-0,9 % p.a., mit doppelten
  Kosten leicht negativ. ETH-Funding im Holdout nur noch Ø 2,5 % p.a. auf die Nominale
  (Entwicklungszeitraum 15,7 %), an 25 % der Tage negativ. Die Prämie ist weitgehend
  wegarbitriert (plausibel: Spot-ETFs, große Basis-Trade-Fonds wie Ethena).
- Der Holdout ist hiermit geöffnet. Künftige Kandidaten können nur noch mit neuen Daten
  (Vorwärtstest im Paper-Handel oder bisher ungenutzte Datenquellen) bestätigt werden.

# Runde 7: Historische Validierung 2003-2015 (2026-09-25)

Nutzer lehnt kostenpflichtige Daten ab. Der Holdout ist verbraucht. Neue, unberührte Daten
gibt es kostenlos nur in der VERGANGENHEIT: Yahoo-Finance-Tagesdaten vor 2016 wurden in keinem
bisherigen Test verwendet. Die drei Kandidaten, die in den Runden 2, 5 und 6 den Kriterien am
nächsten kamen, werden dort genau EINMAL mit ihrer auf 2016-2025 festgelegten Variante
geprüft (keine neue Parameterwahl).

- Daten: Yahoo Finance, Tageswerte (Open, Close, Dividenden, dividendenbereinigter Close),
  jeweils ab Auflage des jüngsten benötigten ETFs, bis 2015-12-31.
- Abweichungen von der ursprünglichen Ausführung (mangels Minutendaten): Signal auf dem
  Schlusskurs statt 15:50-Kurs; Overnight-Rendite = (Open + Dividende am Ex-Tag) / Vortages-
  schluss - 1; sonst Renditen aus dem dividendenbereinigten Schlusskurs. Kosten wie bisher.
- Kandidaten und Benchmark:
  1. E-Portfolio (Overnight, Trendfilter SMA200, 8 ETFs je 1/8), Benchmark SPY halten.
  2. Multi-Asset-Trendfolge "dual, m12" (vom Walk-Forward zuletzt gewählt), Benchmark 1/9 halten.
  3. Monatswechsel SPY, last_days 2 (vom Walk-Forward zuletzt gewählt), Benchmark SPY halten.
- Bestanden, wenn im Validierungszeitraum: Rendite > 0, Sharpe > Sharpe der Benchmark, Alpha ggü.
  Benchmark > 0 mit t >= 2,4 (Bonferroni-Korrektur für 3 Tests).
- Wer besteht, wird als Paper-Bot vorwärts getestet (neue Daten ab heute).

## 2026-09-25 -- Ergebnisse Runde 7 (historische Validierung, Yahoo bis 2015)

- E-Portfolio Overnight (2001-03 bis 2015): 3,70 % p.a., Sharpe 0,65, MaxDD -12,3 % (SPY
  halten 6,15 % p.a., Sharpe 0,40, MaxDD -55,2 %). Alpha 3,07 % p.a. (t 2,13), Beta 0,09
  -> NICHT BESTANDEN (t knapp unter 2,4).
- Multi-Asset dual m12 (2007-03 bis 2015): 7,78 % p.a., Sharpe 0,57 (1/9 halten 0,39),
  Alpha 5,72 % p.a. (t 1,28) -> NICHT BESTANDEN.
- Monatswechsel SPY (1993 bis 2015): 4,24 % p.a., Sharpe 0,50 (SPY 0,55), Alpha 2,16 %
  (t 1,29) -> NICHT BESTANDEN.
- Einordnung (nachträglich, keine Entscheidungsgrundlage): Das E-Portfolio zeigt in zwei
  unabhängigen Zeiträumen ein positives Alpha mit t > 2 (2016-2025: t 2,23; 2001-2015: t 2,13)
  bei sehr kleinem Beta und kleinen Drawdowns. Einziger Kandidat mit wiederholtem Signal ->
  Vorwärtstest als Paper-Bot (overnight-run) ist der angemessene nächste Schritt.

# Runde 8: Weitere bekannte Anomalien (2026-09-25)

Nutzer: "alle Strategien ausprobieren". Holdout verbraucht -> neue Bestehensregel mit zwei
unabhängigen Zeiträumen, wo Daten vorhanden:

- Familien mit ETF-Daten vor 2016 (P, Q, R): Variante mit dem höchsten Alpha-t-Wert in
  2016-2025 (Alpaca) wählen; bestanden nur, wenn dieselbe Variante in 2016-2025 UND im
  Zeitraum vor 2016 (Yahoo) je ein Alpha > 0 mit t >= 2 gegenüber der Benchmark hat.
- Familien nur mit Daten ab 2016 (S, T, Aktien-Querschnitt inkl. delisteter Titel): Walk-
  Forward und alle Kriterien aus Runde 2 inkl. Deflated Sharpe mit N = alle Versuche.
- Kosten: ETFs 1 bp je Seite + SEC-Gebühr; Einzelaktien 3 bp je Seite (1 bp + ~1 Cent/Aktie).
- Signal zum Schlusskurs, Umschichtung zum Schlusskurs; Kosten auf den Umschlag.

## Vorab-Registrierung

- P Volatilitätsgesteuertes SPY (Moreira & Muir 2017, "Volatility-Managed Portfolios"):
  Gewicht = min(cap, 15 % / annualisierte Vola der letzten 21 Tage), täglich.
  cap {1,0; 1,5} -> 2 Versuche. Benchmark SPY.
- Q Halloween-Effekt (Bouman & Jacobsen 2002, "Sell in May"): SPY November-April, sonst Cash.
  1 Versuch. Benchmark SPY.
- R Sektor-Momentum (Moskowitz & Grinblatt 1999): 9 SPDR-Sektoren (XLB, XLE, XLF, XLI, XLK,
  XLP, XLU, XLV, XLY), monatlich die 3 mit höchster 6- bzw. 12-Monats-Rendite (nur bei
  positiver Rendite), je 1/3. 2 Versuche. Benchmark: 9 Sektoren gleichgewichtet.
- S Aktien-Momentum 12-1 (Jegadeesh & Titman 1993): Top-500-Universum nach Liquidität
  (point-in-time), monatlich die n Aktien mit höchster Rendite von t-252 bis t-21, gleich-
  gewichtet. n {50, 100} -> 2 Versuche. Benchmark SPY.
- T Niedrige Volatilität (Baker, Bradley & Wurgler 2011): gleiches Universum, monatlich die n
  Aktien mit der niedrigsten Tagesvola der letzten 63 Tage. n {50, 100} -> 2 Versuche.
  Benchmark SPY.
- Ergänzung vor der Auswertung: P, Q, R nutzen für BEIDE Zeiträume Yahoo-Schlusskurse inkl.
  Dividenden (Alpaca-Schlusskurse enthalten keine Dividenden, das würde Strategien mit
  Cash-Anteil begünstigen). Zeiträume: vor 2016 ab Auflage bzw. Warm-up, und 2016-01-01 bis
  2025-09-19. Hebel über 1 (P, cap 1,5) kostet 6 % p.a. Finanzierungszins auf den geliehenen
  Anteil; Cash verzinst sich mit 0 % (konservativ).
- Klarstellung vor der Auswertung (S, T): Das Liquiditäts-Universum enthält auch ETFs/ETNs
  (u.a. gehebelte wie TQQQ, SOXL). Diese werden über den Namen ausgeschlossen (ETF, ETN,
  Fund, Trust, iShares, SPDR, ProShares, Direxion, Invesco, Vanguard, VanEck, Ultra, 2X/3X,
  Bull/Bear, Index), damit nur Einzelaktien bleiben. SPY dient nur als Benchmark.

## 2026-09-25 -- Ergebnisse Runde 8

- P Vola-gesteuert: cap 1,0 Alpha t 1,33 (vor 2016) / 1,70 (2016-2025), cap 1,5 0,83 / 1,36.
  In beiden Zeiträumen positiv, aber nicht signifikant -> NICHT BESTANDEN.
- Q Halloween: t 1,34 vor 2016, -0,93 seit 2016 -> NICHT BESTANDEN.
- R Sektor-Momentum: m6 t 1,18 / -0,16, m12 0,67 / 0,51 -> NICHT BESTANDEN.
- S Aktien-Momentum: n=50 25,6 % p.a., Sharpe 0,85, MaxDD -46 %; Walk-Forward OOS 26,9 % p.a.,
  Alpha 11,1 % p.a. (t 1,16), Beta 1,24, PF 1,17 -> NICHT BESTANDEN.
- T Niedrige Vola: Sharpe 0,62-0,64, Walk-Forward Alpha 0,8 % p.a. (t 0,26) -> NICHT BESTANDEN.
- Insgesamt protokollierte Versuche: 240.

# Runde 9: Notenbank-Termine, Volatilitätsprämie, Paarhandel (2026-09-26)

Bestehensregeln wie Runde 8 (V, W: zwei unabhängige Zeiträume mit Alpha-t >= 2 für die in
2016-2025 beste Variante; U: nur Daten ab 2016 -> Walk-Forward + alle Kriterien inkl. DSR).

## Vorab-Registrierung

- V Pre-FOMC-Drift (Lucca & Moench 2015, "The Pre-FOMC Announcement Drift"): SPY nur von
  Schluss des Vortags bis Schluss des Tages einer planmäßigen FOMC-Zinsentscheidung, sonst
  Cash. Termine von federalreserve.gov (nur planmäßige Sitzungen, Entscheidungstag = letzter
  Sitzungstag). 1 Versuch. Zeiträume 1994-2015 und 2016-2025 (Yahoo inkl. Dividenden).
  Benchmark SPY.
- W Volatilitätsprämie (Short-Vola): SVXY halten, solange VIX < VIX3M (Contango) zum Schluss,
  sonst Cash. Varianten {nur Contango, Contango und VIX < 20} -> 2 Versuche. Zeiträume
  2011-10 bis 2015 und 2016-2025. Benchmark SPY. Hinweis: SVXY wurde im Februar 2018 von -1x
  auf -0,5x VIX-Futures umgestellt; die Daten zeigen das echte Produkt.
- U Paarhandel (Gatev, Goetzmann & Rouwenhorst 2006): Top-500-Einzelaktien, Bildung über 252
  Tage, die 20 Paare mit der kleinsten Summe quadrierter Abstände der normierten Kurse; Handel
  in den folgenden 126 Tagen: Spread > k Standardabweichungen -> teures Papier short, billiges
  long (je 1/20 des Kapitals pro Seite), Schließen bei Kreuzung. k {2} -> 1 Versuch, Kosten
  3 bp je Seite. Short-Leihgebühren nicht modelliert (zugunsten der Strategie, vermerkt).

## 2026-09-26 -- Ergebnisse Runde 9

- FOMC-Termine: 272 planmäßige Entscheidungstage 1994-2027 (federalreserve.gov); Parser um
  die Formate "Jan/Feb 31-1" und doppelte Leerzeichen ergänzt, bevor ausgewertet wurde.
- V Pre-FOMC: vor 2016 2,45 % p.a. bei 6 % Investitionsgrad, Alpha 2,15 % (t 2,95); 2016-2025
  0,44 % p.a., Alpha 0,03 % (t 0,03) -> NICHT BESTANDEN. Effekt nach Veröffentlichung (2015)
  verschwunden.
- W Short-Vola: Contango 40,7 % / 28,1 % p.a., MaxDD -44 % / -41 %, Alpha t -0,20 / 1,42;
  mit VIX<20 schlechter -> NICHT BESTANDEN.
- U Paarhandel: 0,85 % p.a., Sharpe 0,22, Walk-Forward Alpha 0,36 % p.a. (t 0,20)
  -> NICHT BESTANDEN.
- Insgesamt protokollierte Versuche: 244.

# Runde 10: Systematischer Scan (2026-09-26)

Nutzer: "jede mögliche Konfiguration auf jeder Art von Asset". Bei tausenden Tests erscheinen
~5 % zufällig signifikant. Deshalb zweistufig mit Korrektur für ALLE Tests:

- Assets (Yahoo, Tagesdaten inkl. Dividenden): ETFs SPY, QQQ, IWM, DIA, EFA, EEM, TLT, IEF, LQD,
  HYG, TIP, GLD, SLV, DBC, USO, UNG, VNQ, SMH und die 9 SPDR-Sektoren; Devisen EURUSD, GBPUSD,
  USDJPY, AUDUSD, USDCHF, USDCAD, NZDUSD (Kassakurs, ohne Zinsdifferenz); Krypto (Binance)
  BTC, ETH, BNB, XRP, ADA, LTC, TRX, ETC.
- Regeln (Position zum Schluss t, gilt für t -> t+1; Varianten long/flat und long/short):
  SMA-Trend n {10, 20, 50, 100, 200}; SMA-Kreuzung {5/20, 10/50, 20/100, 50/200};
  Zeitreihen-Momentum L {20, 60, 120, 250}; Donchian-Ausbruch N {20, 55, 100} (Ausstieg N/2);
  RSI(2)-Rückkehr Einstieg < {10, 30}, RSI(14) < {30}; Bollinger-Rückkehr z {1,5; 2; 2,5};
  Wochentag {Mo..Fr} (nur long); ETFs zusätzlich Overnight (long) und Monatswechsel (long).
- Kosten je Seite: ETFs 1 bp, Devisen 1 bp, Krypto 10 bp.
- Kennzahl je Test: Alpha-t-Wert der Tagesrenditen gegenüber Halten des Assets.
- Stufe 1 (Entdeckung): ETFs/Devisen 2016-01-01 bis 2025-09-19, Krypto 2017-08 bis 2021-12.
  Benjamini-Hochberg über ALLE Tests, FDR 10 %, einseitig (Alpha > 0).
- Stufe 2 (Bestätigung, unabhängiger Zeitraum): ETFs/Devisen vor 2016, Krypto 2022-01 bis
  2026-09 (Holdout ist verbraucht). Bestanden nur mit Alpha > 0 und Bonferroni-korrigiertem
  einseitigem p < 5 % über die Zahl der Stufe-1-Überlebenden.
- Diese Runde zählt als ein eigener Test-Block; die Korrektur ist hier eingebaut (statt DSR).
- Ergänzung vor der Auswertung (Ausstieg der Rückkehr-Regeln): RSI-Regeln verlassen die
  Position, sobald der RSI 50 kreuzt (short: Einstieg bei RSI > 100 - Schwelle); Bollinger-
  Regeln, sobald der Kurs den SMA20 wieder erreicht. Monatswechsel = letzter + erste 3
  Handelstage. Krypto-Wochentage wie ETFs Mo-Fr.

## 2026-09-26 -- Ergebnis Runde 10 (systematischer Scan)

- 2.112 Tests (1.377 ETF, 392 Krypto, 343 Devisen), 49 Regeln je Asset (+ Overnight und
  Monatswechsel bei ETFs).
- Entdeckung: 56 Tests mit t > 2 -- bei reinem Zufall erwartet ~49. Benjamini-Hochberg
  (FDR 10 %): 0 Überlebende -> kein Test besteht.
- Beste Einzelergebnisse ohne Korrektur (t Entdeckung / t Bestätigung): ADA SMA 10/50 2,83 /
  1,29; BTC SMA50 2,68 / 1,31; SPY SMA 5/20 2,64 / -1,09; UNG RSI14 2,77 / 0,17. Alle
  schwächer oder mit umgekehrtem Vorzeichen im unabhängigen Zeitraum.
- Vollständige Tabelle: research/scan_results.csv.
- Hinweis zur Methode: long- und long/short-Varianten derselben Regel haben praktisch den
  gleichen Alpha-t-Wert (long/short = 2 x long - Halten), sind also keine unabhängigen Tests;
  die Korrektur ist dadurch eher zu streng als zu locker.

# Runde 11: SEC EDGAR -- Insiderkäufe und Earnings-Drift (2026-09-26)

Auf Wunsch des Nutzers, der aus Deutschland handelt. Daraus folgende Annahmen:
- Nur Käufe (Leerverkäufe von US-Aktien für Privatkunden deutscher Broker kaum möglich).
- Kosten 10 bp je Seite (Ordergebühr, EUR/USD-Umtausch, Spread an deutschen Handelsplätzen
  bzw. IBKR); Stresstest 25 bp je Seite (berichtet, nicht entscheidend).
- Steuern (25 % Abgeltungsteuer + Soli auf realisierte Gewinne) ändern nicht, ob ein Vorteil
  existiert, werden aber in der Bewertung berücksichtigt.

## Daten

- SEC "Insider Transactions Data Sets" (Formulare 3/4/5, quartalsweise, 2015Q4-2025Q3).
- 8-K-Meldungen mit Item 2.02 (Quartalsergebnisse) aus data.sec.gov/submissions, Zeitpunkt
  aus acceptanceDateTime (vor 9:30 ET -> Ereignistag = Meldetag, sonst nächster Handelstag).
- Kurse: Alpaca-Tagespanel inkl. delisteter Titel. Universum: Top 1000 nach Ø-Dollar-Volumen
  der 20 Vortage, Kurs > 5 $, ohne Fonds/ETFs (Namensfilter wie Runde 8).

## Bestehen (zwei unabhängige Zeiträume)

- Entdeckung 2016-01-01 bis 2020-12-31, Bestätigung 2021-01-01 bis 2025-09-19.
- Je Familie die Variante mit dem höchsten Alpha-t (ggü. SPY) in der Entdeckung wählen;
  bestanden nur, wenn diese Variante in der Entdeckung t >= 2,24 (Bonferroni über 4
  Varianten) UND in der Bestätigung t >= 2 hat.
- Portfolio: alle aktiven Positionen gleichgewichtet, täglich; ohne aktive Position Cash.

## Vorab-Registrierung

- X Insiderkäufe (Lakonishok & Lee 2001; Cohen, Malloy & Pomorski 2012): Käufe am offenen
  Markt (Code P) von Officers/Directors, Wert >= 25.000 $. Einstieg zum Schluss des
  Handelstags NACH dem Meldetag. Varianten {jeder Kauf, Cluster: >= 2 verschiedene Insider
  kaufen innerhalb von 30 Tagen (Ereignis = Meldung des zweiten)} x Haltedauer {21, 63}
  Handelstage -> 4 Versuche.
- Y Earnings-Drift (Bernard & Thomas 1989; Chan, Jegadeesh & Lakonishok 1996): Überrendite
  am Ergebnistag = Aktie minus SPY (Schluss vor dem Ereignistag bis Schluss des Ereignistags).
  Kauf, wenn Überrendite > Schwelle, zum Schluss des FOLGEtags. Varianten Schwelle {5 %, 10 %}
  x Haltedauer {20, 60} Handelstage -> 4 Versuche.

# Runde 12: Ideen aus r/algotrading (2026-09-26)

Quelle: Top-Beiträge mit Flair "Strategy" (per Browser gelesen). Regeln exakt wie gepostet,
keine eigene Parameterwahl. Bestehen wie Runde 8: Variante mit dem höchsten Alpha-t in
2016-2025 wählen, bestanden nur mit Alpha-t >= 2 in 2016-2025 UND vor 2016 (Yahoo inkl.
Dividenden, ab Auflage). Kosten 1 bp je Seite + SEC-Gebühr; Stresstest 10 bp (deutscher
Broker). Nur long. Benchmark: dasselbe ETF halten.

- Z1 IBS-/Band-Rückkehr ("A Mean Reversion Strategy with 2.11 Sharpe", "Found a simple mean
  reversion setup with 70% win rate"): Kauf zum Schluss, wenn Schluss < höchstes Hoch der
  letzten 10 Tage - 2,5 x Ø(Hoch - Tief) der letzten 25 Tage UND IBS = (Schluss - Tief) /
  (Hoch - Tief) < 0,3; Verkauf zum Schluss, sobald Schluss > Hoch des Vortags.
  Assets {SPY, QQQ} -> 2 Versuche.
- Z2 Larry Connors "Double 7" ("Backtest results for Larry Connors Double 7"): Kauf zum
  Schluss, wenn Schluss > SMA200 und Schluss = tiefster Schluss der letzten 7 Tage; Verkauf
  zum Schluss, wenn Schluss = höchster Schluss der letzten 7 Tage. {SPY, QQQ} -> 2 Versuche.
- Z3 Asset-übergreifender Vorlauf (Kommentar "cross-asset correlation ... international and
  thematic ETFs"): Ziel-ETF am Folgetag halten, wenn SPY am Tag t gestiegen ist, sonst Cash.
  Ziele {EFA, EEM, EWJ, EWG, EWU, FXI, EWZ} -> 7 Versuche.

## 2026-09-26 -- Ergebnisse Runde 12 (r/algotrading)

- Z1 IBS-Band: SPY t 3,68 (vor 2016) / -0,09 (2016-2025); QQQ 3,89 / 0,66 -> NICHT BESTANDEN.
- Z2 Double 7: SPY 3,05 / 0,52; QQQ 1,14 / 0,77 -> NICHT BESTANDEN.
  Beide Rückkehr-Regeln stark vor 2016, seither verschwunden (Bekanntheit seit ~2008/2013).
- Z3 SPY -> Länder-ETFs: in BEIDEN Zeiträumen signifikant NEGATIV (z.B. EEM t -3,40 / -2,53,
  EWJ -3,40 / -2,22, FXI -4,20 / -3,24) -> NICHT BESTANDEN. Passt zu Levy & Lieberman (2013):
  US-notierte Länder-ETFs überreagieren auf den US-Markt und korrigieren am Folgetag.
- Insgesamt protokollierte Versuche (inkl. Runde 11, siehe unten): siehe trials.csv.

## 2026-09-26 -- Vorab-Registrierung: Z3R, Umkehrung (NACHTRÄGLICH motiviert!)

Die Umkehrung von Z3 wurde erst nach Sicht der Daten beider Zeiträume erkannt; dort zählt sie
nicht als Beleg. Einziger noch ungesehener Zeitraum für diese ETFs: nach 2025-09-19.
- Regel: die 7 Länder-ETFs (EFA, EEM, EWJ, EWG, EWU, FXI, EWZ) gleichgewichtet am Folgetag
  halten, wenn SPY am Tag t GEFALLEN ist, sonst Cash. Kosten 1 bp je Seite.
- Test EINMALIG auf 2025-09-22 bis heute. Bestanden, wenn Alpha ggü. dem gleichgewichteten
  Halten der 7 ETFs > 0 mit t >= 2. Geringe Teststärke (ein Jahr) ausdrücklich vermerkt.
- Praktische Einschränkung: US-notierte ETFs sind für Privatanleger in der EU nicht kaufbar
  (PRIIPs); UCITS-Pendants handeln zu europäischen Zeiten, der Mechanismus ist dort ein anderer.

## 2026-09-26 -- Ergebnis Z3R (einmaliger Test auf 2025-09-22 bis 2026-09-21, 251 Tage)

- Z3R 19,1 % p.a., Sharpe 1,50; 7 ETFs halten 16,6 % p.a., Sharpe 1,02. Alpha 9,0 % p.a.,
  t 1,10, Beta 0,55 -> NICHT BESTANDEN (t < 2). Richtung und Größe (~9 % p.a.) stimmen mit
  den beiden früheren Zeiträumen überein; für Signifikanz reicht ein Jahr nicht.

## 2026-09-26 -- Ergebnisse Runde 11 (SEC EDGAR)

- Daten: 64.951 Insiderkäufe (Officer/Director, >= 25.000 $), 6.728 Symbole; 109.906
  Ergebnismeldungen (8-K Item 2.02) für 2.687 Symbole des Top-1000-Universums.
- X Insiderkäufe: alle 4 Varianten mit negativem Alpha ggü. SPY in beiden Zeiträumen (absolut
  6-15 % p.a., aber unter SPY; beste Variante "jeder Kauf 63T" t -0,39 / -0,65)
  -> NICHT BESTANDEN. Im liquiden Top-1000-Universum kein Insider-Vorteil nach Kosten.
- Y Earnings-Drift: Entdeckung 2016-2020 bis t 2,06 (AR>10 %, 60T: +11,2 % p.a.), Bestätigung
  2021-2025 durchgehend signifikant negativ (-11 bis -26 % p.a., t -2,1 bis -2,3)
  -> NICHT BESTANDEN. Der Effekt hat sich umgekehrt.
- Bekannte Einschränkung: Ticker->CIK teils über die aktuelle SEC-Liste (umbenannte Ticker
  können falsch zugeordnet sein); betrifft nur einen Teil der Symbole.

# Runde 13: Swing-Trading mit Einzelaktien, 2 Wochen bis 6 Monate (2026-09-26)

Auf Frage des Nutzers. Umsetzbar für ~20.000 EUR aus Deutschland: höchstens 20 gleichzeitige
Positionen (je 1/20 des Kapitals, freie Plätze = Cash), nur long, Kosten 10 bp je Seite,
Stresstest 25 bp. Universum: Top 1000 nach Liquidität, Kurs > 5 $, ohne Fonds/ETFs, inkl.
delisteter Titel. Signal und Ausführung zum Schlusskurs. Mehrere Signale am selben Tag:
Rangfolge nach 6-Monats-Rendite (stärkste zuerst).
Bestehen wie Runde 11: je Familie die Variante mit dem höchsten Alpha-t (ggü. SPY) in der
Entdeckung 2016-2020 wählen; bestanden nur mit t >= 2,24 dort UND t >= 2 in der Bestätigung
2021-2025.

## Vorab-Registrierung

- AA 52-Wochen-Hoch (George & Hwang 2004): monatlich die 20 Aktien mit dem höchsten Verhältnis
  Schluss / 252-Tage-Hoch (Schluss), gleichgewichtet bis zum nächsten Monatsende.
  Varianten {nur Aktien über SMA200, ohne Filter} -> 2 Versuche.
- AB Minervini-Trendvorlage mit Ausbruch: Schluss > SMA50 > SMA150 > SMA200, SMA200 höher als
  vor 21 Tagen, Schluss >= 1,25 x 252-Tage-Tief und >= 0,75 x 252-Tage-Hoch; Einstieg bei neuem
  20-Tage-Schlusshoch mit Volumen > 1,5 x Ø50. Ausstieg: Schluss 8 % unter Einstieg oder
  Haltedauer 126 Tage oder Varianten {Schluss < SMA50, Schluss < SMA20} -> 2 Versuche.
- AC Rücksetzer im Aufwärtstrend: Schluss > SMA200 und SMA50 > SMA200; Einstieg, wenn der
  Schluss erstmals unter SMA50 fällt (Vortag darüber). Ausstieg: neues 20-Tage-Schlusshoch,
  Schluss < SMA200 oder Haltedauer {20, 60} Tage -> 2 Versuche.

## 2026-09-26 -- Ergebnisse Runde 13 (Swing mit Einzelaktien)

- AA 52-Wochen-Hoch: 6,7-10,3 % p.a., Alpha t -0,39 bis 0,39 in beiden Zeiträumen
  -> NICHT BESTANDEN.
- AB Minervini: Ausstieg<SMA50 2016-2020 16,7 % p.a. (Alpha 10,2 %, t 1,19), 2021-2025
  -4,7 % p.a., MaxDD -51 % (t -1,33); Ausstieg<SMA20 ähnlich -> NICHT BESTANDEN.
- AC Rücksetzer: max 60T 2016-2020 25,0 % p.a. (t 1,26), 2021-2025 1,9 % p.a., MaxDD -49 %
  (t -0,86) -> NICHT BESTANDEN.
- Muster: Trend-/Ausbruchs-Swing lief 2016-2020 (starker Wachstums-Bullenmarkt) gut und brach
  2021-2025 (Bärenmarkt 2022, Rotationen) ein; kein stabiles Alpha.

# Runde 14: Strukturelle Prämien -- Devisen-Carry, Devisen-Momentum, Anleihe-Auktionen (2026-09-26)

Per Browser recherchiert: Quantpedia-Strategieliste und "Out-of-Sample Alphas Post
Publication" (2025, 177 Aktien-Anomalien: nach Veröffentlichung Alpha im Mittel ~0). Daher
Fokus auf Prämien mit struktureller Ursache außerhalb von Aktien-Anomalien.
Bestehen wie Runde 8: Variante mit höchstem Alpha-t (ggü. SPY) in 2016-2025 wählen; bestanden
nur mit t >= 2,24 (2 Varianten) bzw. 2,5 (4 Varianten, Bonferroni) dort UND t >= 2 vor 2016.

## Vorab-Registrierung

- AD Devisen-Carry (Quantpedia #0005; Lustig, Roussanov & Verdelhan 2011): 8 Währungen (USD,
  EUR, GBP, JPY, AUD, CHF, CAD, NZD). Monatlich nach 3-Monats-Zins (FRED IR3TIB01, Vormonat,
  um Veröffentlichungsverzug zu meiden) sortieren. Rendite je Währung ggü. USD = Kassakurs-
  änderung (Yahoo) + Zinsdifferenz (täglich anteilig). Varianten {Top 3 long / Bottom 3 short,
  Top 3 long gegen USD} -> 2 Versuche. Kosten: 2 bp je Seite bei Umschichtung + 1 % p.a.
  Finanzierungsaufschlag auf die Brutto-Nominale (typischer Broker-Swap-Aufschlag).
  Umsetzbar aus Deutschland über Devisen-CFDs/Spot mit Swap.
- AE Devisen-Momentum (Quantpedia #0008; Menkhoff et al. 2012): gleiche 8 Währungen,
  monatlich Top 3 long / Bottom 3 short nach Überschussrendite (inkl. Zins) der letzten L
  Monate, L {1, 3} -> 2 Versuche, Kosten wie AD.
- AF Anleihe-Auktionszyklus (Lou, Yan & Zhang 2013): Auktionen 5-, 7-, 10-Jahres-Notes inkl.
  Aufstockungen (TreasuryDirect). IEF bzw. TLT vom Schluss des Auktionstags an k Handelstage
  halten, sonst Cash. {IEF, TLT} x k {3, 5} -> 4 Versuche. Kosten 1 bp je Seite. Benchmark
  für den Alpha-Test: SPY (Regression enthält den Anleihe-Beta-Effekt nicht; zusätzlich wird
  Alpha ggü. dem Halten des jeweiligen ETFs berichtet).
- Zeiträume: vor 2016 ab Datenverfügbarkeit (FX ab 2004/2006, Auktionen ab 2004), 2016-01-01
  bis 2025-09-19.
- Korrektur vor der Auswertung (AF): entscheidend ist Alpha ggü. dem Halten des jeweiligen
  ETFs (IEF bzw. TLT), nicht ggü. SPY -- sonst würde die normale Anleiherendite als Vorteil
  gewertet. Strenger als ursprünglich formuliert.

## 2026-09-26 -- Ergebnisse Runde 14

- AD Devisen-Carry: long/short t -0,92 (vor 2016) / -1,24; long ggü. USD -0,18 / -1,44
  -> NICHT BESTANDEN (mit 1 % p.a. Swap-Aufschlag; Carry seit 2008 bei Nullzinsen tot).
- AE Devisen-Momentum: 1M -0,46 / -2,01; 3M -0,04 / -2,57 -> NICHT BESTANDEN (negativ).
- AF Auktionszyklus (703 Auktionen 5/7/10 Jahre inkl. Aufstockungen), Alpha ggü. Halten des ETFs:
  IEF 3T: vor 2016 +3,23 % p.a. (t 3,61), 2016-2025 +2,22 % p.a. (t 2,15);
  IEF 5T: 2,33 / 1,67; TLT 3T: 3,12 / 1,86; TLT 5T: 1,98 / 1,50.
  Gewählt IEF 3T: t 2,15 < 2,5 (Bonferroni über 4) -> NICHT BESTANDEN, aber alle 4 Varianten in
  beiden Zeiträumen positiv; stärkstes konsistentes Ergebnis der gesamten Suche.

## 2026-09-26 -- Vorab-Registrierung: AF-Bestätigung auf ungesehenem Jahr

- Regel unverändert: IEF 3 Handelstage nach jeder Auktion (5/7/10 Jahre inkl. Aufstockungen)
  halten, sonst Cash; 1 bp je Seite.
- Zeitraum 2025-09-22 bis heute (für diese Regel noch nie ausgewertet). EINMALIG.
- Bestanden, wenn Alpha ggü. IEF-Halten > 0 mit t >= 2. Geringe Teststärke (ein Jahr, ~35
  Auktionen) ausdrücklich vermerkt; positives Alpha ohne Signifikanz gilt als "konsistent,
  nicht bestätigt".

## 2026-09-26 -- Ergebnis AF-Bestätigung (2025-09-22 bis 2026-09-21, 251 Tage, 38 Auktionen)

- AF IEF 3T: -3,10 % p.a. (IEF halten -1,94 %), Alpha -2,41 % p.a., t -1,06 -> NICHT BESTANDEN.
  Im ungesehenen Jahr negativ; der Auktionseffekt ist damit nicht bestätigt.

# Runde 15: Eigenständige Recherche per Browser (2026-09-26)

Quellen: Quantocracy (Aggregator von Quant-Blogs). Gelesen u.a.:
- Quanter Lab, "The overnight gain is real, no trade keeps it" (2026): Overnight-Prämie real,
  aber reines Overnight-Halten verdient schon vor Kosten weniger als Halten; zwei NightShares-
  ETFs (2022) nach 14 Monaten geschlossen, beide hinter ihrem Index. Relevant für den
  Overnight-Paper-Bot: dessen "Alpha" stammt aus geringem Beta, nicht aus höherer Rendite.
- Aligrithm zu Avramov, Kaplanski & Subrahmanyam: Moving Average Distance (MA21/MA200),
  Alpha 9,05 % p.a. (t 3,02), vollständig auf der Long-Seite; Korrelation 0,58 mit Momentum.

## Vorab-Registrierung: AG Moving Average Distance

- Universum wie Runde 13 (Top 1000, Kurs > 5 $, ohne Fonds, inkl. delisteter Titel).
- Monatlich die Aktien mit dem höchsten MRAT = SMA21 / SMA200 kaufen, gleichgewichtet bis
  zum nächsten Monatsende. Varianten {Top 100 (~oberstes Dezil), Top 20 (Kontogröße)} -> 2.
- Nur long, Kosten 10 bp je Seite. Bestehen: Entdeckung 2016-2020 t >= 2,24, Bestätigung
  2021-2025 t >= 2, Alpha ggü. SPY.

## 2026-09-26 -- Ergebnis AG (Moving Average Distance)

- Top 100: 2016-2020 24,1 % p.a., Alpha 8,9 % (t 1,12); 2021-2025 5,8 % p.a., Alpha -6,3 %
  (t -0,58), MaxDD -44 %.
- Top 20: 2016-2020 30,4 % p.a. (t 1,14); 2021-2025 -17,7 % p.a., MaxDD -85 % (t -1,31)
  -> NICHT BESTANDEN. Gleiches Muster wie Runde 13: Momentum-/Trend-Aktienauswahl stark im
  Wachstums-Bullenmarkt 2016-2020, Einbruch ab 2021.

# Runde 16: Europäische Länderrotation, Airline-Feiertagseffekt (2026-09-26)

Bestehen wie Runde 8 (zwei unabhängige Zeiträume vor 2016 / 2016-2025, Yahoo inkl. Dividenden;
beste Variante in 2016-2025 mit t >= 2,24 bei 2 Varianten bzw. 2 bei 1 Variante, vor 2016 t >= 2).

- AH Europäische Länderrotation (Richards 1997; Asness, Moskowitz & Pedersen 2013): 10 Länder-
  ETFs EWG, EWQ, EWU, EWI, EWP, EWN, EWL, EWD, EWK, EWO (als Datenquelle; handelbar aus
  Deutschland über UCITS-Länder-ETFs). Monatlich die 3 mit der höchsten Rendite der letzten L
  Monate (nur bei positiver Rendite, sonst Cash-Anteil), je 1/3. L {6, 12} -> 2 Versuche.
  Kosten 10 bp je Seite. Benchmark: die 10 Länder gleichgewichtet.
- AI Airline-Aktien vor US-Feiertagen (Quantpedia 2026): DAL, LUV, ALK, UAL gleichgewichtet
  (Datenverfügbarkeit, Rest-Survivorship-Bias vermerkt) von Schluss 5 Handelstage vor bis
  Schluss des letzten Handelstags vor Neujahr, Memorial Day, 4. Juli, Labor Day, Thanksgiving
  und Weihnachten, sonst Cash. 1 Versuch. Kosten 10 bp je Seite. Benchmark: dieselben 4 Aktien
  gleichgewichtet halten.

## 2026-09-26 -- Ergebnisse Runde 16

- AH Länderrotation: 6M t 1,56 (vor 2016) / 0,01; 12M 0,77 / 0,05; MaxDD -42 bis -49 %
  -> NICHT BESTANDEN.
- AI Airlines vor Feiertagen (Feiertage selbst berechnet: Neujahr, Memorial Day, 4. Juli, Labor
  Day, Thanksgiving, Weihnachten): vor 2016 Alpha -2,96 % (t -1,28), 2016-2025 +5,77 % (t 1,79)
  -> NICHT BESTANDEN; nur im jüngeren (vermutlich Entdeckungs-)Zeitraum positiv.

# Runde 17: Fundamentaldaten aus SEC XBRL (2026-09-26)

Daten: data.sec.gov/api/xbrl/frames (alle Firmen je Kalenderquartal, us-gaap). Point-in-time
konservativ: Werte eines Quartals erst 3 Monate nach Quartalsende verwendbar (10-Q-Frist 40-45,
10-K 60-90 Tage). CIK -> Ticker über Insider-Daten und SEC-Tickerliste (Rest-Fehler vermerkt).
Universum, Kosten, Plätze-Logik und Bestehen wie Runde 13 (Entdeckung 2016-2020 t >= 2,24,
Bestätigung 2021-2025 t >= 2, Alpha ggü. SPY, nur long, 10 bp je Seite).

- AJ Bruttoprofitabilität (Novy-Marx 2013): GP/A = Bruttogewinn (letztes Quartal x 4) /
  Bilanzsumme. Monatlich die n Aktien mit der höchsten GP/A, gleichgewichtet. n {20, 100}.
- AK Vermögenswachstum (Cooper, Gulen & Schill 2008): Wachstum der Bilanzsumme ggü. Vorjahres-
  quartal. Monatlich die n Aktien mit dem NIEDRIGSTEN Wachstum. n {20, 100}.

## 2026-09-26 -- Ergebnisse Runde 17 (XBRL-Fundamentaldaten)

- Abdeckung im Universum: GP/A 44 % (viele Firmen melden keinen GrossProfit-Tag), Vermögens-
  wachstum 87 %.
- AJ GP/A: n=20 2016-2020 21,2 % p.a. (t 0,92), 2021-2025 1,6 % p.a. (t -1,51); n=100 0,77 /
  -1,26 -> NICHT BESTANDEN.
- AK niedriges Vermögenswachstum: n=20 0,38 / -1,77 (2021-2025 -6,9 % p.a., MaxDD -66 %);
  n=100 -0,52 / -0,65 -> NICHT BESTANDEN.
- Gleiches Muster wie Runden 13 und 15: gute Absolutrenditen 2016-2020 durch Beta > 1 im
  Bullenmarkt, kein eigenständiges Alpha, Einbruch 2021-2025.

## 2026-09-26 -- Gesichtet, nicht getestet

- "Good vs Bad COVOL in Crypto" (Pham et al., besprochen von Aligrithm): Schwellen der
  Hebel-Regel brauchen Rückschau, Kopfzahl (Sharpe 0,56 vs 0,40) aus einer Variante, die der
  eigenen Deutung des Papiers widerspricht; zudem GARCH-Schätzung über 25 Coins nötig.
  Kein Versuch gezählt.

# Runde 18: Value-Faktor aus SEC XBRL (2026-09-26)

Bewertungskennzahlen brauchen UNBEREINIGTE Kurse (XBRL-Werte sind nicht split-bereinigt; mit
split-bereinigten Kursen würden später gesplittete Aktien -- oft spätere Gewinner -- künstlich
billig wirken = versteckter Blick in die Zukunft). Daher separater Abruf der Tageskurse mit
Adjustment.RAW für alle Symbole, die je im Top-1000-Universum waren. Renditen weiter aus den
bereinigten Kursen. Point-in-time wie Runde 17 (Quartalswerte ab Quartalsende + 3 Monate).
Universum, Plätze, Kosten, Bestehen wie Runde 17.

- AL Gewinnrendite (Basu 1977; Fama & French 1992): E/P = verwässerter Gewinn je Aktie der
  letzten 4 Quartale / unbereinigter Schluss. Nur E/P > 0. Monatlich höchste E/P, n {20, 100}.
- AM Buchwert/Marktwert: Eigenkapital (StockholdersEquity) / (ausstehende Aktien laut
  Deckblatt, dei:EntityCommonStockSharesOutstanding x unbereinigter Schluss). Nur B/M > 0.
  Monatlich höchste B/M, n {20, 100}.
- 2026-09-26: Auswertung von Runde 18 pausiert -- Alpaca-Keys in bottest.env ungültig
  ("unauthorized"), unbereinigte Kurse noch nicht geladen. Noch KEINE Ergebnisse gesehen.

## 2026-09-26 -- Ergebnisse Runde 18 (Value)

- Unbereinigte Kurse (Alpaca RAW) für 2.795 Symbole; Abdeckung E/P 53 %, B/M 71 %.
- AL E/P: n=20 2016-2020 2,6 % p.a., MaxDD -72 %, Alpha -14,4 % (t -1,37); 2021-2025 10,1 %,
  Alpha -3,2 % (t -0,43). n=100 -1,13 / -0,41 -> NICHT BESTANDEN.
- AM B/M: n=20 -0,95 / -0,16 (2016-2020 MaxDD -78 %); n=100 -1,02 / -0,20 -> NICHT BESTANDEN.
- Spiegelbild von Momentum: Value schwach 2016-2020 ("verlorenes Jahrzehnt", Corona-Crash),
  besser 2021-2025, aber in keinem Zeitraum über SPY.

## Vorab-Registrierung: AN Value + Momentum kombiniert (Asness, Moskowitz & Pedersen 2013)

Hinweis: nach Sicht der Einzelergebnisse registriert, aber als in der Literatur vorgegebene
Standardkombination (keine eigene Parameterwahl).
- 50 % Kapital: Top 100 nach B/M (wie AM), 50 % Kapital: Top 100 nach 12-1-Momentum (wie
  Runde 8 S, Universum Top 1000), jeweils monatlich, gleichgewichtet. 1 Variante.
- Bestehen: Entdeckung 2016-2020 t >= 2, Bestätigung 2021-2025 t >= 2 (Alpha ggü. SPY).
- Ergebnis AN: 2016-2020 14,0 % p.a. (Alpha -2,5 %, t -0,52), 2021-2025 13,8 % p.a. (Alpha
  -0,5 %, t -0,08), Beta 1,22 -> NICHT BESTANDEN. Stabil über beide Zeiträume, aber nur
  Marktrendite mit etwas mehr Risiko.

# Runde 19: Saisonalität einzelner Aktien, niedriges Beta (2026-09-26)

Universum, Kosten (10 bp), nur long, Alpha ggü. SPY wie Runde 13.

- AO Saisonalität (Heston & Sadka 2008): am Monatsende für jede Aktie der Mittelwert ihrer
  Renditen im KOMMENDEN Kalendermonat aus den Vorjahren (höchstens 5, mindestens 3 Jahre).
  Die n Aktien mit dem höchsten Wert für einen Monat halten. n {20, 100}.
  Wegen des Datenbeginns 2016 abweichende Zeiträume: Entdeckung 2019-01 bis 2021-12,
  Bestätigung 2022-01 bis 2025-09-19. Bestehen: t >= 2,24 / t >= 2.
- AP Niedriges Beta, nur long (Frazzini & Pedersen 2014 ohne Hebel): Beta ggü. SPY aus den
  Tagesrenditen der letzten 252 Tage; monatlich die n Aktien mit dem NIEDRIGSTEN Beta.
  n {20, 100}. Entdeckung 2016-2020, Bestätigung 2021-2025, t >= 2,24 / t >= 2.

## 2026-09-26 -- Ergebnisse Runde 19

- AO Saisonalität: n=20 t 0,14 (2019-2021) / -0,21 (2022-2025); n=100 -0,68 / -0,28
  -> NICHT BESTANDEN.
- AP Niedriges Beta: n=20 t 0,36 / -2,05 (2021-2025 -16,1 % p.a., MaxDD -67 %); n=100 0,14 /
  -1,09 -> NICHT BESTANDEN. Prüfung der Auswahl: Mitte 2021 wählte das naive 252-Tage-Beta
  Meme-Aktien (AMC, GME, BNGO), deren chaotische Kurse kaum mit dem Markt korrelierten; danach
  defensive Werte (Clorox, General Mills, Hershey, Goldminen). Das robustere Beta des Originals
  (5-Jahres-Korrelation) ist mit Daten ab 2016 für die Entdeckung nicht berechenbar; die kaum
  betroffene Variante n=100 besteht ebenfalls nicht.

## 2026-09-26 -- Recherche r/quant (keine Versuche)

- "Does being a quant help you in personal trading?": meistbewertete Antworten (377, 181
  Punkte): Profis halten privat nur breite Indizes ("long only indices", "long SPX only"), weil
  ihr beruflicher Vorteil an Technik und Daten der Firma hängt.
- "List of free or affordable alternative datasets": Hinweise auf Stooq (lange Futures-/Index-
  Historien) und Dukascopy (Devisen/CFD-Ticks). Stooq-CSV per Automatisierung blockiert
  (JS-Prüfung, Download bricht ab); nur seitenweises Auslesen der HTML-Tabellen möglich.
  Dukascopy (Gold 24 h, z.B. für Asien-Range-Ausbruch) als nächster Kandidat notiert.

# Runde 20: Gold-Range-Ausbruch nach der Asien-Sitzung (2026-09-26)

Idee aus r/algotrading ("YouTube, René Balke, range breakout xauusd"); Daten: Dukascopy
XAUUSD-Minutenkerzen (Bid), 24 h, kostenlos (dukascopy-node).
- Range = Hoch/Tief von 00:00 bis 06:59 UTC. Ab 07:00 bis 19:59 UTC Stop-Einstieg: Kauf über
  dem Range-Hoch bzw. Verkauf unter dem Range-Tief; nur der erste ausgelöste Trade je Tag.
  Stop-Loss an der gegenüberliegenden Range-Grenze. Ausstieg: Variante {Ziel = 1 x Range-Höhe,
  kein Ziel} und spätestens 20:00 UTC. Wochenenden entfallen.
- Ausführung auf Minutenbasis: Einstieg zum Stop-Kurs bzw. schlechteren Minuten-Open; Stop und
  Ziel in derselben Minute -> Stop zählt (konservativ). Kosten 1 bp je Seite (Spread ~0,3 $ bei
  ~4.000 $ plus Ask-Aufschlag, da Bid-Daten). Long und short (aus Deutschland per Gold-CFD
  möglich); Positionsgröße: 1 x Kapital, kein Hebel.
- Zwei unabhängige Zeiträume: Entdeckung 2016-01-01 bis 2025-09-19, Bestätigung 2008-2015.
  Bestanden: beste Variante in der Entdeckung Alpha-t >= 2,24 (ggü. Gold halten), Bestätigung
  t >= 2.

## 2026-09-26 -- Ergebnis Runde 20 (Gold-Range-Ausbruch, Dukascopy)

- 7,45 Mio. Minutenkerzen 2008-01 bis 2025-09; 2.385 Trades (2016-2025), 1.938 (2008-2015).
- Ziel 1x Range: 2016-2025 -1,1 % p.a. (Alpha t -0,33), 2008-2015 +4,4 % (t 1,34).
- Ohne Ziel: 2016-2025 +2,2 % p.a. (t 0,95), 2008-2015 +8,9 % (t 1,87)
  -> NICHT BESTANDEN. Gold halten 2016-2025 deutlich besser (Sharpe 0,82).

# Runde 21: Monatsend-Fixing im Devisenmarkt (2026-09-26)

Quellen: Melvin & Prins (2015), "Equity hedging and exchange rates at the London 4 p.m. fix";
Evans, O'Neill, Rime & Saakvitne (2018), "Fixing the Fix?". Struktureller Fluss: Absicherungs-
Umschichtungen großer Investoren zum WM/Reuters-Fixing (16:00 London) am letzten Handelstag
des Monats; Kursbewegung vor dem Fixing, Umkehr danach.
Daten: Dukascopy-Minuten (Bid) EURUSD, GBPUSD, USDJPY 2008-2025. Uhrzeit 16:00 Europe/London
(Sommerzeit berücksichtigt). Ereignisse: letzter Werktag (Mo-Fr) jedes Monats.
- AQ Vor dem Fixing: USD long gegen die 3 Währungen gleichgewichtet von 14:00 bis 16:00 London.
- AR Nach dem Fixing (Umkehr): USD short von 16:00 bis 20:00 London.
  -> 2 Versuche (je eine feste Regel, Richtung laut Literatur: USD-Stärke vor dem Monatsend-
  Fixing, Umkehr danach).
- Kosten 0,5 bp je Seite und Währungspaar (Spread der Hauptpaare ~0,1-0,3 Pips, CFD aus
  Deutschland). Kennzahl: mittlere Rendite je Ereignis, t-Wert über die Ereignisse.
- Bestanden: t >= 2,24 (Bonferroni über 2) in 2016-2025 UND t >= 2 in 2008-2015, gleiches
  Vorzeichen.

## 2026-09-26 -- Ergebnis Runde 21 (Monatsend-Fixing, Dukascopy EURUSD/GBPUSD/USDJPY)

- AQ USD long 14-16 Uhr London: 2016-2025 Ø -4,94 bp je Monatsende (t -2,62, Vorzeichen
  ENTGEGEN der Vorab-Richtung), 2008-2015 +1,85 bp (t 0,75) -> NICHT BESTANDEN.
- AR USD short 16-20 Uhr (Umkehr): -3,48 bp (t -1,84) / -1,77 bp (t -1,02) -> NICHT BESTANDEN;
  keine Umkehr nach dem Fixing.
- Wirtschaftliche Größe ohnehin gering (~0,4-0,6 % p.a.). Die Umkehrung der Richtung wäre
  nachträglich und zählt nicht.

# Runde 22: London-Open-Ausbruch bei Devisen (2026-09-27)

Häufig empfohlene Forex-Strategie; gleiche Regeln wie Runde 20 (Range 00:00-06:59 UTC, Stop-
Einstieg 07:00-19:59 UTC, Stop an der Gegenseite, Ziel {1x Range, keins}, Ausstieg spätestens
20:00 UTC). Paare {EURUSD, GBPUSD} -> 4 Versuche. Kosten 0,5 bp je Seite. Benchmark: Halten
des Paares. Bestanden: beste Variante 2016-2025 t >= 2,5 (Bonferroni über 4) und 2008-2015
t >= 2.

## 2026-09-27 -- Ergebnis Runde 22 (London-Open-Ausbruch Devisen)

- EURUSD: Ziel 1x t -1,90 / -1,00; ohne Ziel -0,34 / -0,07.
- GBPUSD: Ziel 1x 1,04 / -2,59; ohne Ziel +4,1 % p.a. (t 2,09) 2016-2025, aber -6,6 % p.a.
  (t -2,81) 2008-2015 -> NICHT BESTANDEN. Vorzeichenwechsel zwischen den Zeiträumen.

# Runde 23: Faber-GTAA als reiner Nach-Veröffentlichungs-Test (2026-09-27)

Recherche: "The long-term efficiency of tactical asset allocation: Evidence from 86 strategies"
(2026): TAA über 30 Jahre risikobereinigt besser als 60/40, auf kurzen Horizonten instabil;
Concretum Group: Faber-GTAA knapp 20 Jahre nach Veröffentlichung robust.
- Regel exakt wie Faber (2007): 5 Anlageklassen (SPY, EFA, IEF, DBC, VNQ), je 1/5; am
  Monatsende investiert, wenn Schluss > 10-Monats-Durchschnitt der Monatsschlüsse, sonst Cash
  (hier 0 % Zins, konservativ). Yahoo inkl. Dividenden, Kosten 1 bp je Seite.
- Test: 2008-01 bis 2025-09 (komplett NACH der Veröffentlichung, 1 Versuch).
- Bestanden, wenn Sharpe > gleichgewichtetes Halten der 5 UND Alpha ggü. diesem Halten > 0
  mit t >= 2. Maximaler Verlust wird berichtet.
- Ergebnis Runde 23: GTAA 4,44 % p.a., Sharpe 0,58, MaxDD -15,5 %; 1/5 halten 5,77 %, 0,45,
  -45,7 %; SPY 10,99 %, 0,62, -52,3 %. Alpha 2,38 % p.a. (t 1,60), Beta 0,34 -> NICHT
  BESTANDEN. Bestätigt die Literatur: deutlich weniger Verlust, aber keine signifikante
  Überrendite; Rendite weit unter Aktien.

# Runde 24: Dual Momentum (Antonacci 2014) als Nach-Veröffentlichungs-Test (2026-09-27)

- Regel wie "Global Equities Momentum" (GEM): am Monatsende 12-Monats-Rendite von SPY mit der
  von Cash (hier: SHY) vergleichen; ist SPY besser, das stärkere von SPY und EFA halten (nach
  12-Monats-Rendite), sonst AGG (Anleihen). Yahoo inkl. Dividenden, 1 bp je Seite.
- Test: 2015-01 bis 2025-09 (nach Veröffentlichung, 1 Versuch). Bestanden, wenn Alpha ggü.
  SPY > 0 mit t >= 2.
- Ergebnis Runde 24: GEM 2015-2025 6,34 % p.a., Sharpe 0,46, MaxDD -33,7 %; SPY 13,51 %, 0,80,
  -33,7 %. Alpha -3,92 % p.a. (t -1,69), ~2 Wechsel/Jahr -> NICHT BESTANDEN. Nach der
  Veröffentlichung deutlich schlechter als SPY bei gleichem Maximalverlust.

# Ideen-Warteschlange aus Quantpedia (2026-09-27, per Suchmaschine gesammelt)

Noch nicht getestet und mit freien Daten prüfbar:
- Runde 25 (Kalender/ETF, Yahoo, zwei Zeiträume): Optionsverfall-Woche, Vor-Feiertag,
  Zahltag-Effekt, Januar-Effekt (Nebenwerte), Paired Switching (SPY/TLT), Rohöl sagt Aktien
  voraus, Umkehr bei internationalen Aktien-ETFs.
- Runde 26 (Aktien, Alpaca-Panel + SEC): Residual Momentum, Earnings-Announcement-Premium,
  Accrual-Anomalie, ROA-Effekt.
- Runde 27 (Krypto, Binance stündlich): Overnight-Saisonalität bei Bitcoin.
- Danach: Paarhandel mit Länder-ETFs, Momentum bei REITs, Länder-Saisonalität, FED-Modell
  (Shiller-Daten), Momentum-Varianten (konsistentes Momentum).
Bereits getestet (übersprungen): Value, PEAD, Asset Growth, Zeitreihen-Momentum, Monatswechsel,
Short-Term-Reversal, Momentum, Low Vol, Sektor-Momentum, FX-Carry/-Value, 12-Monats-Zyklus,
52-Wochen-Hoch, Momentum-Allokation, Asset-Class-Trend, Paarhandel Aktien, VIX-Laufzeit.

# Runde 25: Quantpedia-Kalender- und ETF-Strategien (2026-09-27)

Je Familie 1 feste Regel, Yahoo inkl. Dividenden, Kosten 1 bp je Seite + SEC-Gebühr. Bestehen
(Bonferroni über 7 Familien): Alpha-t >= 2,69 in 2016-2025 UND >= 2 vor 2016 (ab Datenbeginn).
- Q1 Optionsverfall-Woche: SPY nur Montag-Freitag der Woche mit dem 3. Freitag. Bench SPY.
- Q2 Vor-Feiertag: SPY nur am letzten Handelstag vor US-Börsenfeiertagen (Neujahr, MLK, Presidents,
  Karfreitag, Memorial, 4. Juli, Labor, Thanksgiving, Weihnachten; aus Handelskalender-Lücken
  abgeleitet: Tag vor einem Werktag ohne Handel). Bench SPY.
- Q3 Zahltag: SPY am letzten Handelstag vor dem 15. und am ersten ab dem 15. Bench SPY.
- Q4 Januar-Effekt: im Januar IWM statt SPY, sonst SPY. Bench SPY.
- Q5 Paired Switching: am Quartalsende das bessere von SPY/TLT (Quartalsrendite) für das nächste
  Quartal. Bench 50/50 SPY/TLT.
- Q6 Rohöl: am Monatsende SPY für den Folgemonat, wenn USO im abgelaufenen Monat gefallen ist,
  sonst Cash. Bench SPY.
- Q7 Umkehr Länder-ETFs: jeden Freitag die 3 schwächsten der letzten 5 Tage aus EWJ, EWG, EWU,
  EWQ, EWC, EWA, EWH, EWS, EWZ, EWW, EWY, EWT, eine Woche halten. Bench: alle 12 gleichgewichtet.

## 2026-09-27 -- Ergebnisse Runde 25 (Alpha-t vor 2016 / 2016-2025)

- Q1 Optionsverfall-Woche 0,57 / -1,40; Q2 Vor-Feiertag 0,27 / 1,12; Q3 Zahltag 0,51 / 1,26;
  Q4 Januar-Nebenwerte 0,67 / -1,01; Q5 Paired Switching 1,37 / -0,44; Q6 Rohöl -0,13 / 0,22;
  Q7 Umkehr Länder-ETFs 4,98 (Alpha 12,9 % p.a.) / -0,34 -> alle NICHT BESTANDEN.
  Q7: stark bis 2015, danach verschwunden (gleiches Muster wie IBS/Double 7).

# Runde 26: Quantpedia-Aktienanomalien (2026-09-27)

Universum Top 1000 (ohne Fonds), nur long, 10 bp je Seite, Alpha ggü. SPY. Je Familie n {20, 100};
Bestehen: beste Variante in der Entdeckung t >= 2,24 UND Bestätigung t >= 2.
- AS Residual Momentum (Blitz, Huij & Martens 2011): Beta ggü. SPY aus 252 Tagen, Summe der
  Residualrenditen t-252..t-21 geteilt durch deren Std. Monatlich höchste Werte.
  Entdeckung 2017-2020 (Warm-up), Bestätigung 2021-2025.
- AT Earnings-Announcement-Premium (Frazzini & Lamont 2007): erwarteter nächster Termin =
  letzte 8-K-Item-2.02-Meldung + 91 Tage; Aktie von 5 Handelstagen vor bis 1 Tag nach dem
  erwarteten Termin halten (nur Information aus der Vergangenheit), alle aktiven gleichgewichtet.
  Varianten {5, 10} Tage Vorlauf statt n. Entdeckung 2016-2020, Bestätigung 2021-2025.
- AU Accrual-Anomalie (Sloan 1996): (Jahresüberschuss - operativer Cashflow) / Bilanzsumme aus
  Jahres-Frames; verfügbar ab 30. April des Folgejahres. Monatlich NIEDRIGSTE Accruals.
- AV ROA-Effekt: Jahresüberschuss / Bilanzsumme (Jahresende), verfügbar ab 30. April des
  Folgejahres. Monatlich HÖCHSTE ROA. AU/AV: Entdeckung 2016-2020, Bestätigung 2021-2025.

## 2026-09-27 -- Ergebnisse Runde 26 (Alpha-t Entdeckung / Bestätigung)

- AS Residual Momentum: n=20 +24,7 % / +25,3 % p.a., Alpha +10,2 % / +12,1 % (t 1,04 / 1,01);
  n=100 1,07 / 0,13 -> NICHT BESTANDEN. Einziges Aktiensignal mit positivem Alpha in BEIDEN
  Zeiträumen, aber zu volatil für Signifikanz (vorgemerkt).
- AT Earnings-Premium: 5 Tage -2,07 / -2,21; 10 Tage -1,69 / -2,04 (signifikant negativ;
  vermutlich Umschlagskosten durch ständige Neugewichtung vieler kurzer Positionen und
  ungenaue Terminschätzung) -> NICHT BESTANDEN.
- AU Accruals: n=100 1,34 / -1,33 (n=20 2021-2025 -11,7 % p.a., MaxDD -80 %) -> NICHT BESTANDEN.
- AV ROA: n=100 0,33 / -1,11 -> NICHT BESTANDEN.

# Runde 27: Bitcoin-Intraday-Saisonalität (2026-09-27)

Quelle: Padyšák & Vojtko (2022, SSRN 4081000), Quantpedia: BTC um 22:00 UTC kaufen, nach 2
Stunden verkaufen, täglich. Daten: Binance BTCUSDT Stundenkerzen (kostenlos).
- Rendite je Tag = Open 00:00 / Open 22:00 - 1 (Kerzen 22:00 und 23:00 gehalten).
- Kosten je Seite: Szenario Maker 0,02 % (Limit-Orders, bester Fall) und Taker 0,10 %.
- Zeiträume: 2018-2021 (Studienzeitraum) und 2022-01 bis heute (nach Veröffentlichung).
- Bestanden, wenn im Maker-Szenario beide Zeiträume Ø-Nettorendite > 0 und nach
  Veröffentlichung t >= 2 (1 Versuch).
- Ergebnis Runde 27: brutto nur 1,5 bp/Tag in beiden Zeiträumen (Binance-Daten; Studie nutzte
  Gemini). Maker 0,02 %: -2,5 bp/Tag netto (t -0,75 / -1,48, ca. -10 % p.a.); Taker 0,10 %:
  ca. -50 % p.a. -> NICHT BESTANDEN.

# Runde 28: Bitcoin an N-Tage-Hoch/-Tief (Padyšák & Vojtko 2022)

- BTC am Folgetag halten, wenn der Tagesschluss (UTC) ein N-Tage-Hoch ODER ein N-Tage-Tief ist
  (Trend am Maximum, Rückprall am Minimum), sonst Cash. N {10, 20} -> 2 Versuche.
- Kosten 0,10 % je Seite (Taker, EU-Börse günstig) auf den Umschlag. Benchmark: BTC halten.
- Zeiträume 2018-2021 (Studie) und 2022-01 bis heute (nach Veröffentlichung).
- Bestanden: beste Variante nach Veröffentlichung Alpha-t >= 2,24, im Studienzeitraum > 0.
- Ergebnis Runde 28: N=10 2018-2021 +65,5 % p.a. (Alpha t 2,17), 2022-heute -8,2 % p.a.
  (t -1,20); N=20 1,50 / -0,90 -> NICHT BESTANDEN. Deutlicher Veröffentlichungseffekt.

# Runde 29: Paarhandel mit Länder-ETFs, Länder-Saisonalität (2026-09-27)

Universum: EWJ, EWG, EWU, EWQ, EWC, EWA, EWH, EWS, EWZ, EWW, EWY, EWT, EWI, EWP, EWN, EWL, EWD
(Yahoo inkl. Dividenden). Kosten 1 bp je Seite + SEC. Bestehen (2 Familien): t >= 2,24 in
2016-2025 UND t >= 2 vor 2016; Benchmark: alle gleichgewichtet.
- AW Paarhandel (Quantpedia "Pairs Trading with Country ETFs"; Gatev et al.): Bildung 252 Tage,
  Handel 126 Tage, 5 Paare, Einstieg bei 2 Std., Ausstieg bei Kreuzung (Funktion aus Runde 9).
  Hinweis: braucht Leerverkäufe (aus Deutschland nur per CFD) -- hier zunächst Beleg des Effekts.
- AX Länder-Saisonalität (Quantpedia "Market Seasonality Effect in World Equity Indexes"): am
  Monatsende die 3 Länder mit der höchsten Durchschnittsrendite im kommenden Kalendermonat über
  die letzten (höchstens) 10 Jahre (mindestens 5), je 1/3, einen Monat halten.

## 2026-09-27 -- Ergebnisse Runde 29

- AW Paarhandel Länder-ETFs: vor 2016 +3,6 % p.a., Alpha t 2,03; 2016-2025 +2,0 %, t 1,03
  -> NICHT BESTANDEN (in beiden Zeiträumen positiv, aber schwach; braucht Leerverkäufe).
- AX Länder-Saisonalität: erster Lauf ungültig (Programmfehler: Gewichte wurden wegen
  "chained assignment" nicht gesetzt, 0 Positionen), korrigiert und neu gerechnet:
  vor 2016 t -0,45, 2016-2025 t -1,09 -> NICHT BESTANDEN.

# Runde 30: Krypto-Wochenende, Funding als Gegensignal (2026-09-27)

BTC (Binance, Tagesschluss UTC), Kosten 0,10 % je Seite, Benchmark BTC halten, 365 Tage.
Zeiträume: 2020-01 bis 2022-12 und 2023-01 bis heute (Funding erst ab 2019-09). Bestehen (2
Familien): t >= 2,24 im jüngeren UND t >= 2 im älteren Zeitraum.
- AY Wochenende: BTC nur für die Renditen von Samstag und Sonntag halten (Kauf Freitag-Schluss,
  Verkauf Sonntag-Schluss).
- AZ Funding-Gegensignal: BTC am Folgetag halten, wenn das Ø-Funding der letzten 7 Tage unter
  seinem Median der letzten 365 Tage liegt, sonst Cash.

Ergebnis Runde 30:
- AY Wochenende: 2020-2022 -13,9 % p.a., Alpha t -1,30; 2023-heute +0,4 %, t -0,63 -> NICHT BESTANDEN.
- AZ Funding-Gegensignal: 2020-2022 +11,0 % (BTC 38 %), t -0,41; 2023-heute +26,5 % (BTC 55 %),
  t 0,08 -> NICHT BESTANDEN. Funding enthält keine verwertbare Information über die nächste Tagesrendite.

# Runde 31: Momentum-Varianten bei Aktien (2026-09-27)

Universum Top 1000 (ohne Fonds), nur long, 10 bp je Seite, monatlich, Alpha ggü. SPY, n {20, 100}.
Entdeckung 2016-2020 (Warm-up 2016), Bestätigung 2021-2025-09-19. Bestehen (2 Familien): beste
Variante Entdeckung t >= 2,24 UND Bestätigung t >= 2.
- BA Konsistentes Momentum (Chen/Kadan/Kose): nur Titel im oberen Dezil sowohl der Rendite t-126..t-21
  als auch t-252..t-147; daraus die n mit höchster 12-1-Rendite (weniger als n -> alle, gleichgewichtet
  1/n, Rest Cash).
- BB Frog-in-the-Pan (Da/Gurun/Warachka 2014): oberes Quintil 12-1-Momentum; ID = sign(PRET) *
  (Anteil negativer - Anteil positiver Tage) über t-252..t-21; daraus die n mit NIEDRIGSTEM ID
  (kontinuierlichste Information).

Ergebnis Runde 31 (Alpha-t Entdeckung / Bestätigung):
- BA konsistentes Momentum: n=20 +25,4 % / +22,3 % p.a., t 1,16 / 0,66; n=100 (nur 16-19 % investiert,
  zu wenige Kandidaten) 0,90 / 0,66 -> NICHT BESTANDEN.
- BB Frog-in-the-Pan: n=20 0,98 / -0,59; n=100 1,09 / -0,95 -> NICHT BESTANDEN.

# Runde 32: S&P-500-Indexänderungen (2026-09-27)

Daten: Änderungstabelle aus Wikipedia "List of S&P 500 companies" (Revision 2025-12-23, 388 Zeilen,
data_cache/sp500_changes.csv), Kurse Alpaca-Tagespanel (nur heute noch vorhandene Symbole;
Survivorship-Verzerrung zugunsten der Strategie, v.a. bei Streichungen). Einstieg zum Schluss des
letzten Handelstags VOR dem Stichtag (dann handeln Indexfonds), H Handelstage halten, je Ereignis
10 % Gewicht, Summe höchstens 100 % (sonst anteilig gekürzt), 10 bp je Seite, Alpha ggü. SPY.
Entdeckung 2016-2020, Bestätigung 2021-2025-09-19. Bestehen (2 Familien): beste Variante
Entdeckung t >= 2,24 UND Bestätigung t >= 2.
- BC Streichungs-Erholung: gestrichene Titel ohne Übernahme/Fusion/Abspaltung/Insolvenz (Grund
  enthält nicht acqui|merg|spin|spun|bankrupt|private|split|reorgan), H {20, 60}.
- BD Aufnahme-Drift: neu aufgenommene Titel, H {20, 60}.

Ergebnis Runde 32 (Alpha-t Entdeckung / Bestätigung; 63 Streichungen, 163 Aufnahmen im Panel):
- BC Streichungs-Erholung: H=20 0,46 / -1,99; H=60 0,44 / -0,80 -> NICHT BESTANDEN (trotz
  Survivorship-Vorteil).
- BD Aufnahme-Drift: H=20 0,31 / -2,17; H=60 0,20 / -1,03 -> NICHT BESTANDEN. Nach Aufnahme eher
  Rückgang (bekannter Umkehreffekt), long-only nicht nutzbar.

# Runde 33: Querschnitts-Umkehr bei Kryptowährungen (2026-09-27)

Binance-Spot-Tageskerzen (UTC, nur heute noch gelistete Paare -> Survivorship-Verzerrung zugunsten
der Strategie), Universum Top-N nach 30-Tage-Quote-Volumen (crypto.universe_mask), nur long,
0,10 % je Seite. Benchmark: gleichgewichtetes Universum (täglich neu gewichtet), Alpha-t per
Regression. Entdeckung 2018-2021, Bestätigung 2022-2025-09-21. Bestehen (2 Familien): beste
Variante Entdeckung t >= 2,24 UND Bestätigung t >= 2.
- BE Wochen-Umkehr: jeden Sonntag zum Schluss die 5 schwächsten der letzten 7 Tage, 7 Tage halten;
  Universum Top {20, 50}.
- BF Tages-Umkehr: täglich die 5 schwächsten des Vortags aus Top 20 bzw. Top 50, 1 Tag halten.

Ergebnis Runde 33 (Alpha-t ggü. gleichgewichtetem Universum, Entdeckung / Bestätigung):
- BE Wochen-Umkehr: Top20 -2,49 / -1,91; Top50 -2,29 / -1,68 -> NICHT BESTANDEN.
- BF Tages-Umkehr: Top20 -3,91 / -4,85; Top50 -4,21 / -5,16 -> NICHT BESTANDEN.
Befund: Verlierer fallen weiter (auch über einen Tag), trotz Survivorship-Vorteil. Die Umkehrung
(Gewinner kaufen) ist ein NEUER Test und wird in Runde 34 separat vorregistriert. (Technik:
btc_1h.pkl aus data_cache/crypto nach data_cache/crypto_hourly verschoben, da load_panel alle
.pkl im Verzeichnis liest.)

# Runde 34: Kurzfrist-Momentum bei Kryptowährungen (2026-09-27)

Gleiche Daten, Kosten, Zeiträume und Benchmark wie Runde 33. Zusätzlich Kosten-Stresstest 0,20 %.
Bestehen (2 Familien, zusätzlich Runde 33 bereits verbraucht): beste Variante Entdeckung t >= 2,5
UND Bestätigung t >= 2, UND Bestätigungs-CAGR > gleichgewichtetes Universum UND > BTC halten.
- BG Tages-Gewinner: täglich die 5 stärksten des Vortags aus Top {20, 50}, 1 Tag halten.
- BH Wochen-Gewinner: jeden Sonntag die 5 stärksten der letzten 7 Tage aus Top {20, 50}, 7 Tage.

Ergebnis Runde 34 (Alpha-t Entdeckung / Bestätigung):
- BG Tages-Gewinner: Top20 -0,97 / -3,73; Top50 -1,81 / -4,57 -> NICHT BESTANDEN.
- BH Wochen-Gewinner: Top20 -0,66 / 0,36; Top50 0,71 / -0,93 (Bestätigung -62,5 % p.a., BTC +27,8 %)
  -> NICHT BESTANDEN.
Befund Runde 33+34: Sowohl die stärksten als auch die schwächsten Altcoins schneiden schlechter ab
als das Universum -- Extrembeweger verlieren in beide Richtungen (hohe Volatilität, Volatilitäts-
Abzug), nach Kosten stark negativ. Kein Kurzfrist-Querschnittssignal bei Krypto.

Ergebnis Runde 35 (Alpha-t Entdeckung / Bestätigung):
- BI Dividendenmonat (Gesamtrendite, ~190 Titel): m-3 -1,59 / -0,52; m-12 -1,40 / -0,18
  -> NICHT BESTANDEN.
- BJ Anstieg vor Ex-Tag (~15.000 Ereignisse): K=5 -3,52 / -4,19; K=10 -2,85 / -1,25
  -> NICHT BESTANDEN. Plausibilitätsprüfung (9.576 Ex-Tage mit Rendite 0,5-5 %, 2017-2024,
  Überrendite ggü. SPY): Tag -3 +0,03 %, -2 -0,02 %, -1 +0,03 %, Ex-Tag -1,09 % (= Dividende;
  bestätigt korrekte Ex-Daten), +1 -0,10 %. Kein Vorlauf vorhanden; Verlust = Umschlagskosten.

# Runde 36: Klassische Anomalien bei europäischen Aktien (2026-09-27)

Motivation: Jacobs & Müller (2020, JFE, 241 Anomalien in 39 Ländern): verlässlicher Rückgang nach
Veröffentlichung NUR in den USA. Alle bisherigen Aktientests waren US-Daten.
Daten: heutige Mitglieder von DAX, MDAX, CAC 40, FTSE 100, AEX, SMI, IBEX 35, FTSE MIB, OMXS30 laut
Wikipedia (379 Titel, Yahoo adjclose inkl. Dividenden, data_cache/europe), in EUR umgerechnet
(GBPEUR, CHFEUR, SEKEUR). Survivorship-Verzerrung: nur heutige Mitglieder -> Benchmark ist das
GLEICHGEWICHTETE Universum derselben Titel (täglich), Alpha-t per Regression dagegen.
Datenbereinigung (vorab festgelegt): Tagesrendite > +50 % oder < -50 %, auf die am Folgetag eine
Gegenbewegung von mehr als der Hälfte folgt, wird als Datenfehler auf 0 gesetzt (beide Tage).
Universum an Tag t: Titel mit >= 252 Tagen Kurshistorie. Monatliche Umschichtung, n {20, 40},
gleichgewichtet, 10 bp je Seite, zusätzlich 0,5 % Stempelsteuer auf Käufe von .L-Titeln.
Entdeckung 2003-2013, Bestätigung 2014-2025-09-19. Bestehen (3 Familien): beste Variante
Entdeckung t >= 2,39 UND Bestätigung t >= 2.
- BK Momentum 12-1: höchste Rendite t-252..t-21.
- BL Niedrige Volatilität: niedrigste Std. der Tagesrenditen über 252 Tage.
- BM Kurzfrist-Umkehr: niedrigste Rendite der letzten 21 Tage.

## 2026-09-27 -- Ergebnisse Runde 36 (Alpha-t ggü. gleichgewichtetem Universum, Entdeckung / Bestätigung)

- BK Momentum 12-1: n=20 23,6 % / 19,7 % p.a. (EW 15,2 % / 11,3 %), Alpha 9,2 % / 8,4 % p.a.,
  t 2,70 / 2,20, MaxDD -50 % / -45 %; n=40 1,22 / 1,57 -> BESTANDEN (erste bestandene Familie
  nach 36 Runden) -- ABER unter Survivorship-Vorbehalt: Universum = HEUTIGE Indexmitglieder. Das
  begünstigt gerade Momentum (frühere Gewinner, die weiter stiegen, sind heute im Index; Gewinner,
  die danach einbrachen, fehlen). Der EW-Benchmark gleicht das nur teilweise aus.
- BL Niedrige Vola: n=20 0,79 / 0,88; n=40 0,94 / 0,26 -> NICHT BESTANDEN.
- BM Kurzfrist-Umkehr: n=20 -2,67 / -1,80; n=40 -2,81 / -2,27 -> NICHT BESTANDEN (negativ:
  Verlierer der letzten 21 Tage laufen weiter schlechter -- passt zu Momentum).

# Runde 37: Robustheitsprüfung Europa-Momentum BK n=20 (vorregistriert vor jeder weiteren Analyse)

Regel unverändert (12-1, monatlich, Top 20, gleichgewichtet, EUR, 10 bp + 0,5 % UK-Stempelsteuer).
- R1 Zeitpunktgenaues Universum: Mitgliederlisten aus alten Wikipedia-Revisionen der Indexseiten
  (je Index eine Revision pro Jahr zum 1. Januar, soweit vorhanden); gehandelt werden nur Titel,
  die zum letzten Jahreswechsel laut dieser Revision Mitglied waren (heute nicht mehr gelistete
  Titel fehlen bei Yahoo; ihr Anteil wird berichtet). Benchmark: EW desselben zeitpunktgenauen
  Universums. Bestehen: Alpha-t >= 1,65 (einseitig 5 %) in BEIDEN Zeiträumen, soweit Revisionen
  reichen.
- R2 Unberührtes Jahr 2025-09-22 bis 2026-09-25 (Yahoo-Daten nach VALIDATION_END, bisher nie
  geladen): Alpha ggü. EW-Universum muss POSITIV sein (nur Vorzeichen; ein Jahr hat keine Macht).
- R3 Kostenstress 25 bp je Seite: Alpha-t in beiden Zeiträumen berichtet (kein Kriterium).
- Zusätzlich berichtet: Umschlag p.a., Anteil UK-Titel, Jahresrenditen.

## 2026-09-27 -- Ergebnisse Runde 37 (R2, R3; R1 folgt)

- R3 Kostenstress 25 bp je Seite: Alpha 7,4 % / 6,4 % p.a., t 2,16 / 1,68. Umschlag 12,6x / 13,4x
  p.a. (beide Seiten gezählt); 30 % der Positionstage UK-Titel.
- Jahresrenditen Momentum vs. EW: schwächer 2004, 2009 (+22 % vs. +59 %, Momentum-Crash nach der
  Krise), 2011, 2021, 2022 (-21 % vs. -11 %), 2023; stärker u.a. 2010, 2017, 2020, 2024, 2025.
- R2 unberührtes Jahr 2025-09-22..2026-09-25 (260 Tage): Momentum +6,5 % (MaxDD -24 %), EW +16,9 %,
  Alpha -12,8 % p.a. (t -0,60) -> NEGATIV -> R2 NICHT BESTANDEN. (Kontrolle: neu geladene Daten
  2024-2025 decken sich mit den alten, Korrelation 1,0.)
- R1 zeitpunktgenaues Universum (198 Wikipedia-Revisionen, Mitgliederlisten ab 2008; 744 historische
  Mitglieder, davon 292 bei Yahoo nicht auffindbar -- Abdeckung 60-92 % je Jahr):
  2008-2013 3,0 % p.a. (EW 19,7 %), Alpha 2,2 %, t 0,25; 2014-2025 10,5 % (EW 7,3 %), Alpha 4,3 %,
  t 1,25 -> R1 NICHT BESTANDEN.

Fazit Runde 36/37: Das Bestehen von Europa-Momentum in Runde 36 war zum großen Teil ein
Survivorship-Artefakt (Alpha halbiert sich mit zeitpunktgenauem Universum, obwohl auch dort noch
Titel fehlen) und das unberührte Jahr ist negativ. KEIN bestätigter Kandidat. Europa-Momentum bleibt
der stärkste Aktienbefund (positives Alpha auch zeitpunktgenau 2014-2025), aber nicht signifikant.
Skripte: research/scripts/r36.py, r37_common.py, r37_wiki.py, r37_r1.py, r37_r2r3.py.

# Runde 38: Gehebelte Indexfonds mit Trendfilter ("LETF + SMA200") (2026-09-27)

Populäre Reddit-/YouTube-Idee; in der EU umsetzbar mit UCITS-Hebel-ETFs (z.B. Amundi Nasdaq-100
Daily 2x, Xtrackers S&P 500 2x). Simulation: Tagesrendite = L x Indexrendite - (L-1) x (T-Bill +
0,5 %)/252 - 0,6 %/252 (TER); außerhalb des Markts T-Bill-Zins. Signal: Schluss > SMA200 des
Index zum Schluss t -> investiert ab t+1. 10 bp je Wechsel. T-Bill: FRED TB3MS (monatlich).
Indexdaten Yahoo ^GSPC (ab 1928) und ^NDX (ab 1985), nur Kursindex (ohne Dividenden, in beiden
Armen gleich).
- BN S&P 500: Entdeckung 1934-1979, Bestätigung 1980-2025-09-19. L {2, 3}.
- BO Nasdaq-100: Entdeckung 1986-2005, Bestätigung 2006-2025-09-19. L {2, 3}.
Bestehen (2 Familien): Alpha-t ggü. Index halten >= 2,24 in der Entdeckung UND >= 2 in der
Bestätigung (beste Variante). Berichtet: CAGR, MaxDD, Sharpe vs. Halten, und L-fach OHNE Filter.

## 2026-09-27 -- Ergebnisse Runde 38 (Alpha-t ggü. Index halten, Entdeckung / Bestätigung)

- BN S&P 500: 2x 10,7 % / 10,8 % p.a. (Halten 5,3 % / 9,4 %), MaxDD -63 % / -53 % (Halten -60 % /
  -57 %), Sharpe 0,59 / 0,56 (Halten 0,41 / 0,59), t 2,88 / 1,54; 3x 2,56 / 1,11 -> NICHT BESTANDEN.
- BO Nasdaq-100: 2x 14,6 % / 18,5 % (Halten 13,4 % / 14,7 %), MaxDD -85 % / -50 %, t 0,88 / 1,31;
  3x 0,68 / 1,25 (MaxDD -95 % 2000-2002) -> NICHT BESTANDEN.
- Ohne Filter: 2x/3x mit MaxDD -83 % bis -100 %; der Filter verhindert den Totalverlust.
Einordnung: In allen 8 Zeilen positives Alpha, aber das Sharpe-Verhältnis liegt ab 1980 auf dem
Niveau des Haltens -- der Filter macht Hebel ÜBERLEBBAR (Drawdown wie 1x bei höherer CAGR), er
ist keine eigenständige Überrendite pro Risiko. Für einen Anleger, der mehr Rendite bei gleichem
maximalem Verlust will, ist 2x S&P 500 + SMA200 die ehrlichste Variante (vorgemerkt, kein
Bestehen). Steuer: jeder Ausstieg realisiert Gewinne (25 % Abgeltungsteuer) -- nicht simuliert.

# Runde 39: Kalendereffekte an europäischen Indizes (2026-09-27)

Motivation: Monatswechsel-Effekt in 31 von 35 Ländern (McConnell & Xu 2008); Halloween-Effekt
international stärker als in den USA (Bouman & Jacobsen 2002). Daten Yahoo ^GDAXI (Performance-
index inkl. Dividenden), ^FCHI, ^FTSE, ^STOXX50E (Kursindizes), gleichgewichtet gepoolt; außerhalb
des Markts 0 % (konservativ). 10 bp je Seite. Entdeckung ab gemeinsamem Datenbeginn bis 2005,
Bestätigung 2006-2025-09-19. Alpha-t ggü. gleichgewichtetem Halten der 4 Indizes. Bestehen
(2 Familien): t >= 2,24 Entdeckung UND >= 2 Bestätigung.
- BP Monatswechsel: investiert vom letzten Handelstag des Monats (Kauf zum Schluss des vorletzten)
  bis Schluss des 3. Handelstags des Folgemonats.
- BQ Halloween: investiert November bis April, Mai bis Oktober Cash.
Änderung VOR jeder Auswertung (Programmlauf brach ohne Ergebnis ab): ^STOXX50E hat bei Yahoo erst
Daten ab 2007-03-30, "gemeinsamer Datenbeginn" wäre 2007. Stattdessen: Pool der jeweils verfügbaren
Indizes (gleichgewichtet, fehlende ausgelassen), Entdeckung 1990-03-01 bis 2005.

Ergebnis Runde 39 (Alpha-t ggü. gleichgewichtetem Halten, Entdeckung 1990-2005 / Bestätigung 2006-2025):
- BP Monatswechsel: +3,9 % / -1,3 % p.a. (19 % investiert), t 1,42 / -1,23 -> NICHT BESTANDEN.
- BQ Halloween: +8,6 % / +4,9 % p.a. (Halten 6,2 % / 4,1 %), MaxDD -32 % / -37 % (Halten -63 % /
  -55 %), t 2,57 / 1,27 -> NICHT BESTANDEN. Positiv in beiden Zeiträumen bei halber Marktzeit,
  nach Veröffentlichung (2002) aber nicht signifikant -- gleiches Muster wie USA (Runde 8 Q).

# Runde 40: DAX-Nachteffekt per CFD (2026-09-27)

Long DAX nur vom Xetra-Schluss bis zur nächsten Eröffnung (Yahoo ^GDAXI Open/Close; FTSE-Opens bei
Yahoo unbrauchbar -- ab 2000 fast immer = Vortagesschluss). Umsetzung per DAX-CFD: Kosten 1 bp je
Seite (Spread ~1-2 Punkte) + Finanzierung (EUR-3M-Zins [FRED IR3TIB01EZM156N, vor 1999 DEM-Wert
nicht verfügbar -> 3M-Zins des ersten verfügbaren Monats] + 2,5 %) / 360 je Kalendernacht (Fr->Mo 3).
Cash-Zins nicht gutgeschrieben (CFD-Margin). Benchmark: DAX halten (Performanceindex).
Entdeckung 1993-2008, Bestätigung 2009-2025-09-19. 1 Variante. Bestehen: Alpha-t >= 2 in BEIDEN.
Hinweis: Der DAX-Eröffnungswert enthält teils veraltete Vortageskurse (Titel ohne ersten Handel);
das verschiebt Nachtrendite in den Tag und macht den Test eher konservativ.

Ergebnis Runde 40: brutto 4,43 / 4,42 bp je Nacht (11,4 % / 11,0 % p.a. -- mehr als DAX halten
7,4 % / 9,9 %; der Handelstag ist netto negativ). Netto nach CFD-Kosten -1,0 % / +2,3 % p.a.,
Alpha t -1,08 / -0,42 -> NICHT BESTANDEN. Die CFD-Finanzierung (Ø 2,7 / 1,3 bp je Nacht) frisst den
Effekt.

# Runde 41: DAX-Nachteffekt per Micro-DAX-Future (2026-09-27) -- NACHTRÄGLICH motiviert

Motivation aus dem Ergebnis von Runde 40 (Bruttoeffekt gesehen; daher kein blinder Test, als
eigener Versuch gezählt). Umsetzung mit Micro-DAX-Future FDXS (1 EUR/Punkt, ~24.000 EUR Nennwert,
passt zu 20k-Konto; seit 2023 handelbar, vorher nur FDAX/Mini): Kosten 0,5 bp je Seite (Spread ~1
Punkt + ~0,50 EUR Gebühr) + Carry des Performanceindex-Futures = EUR-3M-Zins/360 je Kalendernacht
(kein Aufschlag). Sonst identisch zu Runde 40. Bestehen: Alpha-t >= 2,24 in BEIDEN Zeiträumen
(verschärft wegen nachträglicher Motivation). Zusätzlich berichtet: Jahresrenditen, Anteil
positiver Jahre.

Ergebnis Runde 41: netto 4,2 % / 7,4 % p.a. (DAX halten 7,4 % / 9,9 %), MaxDD -45 % / -22 % (DAX
-73 % / -39 %), Sharpe 0,54 / 0,67 (DAX 0,42 / 0,57), Alpha 3,0 % / 3,9 % p.a., t 1,62 / 1,71,
Beta 0,14 / 0,34; 64 % positive Jahre -> NICHT BESTANDEN (Schwelle 2,24). Vorgemerkt als einer der
konsistentesten Befunde (positives Alpha in beiden Zeiträumen, höheres Sharpe als Halten), aber
2003-2007 schwach (netto -0,1 bis -9 % bei stark steigendem DAX) und nicht signifikant.
Offene Punkte, falls weiterverfolgt: echte FDXS-Kurse um 17:30/9:00 statt Indexwerte; Verhalten
der Abendsitzung bis 22:00.

# Runde 42: DAX-Daytrading per CFD mit Minutendaten (2026-09-27)

Daten: Dukascopy DEUIDXEUR (DAX-CFD) Minutenkerzen Bid 2013-01 bis 2025-09-19 (data_cache/dukascopy/
dax), Zeiten Europe/Berlin. Kosten 1,5 Indexpunkte je Round-Trip (Spread ~1 + Schlupf 0,5), Position
1 x Kapital, Short erlaubt (CFD). Kennzahl: Tagesrenditen (0 an Tagen ohne Trade), t-Wert des
Mittelwerts gegen 0 (kein Übernacht-Marktrisiko). Entdeckung 2013-2018, Bestätigung 2019-2025-09-19.
Bestehen (2 Familien): beste Variante t >= 2,24 Entdeckung UND >= 2 Bestätigung.
- BU "Early Bird" Range-Ausbruch 8-9 Uhr: Spanne 08:00-08:59, ab 09:00 erster Ausbruch über Hoch
  (long) bzw. unter Tief (short), Stop auf der Gegenseite, Ausstieg spätestens 17:00 (letzte Kerze
  16:59); Ziel {kein, 1 x Spannenhöhe}. Logik wie gold.day_trade (Stop vor Ziel bei gleicher Kerze).
- BV Intraday-Momentum (Gao, Han, Li & Zhou 2018, auf DAX übertragen): Richtung = Vorzeichen der
  Rendite vom Vortages-Schluss 17:30 bis 09:30; Position in diese Richtung von 17:00 bis 17:30.

Ergebnis Runde 42 (Dukascopy-Daten beginnen erst 2013-09-30; t Entdeckung / Bestätigung):
- BU Early Bird: ohne Ziel +2,45 bp/Tag (5,9 % p.a.) / -0,17 bp, t 1,37 / -0,11; Ziel 1x 0,33 / -0,17
  -> NICHT BESTANDEN.
- BV Intraday-Momentum: -0,41 / -0,04 -> NICHT BESTANDEN.

## Kontrolle zu Runde 41 mit handelbaren CFD-Kursen (vorregistriert, kein neuer Versuch)

Gleiche Regel wie Runde 41, aber Einstieg = Dukascopy-CFD-Kurs 17:30 (erste Minute ab 17:30),
Ausstieg = CFD-Kurs 09:00 (Bid, Spread in den 0,5 bp je Seite enthalten), 2013-10 bis 2025-09-19.
Frage: Bleibt der Nachteffekt mit echten handelbaren Kursen bestehen (Ø brutto > 2 bp/Nacht und
netto t > 0)? Zusätzlich Aufteilung: 17:30-22:00 (Abendsitzung) und 22:00-09:00.
Ergebnis Kontrolle: 2013-2018 brutto 5,75 bp/Nacht, netto 4,73 bp (11,7 % p.a.), t 1,89; 2019-2025
brutto 3,56, netto 2,03 bp (4,3 % p.a.), t 1,02; gesamt netto 3,05 bp (7,1 % p.a.), t 1,97.
-> Der Nachteffekt ist mit handelbaren CFD-Kursen vorhanden (kein Artefakt veralteter Eröffnungs-
werte), aber seit 2019 schwächer und nicht signifikant. (Aufteilung Abend/Nacht nur auf Tagen mit
Kurs um 22:00 -- Teilmenge, nicht additiv.)

# Runde 43: Replikation des Nachteffekts an 5 weiteren Indizes (2026-09-27)

Frage: Ist der DAX-Nachteffekt (Runden 40-42) ein allgemeines Phänomen? Die 5 Indizes wurden
bisher NICHT auf Nachtrenditen angesehen (echter Replikationstest). Daten: Dukascopy-CFD-Minuten
(Bid) usa500idxusd, usatechidxusd (Kassaschluss 16:00 -> Eröffnung 09:30 New York),
gbridxgbp (16:30 -> 08:00 London), fraidxeur (17:30 -> 09:00 Berlin), jpnidxjpy (15:00 -> 09:00
Tokio). Kurs = Open der ersten Minute ab dem Zeitpunkt (max. 5 Min. später). Kosten wie Future:
0,5 bp je Seite + 3M-Zins der Währung/360 je Kalendernacht (FRED IR3TIB01*). 2013-10 bis 2025-09-19.
Portfolio: gleichgewichtet über die an einem Kalendertag verfügbaren Nächte.
Bestehen: Portfolio netto t >= 2 über 2013-2025 UND positiver Mittelwert in beiden Hälften
(2013-2018, 2019-2025) UND mindestens 4 der 5 Indizes einzeln netto positiv.

Ergebnis Runde 43 (netto je Nacht, t; 2013-2018 / 2019-2025):
- S&P 500 1,81 bp (t 1,29) / 0,56 (0,28); Nasdaq-100 2,93 (1,80) / -0,26 (-0,11); FTSE 100 1,52
  (0,99) / -1,10 (-0,62); CAC 40 1,92 (1,11) / -0,17 (-0,09); Nikkei 225 5,23 (1,74) / 4,73 (1,85),
  gesamt t 2,54.
- Portfolio: 2,24 bp (5,4 % p.a., t 1,65) / 0,75 bp (1,3 % p.a., t 0,47); gesamt t 1,37; 5/5
  Indizes gesamt positiv -> NICHT BESTANDEN (t < 2).
Befund: Der Nachteffekt repliziert qualitativ (alle 5 positiv), ist aber seit 2019 außer in Japan
praktisch verschwunden. Japan fällt auf, ist aber nachträglich aus 5 ausgewählt (kein Beleg).

# Runde 44: Volatilitätsprämie per Put-Verkauf -- CBOE PutWrite-Index (2026-09-27)

CBOE PUT: monatlich verkaufte ATM-SPX-Puts, voll besichert in T-Bills (Gesamtrendite). Yahoo ^PUT
ab 1996-08 vs. ^SP500TR. Alpha-t per Regression. Entdeckung 1996-08 bis 2009 (CBOE-Veröffentlichung
2007), Bestätigung 2010-2025-09-19. 1 Familie, keine Varianten. Bestehen: t >= 2 in BEIDEN.
Umsetzbarkeit (nicht simuliert): SPX/XSP/SPY-Optionen haben 65.000-650.000 USD Nennwert je
Kontrakt -> mit 20k EUR nicht voll besichert handelbar; Euro-Stoxx-50-Optionen ~55.000 EUR.
Ergebnis Runde 44: 1996-2009 PUT 8,9 % p.a. (S&P TR 5,8 %), Sharpe 0,68 vs. 0,37, Alpha 4,9 %,
t 2,78; 2010-2025 PUT 7,8 % (S&P TR 14,2 %), Sharpe 0,54 vs. 0,85, Alpha -1,8 %, t -0,65
-> NICHT BESTANDEN. Gleiches Muster wie fast alle Prämien: stark vor der Veröffentlichung, danach weg.

# Runde 45: Unberührtes Jahr für den Nachteffekt (2026-09-27)

Dukascopy-Daten 2025-09-20 bis 2026-09-25 (bisher nie geladen), Regeln und Kosten exakt wie Runde 43
(Future-Kosten) bzw. Kontrolle Runde 41/42 (DAX 17:30 -> 09:00). Nur Vorzeichentest (ein Jahr hat
wenig Macht): berichtet werden Ø netto je Nacht, t und Jahresrendite für
(a) DAX, (b) Nikkei (in Runde 43 nachträglich aufgefallen), (c) 5-Index-Portfolio aus Runde 43,
(d) 6-Index-Portfolio inkl. DAX. "Bestätigt" nur, wenn Ø netto > 0; sonst verworfen.
Ergebnis Runde 45 (2025-09-22..2026-09-25, netto je Nacht):
- (a) DAX -0,07 bp, t -0,02, Jahr -0,9 % -> VERWORFEN (DAX-Nachteffekt der Runden 40-42 bestätigt
  sich nicht).
- (b) Nikkei +11,98 bp, t 1,21, Jahr +29,2 % -> positiv (in einem stark steigenden Jahr; nicht
  signifikant).
- Einzeln: S&P 500 +3,37 bp (t 1,01), Nasdaq-100 +5,60 (1,02), FTSE -2,07 (-0,71), CAC -0,49 (-0,12).
- (c) 5-Index-Portfolio +4,02 bp, t 1,13, +10,7 %; (d) 6-Index-Portfolio +3,37 bp, t 0,94, +8,8 %
  -> positiv, nicht signifikant.
Gesamtbild Nachteffekt (Runden 40-45): real vorhanden (brutto positiv in fast allen Märkten und
Zeiträumen), netto nach Future-Kosten klein und instabil; der einzige über alle Prüfungen
durchgehend positive Markt ist Japan -- das ist aber nachträglich ausgewählt. Kein Kandidat, der
die vorregistrierten Kriterien erfüllt.

# Runde 46: Gotobi-Effekt bei USD/JPY (2026-09-27)

Hypothese (Ito & Yamada 2017; Bessho et al.): An Gotobi-Tagen (5., 10., 15., 20., 25. und letzter
Tag des Monats; fällt er auf ein Wochenende, gilt der vorherige Freitag -- japanische Feiertage
nicht berücksichtigt) kaufen japanische Importeure USD vor dem Tokio-Fixing um 9:55 JST; der Yen
schwächt sich vorher ab. Daten Dukascopy USDJPY m1 (Bid, data_cache/dukascopy/fx), Zeiten Asia/Tokyo.
Kosten 0,5 bp je Seite (Spread ~0,2-0,5 Pips). Tagesrendite, 0 an Tagen ohne Position.
Entdeckung 2008-2016 (vor Veröffentlichung), Bestätigung 2017-2025-09-19, plus unberührtes Jahr
2025-09-22..2026-09-25 (neu geladen) als Vorzeichentest.
- BX Gotobi: long USDJPY 05:00 -> 09:55 JST an Gotobi-Tagen.
- BY Kontrolle / Alle-Tage-Variante: long USDJPY 05:00 -> 09:55 JST an allen ANDEREN Werktagen.
Bestehen (2 Familien): t >= 2,24 Entdeckung UND >= 2 Bestätigung UND unberührtes Jahr positiv.

## 2026-09-27 -- Ergebnisse Runde 46

- BX Gotobi: 2008-2016 639 Trades, Ø 4,64 bp, 59 % Treffer, t 4,68; 2017-2025 627 Trades, Ø 2,05 bp,
  58 % Treffer, t 2,80; unberührtes Jahr 70 Trades, Ø +2,05 bp (Summe +1,43 %) -> BESTANDEN.
  (Erste Familie, die alle drei Hürden inkl. unberührtem Jahr nimmt; auch NACH der Veröffentlichung
  2017 signifikant.) Wirtschaftlich klein: ~70 Trades/Jahr, 1,4 % p.a. bei 1x; Jahres-Sharpe grob
  t/sqrt(Jahre) = 2,80/sqrt(8,7) ~ 0,95.
- BY andere Tage (Kontrolle): t 1,57 / -0,49, unberührt -1,73 bp -> NICHT BESTANDEN. Der Effekt ist
  spezifisch für Gotobi-Tage (passt zur Fixing-Nachfrage-Erklärung).

# Runde 47: Robustheit Gotobi (vorregistriert vor weiterer Analyse)

Kriterien (alle für 2017-2025-09-19, dem Zeitraum nach Veröffentlichung):
- R1 Kostenstress 1,5 bp je Seite (breitere Retail-Spreads): t >= 1,65.
- R2 Einstiegszeit 03:00, 07:00, 08:00 JST (Ausstieg 09:55): alle drei Ø > 0.
- R3 Jahre 2008-2025 (jeweils Kalenderjahr, 2025 bis 09-19): mindestens 60 % positiv.
- R4 Ausstieg 10:30 statt 09:55 (nach dem Fixing): berichtet, erwartet kleiner (Umkehr nach Fix).
- R5 Swap: long USDJPY erhält i.d.R. positiven Swap (USD-Zins > JPY-Zins) -- nicht einbezogen
  (konservativ), nur erwähnt.

## 2026-09-27 -- Ergebnisse Runde 47 (2017-2025, Gotobi)

- R1 Kostenstress 1,5 bp je Seite: Ø 0,05 bp, t 0,07 -> NICHT ok. Brutto ~3 bp je Trade; nur mit
  ECN-Kosten (<= ~1 bp Round-Trip, z.B. IBKR: ~0,2 Pip Spread + 0,2 bp Kommission je Seite) sinnvoll.
- R2 Einstieg 03:00 / 07:00 / 08:00: Ø 2,51 / 2,22 / 1,16 bp, t 2,87 / 3,27 / 1,86 -> ok.
- R3 Jahre positiv 15/18 = 83 % -> ok; aber 2024 -0,09 %, 2025 (bis 09-19) -1,85 %; unberührtes Jahr
  2025-09..2026-09 +1,43 %.
- R4 Ausstieg 10:30: Ø -0,67 bp (t -0,82) -> nach dem Fixing Umkehr; stützt die Erklärung
  (Fixing-Nachfrage), der Gewinn muss VOR 9:55 realisiert werden.
Gesamturteil Gotobi: statistisch der robusteste Befund der gesamten Suche (signifikant vor UND nach
Veröffentlichung, positiv im unberührten Jahr, spezifisch für Gotobi-Tage, plausibler Mechanismus),
aber wirtschaftlich dünn und kostensensitiv: ~3 bp brutto je Trade, ~70 Trades/Jahr, nur mit
ECN-Kosten und Hebel (z.B. 5-10x) lohnend; letzte zwei Kalenderjahre schwach. Empfehlung:
Papierhandel mit echten Kursen/Spreads eines ECN-Brokers, bevor Geld eingesetzt wird.
Größenordnung (beschreibend, 2017-2025, Regel unverändert): Kosten 0,3 bp je Seite: 3x 5,3 % p.a.
(MaxDD -10 %), 5x 8,9 % (-16 %), 10x 17,8 % (-31 %); Kosten 0,5 bp: 3x 4,4 %, 5x 7,3 % (-18 %),
10x 14,5 % (-33 %). Schlechtester Einzeltrade bei 10x -8,8 %.

# Runde 48: Monatsend-Rebalancing von Pensionsfonds (Harvey, Mazzoleni & Melone 2025) (2026-09-27)

Kalender-Signal (NBER w33554, Febr. 2025; Beschreibung laut QuantReturns): an den letzten 5
Handelstagen des Monats Position im Spread Aktien minus Anleihen = -Vorzeichen(Monatsrendite bis
Vortag SPY - TLT); am LETZTEN Handelstag umgekehrt (+Vorzeichen). Sonst keine Position.
P&L = w x (r_SPY - r_TLT) (Yahoo adjclose, TLT ab 2002-07). Kosten 2 bp je Seite und Bein bei jeder
Positionsänderung (Futures wären günstiger). Umsetzung für DE: Micro-E-mini S&P (MES) + 10Y-
Treasury-Future (bzw. FDXS + Bund-Future), IBKR.
Zeiträume: Entdeckung 2003-2014, Bestätigung 2015-2025-09-19 (beide im Stichprobenzeitraum des
Papiers 1997-2023!), plus nach Veröffentlichung 2025-02-01..2026-09-25 (einzig echt neue Daten).
1 Familie, keine Varianten. Bestehen: t >= 2 in beiden Zeiträumen UND Ø > 0 nach Veröffentlichung.
Ergebnis Runde 48: 2003-2014 Ø 0,30 bp je aktivem Tag, t -0,08; 2015-2025 Ø 2,67 bp, t 0,33; nach
Veröffentlichung (2025-02..2026-09, 100 aktive Tage) Ø -16,7 bp, t -1,96 -> NICHT BESTANDEN. Das
Kalendersignal allein repliziert mit SPY/TLT nicht (Kopfzahlen des Papiers/Blogs: kombiniertes
Schwellen- + Kalendersignal, auf S&P-Vola skaliert, Futures); nach Veröffentlichung deutlich negativ.

# Runde 49: Gotobi mit echten Dukascopy-Bid/Ask-Kursen (vorregistriert, Teil der Gotobi-Prüfung)

Kauf zum ASK (Open der Minute ab 05:00 JST), Verkauf zum BID (Open der Minute ab 09:55 JST), keine
weiteren Kosten (Dukascopy ist ein ECN-Anbieter; Kommission dort ~0,35 bp je Seite wird zusätzlich
abgezogen). 2017-2025-09-19 und unberührtes Jahr. Kriterium: Ø netto > 0 und t >= 1,65 für
2017-2025. Zusätzlich berichtet: mittlerer Spread um 05:00 und 09:55 JST.
Ergebnis Runde 49: Spread 05:00 JST Ø 1,29 bp (Median 0,34 -- einzelne sehr breite Minuten), 09:55
Ø 0,35 bp. 2017-2025: 626 Trades, Ø netto 1,00 bp, 55 % Treffer, Summe +6,3 %, t 1,38 -> NICHT
ok (Schwelle 1,65); unberührtes Jahr Ø +1,21 bp, t 0,67.
Endurteil Gotobi: Der Effekt ist statistisch real (brutto ~3 bp, signifikant vor und nach
Veröffentlichung, Umkehr nach dem Fixing), aber mit echten ECN-Bid/Ask-Kursen bleibt ~1 bp je Trade
(~0,7 % p.a. bei 1x) und die Signifikanz geht verloren. Nur mit passiven Limit-Orders (Spread
verdienen statt zahlen) wäre mehr möglich -- nicht mit Minutendaten prüfbar. Kein handelbarer
Kandidat nach den Kriterien; bester Befund der Suche für einen Papierhandel.

# Runde 50: Querschnitts-Funding-Carry bei Altcoins (2026-09-27)

Erweiterung von Familie O (Runde 6; BTC/ETH-Prämie im Holdout auf ~1-2 % p.a. gefallen): Prämie
dort ernten, wo das Funding gerade hoch ist. Universum: Spot-Top-30 nach Volumen (crypto.
universe_mask) mit heute existierendem USDT-Perpetual (inkl. 1000PEPE/1000SHIB/1000BONK/1000FLOKI/
1000LUNC; delistete Perps wie LUNA fehlen -> Verzerrung zugunsten der Strategie).
Regel: jeden Sonntag zum Tagesschluss (UTC) die k Coins mit dem höchsten Ø-Funding der letzten
7 Tage (nur > 0); je Coin 1/k des Kapitals: halb Spot long, halb Perp short (1x). Tagesrendite je
Coin = 0,5 x (Spot - Perp + Funding); fehlende Kurse = 0. Kosten Spot 0,10 %, Perp 0,05 % je Seite
auf den Umschlag. k {5, 10}.
Kennzahl: Überrendite über T-Bill (FRED TB3MS/365). Entdeckung 2020-01 bis 2022-12, Bestätigung
2023-01 bis 2025-09-21, unberührtes Jahr 2025-09-22 bis 2026-09-25 (Altcoin-Funding dort bisher nicht
angesehen). Bestehen (1 Familie, 2 Varianten): beste Variante Überrendite-t >= 2,24 Entdeckung UND
>= 2 Bestätigung UND Überrendite im unberührten Jahr > 0. Berichtet: MaxDD, größter Tagesverlust,
größte Tages-Perp-Rendite eines gehaltenen Coins (Liquidationsrisiko der 1x-Short-Seite).
Umsetzbarkeit DE: Binance-Futures für deutsche Privatkunden i.d.R. nicht verfügbar; Alternativen
(DEX wie Hyperliquid/dYdX) mit eigenem Risiko -- im Ergebnis bewerten.

Ergebnis Runde 50 (Überrendite über T-Bill, t):
- k=5: 2020-2022 +11,4 % p.a. (Sharpe 6,0), t 9,51; 2023-2025 +1,0 % (über T-Bill -3,8 %), t -4,11;
  unberührt -7,6 %, t -4,13.
- k=10: +11,6 % (Sharpe 7,1), t 11,35; +2,0 % (-2,8 % über T-Bill), t -5,00; unberührt -4,2 %, t -5,05
  -> NICHT BESTANDEN. Größte Tages-Perp-Rendite eines gehaltenen Coins bis +73 % (1x-Short nahe
  Liquidation). Die Funding-Prämie ist seit 2023 auch bei Altcoins wegarbitriert; zuletzt negativ
  (Kosten der wöchentlichen Umschichtung > Funding).

# Runde 51: "Best Ideas" aus 13F-Meldungen (Cohen, Polk & Silli 2010) (2026-09-27)

Daten: SEC Form-13F-Datensätze (quartalsweise ZIPs 2013Q2-2026, INFOTABLE + SUBMISSION), nur
13F-HR (keine Änderungen), Zeilen ohne Put/Call, Aktien (Wertpapierklasse nicht "PRN"/Anleihen).
CUSIP -> Ticker per OpenFIGI (US-Aktien); Kurse Alpaca-Panel (nur heute noch vorhandene Symbole).
Definition: Für jeden Melder mit 20-200 Positionen und >= 100 Mio. USD gemeldetem Wert ist die
"beste Idee" die Position mit dem größten Portfoliogewicht UNTER AUSSCHLUSS der 100 Titel mit dem
höchsten Gesamtwert über alle Melder im selben Berichtsquartal (Näherung für "Gewicht über
Marktgewicht", da Mega-Caps sonst immer größte Positionen sind).
Portfolio: an jedem Monatsende alle besten Ideen aus den jeweils letzten 13F-HR-Meldungen je Melder
mit Meldedatum in den letzten 92 Tagen (Information ab Meldedatum verfügbar), gleichgewichtet je
Titel, 1 Monat halten; nur Titel im Top-1000-Universum (ohne Fonds). 10 bp je Seite.
Varianten: Melder mit 20-200 Positionen vs. konzentrierte Melder mit 20-50 Positionen.
Entdeckung 2014-2019, Bestätigung 2020-2025-09-19. Alpha-t ggü. SPY. Bestehen (1 Familie): beste
Variante t >= 2,24 Entdeckung UND >= 2 Bestätigung.

# Runde 52: Kurzfrist-Umkehr-Regeln (Z1 IBS-Band, Z2 Double 7) an DAX, CAC 40, Nikkei (2026-09-27)

Regeln exakt wie Runde 12 (anomalies.ibs_band_positions, double7_positions), angewandt auf Yahoo
^GDAXI, ^FCHI, ^N225 (OHLC, ab 1994; data_cache/yahoo_unseen bis 2026-09-25). Umsetzung per Index-
Future: Kosten 0,5 bp je Seite; investierte Tage tragen Indexrendite - T-Bill/252 (Future-Carry,
konservativ für Kursindizes). Portfolio = Mittel der 3 Strategierenditen; Benchmark = Mittel der
3 Indexrenditen. Entdeckung 1994-2008, Bestätigung 2009-2025-09-19, unberührtes Jahr 2025-09-22..
2026-09-25. Bestehen (2 Familien): Alpha-t >= 2,24 Entdeckung UND >= 2 Bestätigung UND Alpha im
unberührten Jahr > 0.
Ergebnis Runde 52 (Alpha-t Entdeckung / Bestätigung / unberührt):
- Z1 IBS-Band: 0,44 / 0,50 / 0,20 (Alpha +1,0 / +0,9 / +1,3 % p.a.) -> NICHT BESTANDEN.
- Z2 Double 7: 1,37 / -1,68 / -0,33 -> NICHT BESTANDEN.
Die in den USA vor 2016 starken Umkehrregeln (SPY t 3,7) wirken an DAX/CAC/Nikkei nie signifikant.

Ergebnis Runde 51 (306.492 13F-HR-Meldungen, davon 154.720 qualifiziert; 10.913 Kandidaten-CUSIPs,
etwa die Hälfte per OpenFIGI einem US-Ticker zuordenbar; 85.558 Meldungen mit Ticker im Panel):
- 20-200 Positionen: Ø 457 Titel, 14,6 % / 11,2 % p.a. (SPY 14,2 % / 13,5 %), Alpha t 0,01 / -0,74.
- 20-50 Positionen: Ø 268 Titel, 15,2 % / 12,2 %, t 0,20 / -0,49 -> NICHT BESTANDEN.
Die gebündelten "besten Ideen" sind so breit gestreut, dass sie den Markt nachbilden (Beta 1,05-1,10);
kein Informationsvorsprung erkennbar.
Nicht getestet (vermerkt): Pre-ECB-Drift -- ECB-Sitzungstermine nicht als statische Liste abrufbar.

# Runde 53: Nikkei-Nachteffekt 1994-2013 (Test der in Runde 43 nachträglich aufgefallenen Hypothese)

Die Nikkei-Nachtrenditen vor 2013-10 wurden bisher nie angesehen (Dukascopy beginnt 2013-10).
Yahoo ^N225 Open/Close (Opens geprüft: nie = Vortagesschluss). Nacht = Open_t / Close_t-1 - 1,
Kosten wie Runde 43 (0,5 bp je Seite + JPY-3M-Zins/360 je Kalendernacht, negative Zinsen = 0).
Zeitraum 1994-01-01 bis 2013-09-29. 1 Variante. Bestehen: netto t >= 2 und Ø > 0.
Hinweis: Eröffnungswert des Index enthält teils veraltete Kurse (konservativ, s. Runde 40).

## 2026-09-27 -- Ergebnis Runde 53

- 1994-2003: brutto 3,13 bp, netto 2,09 bp/Nacht (5,2 % p.a.), t 2,45; tagsüber Ø -4,17 bp.
- 2004-2013: brutto 4,39, netto 3,23 bp (7,7 % p.a.), t 2,03; tagsüber -2,12 bp.
- 1994-2013 gesamt: netto 2,65 bp (6,4 % p.a.), t 2,97 -> BESTANDEN.
- Kostenstress (nur berichtet): 1,0 bp je Seite 3,7 % p.a., t 1,85; 1,5 bp je Seite 1,2 %, t 0,73.
Gesamtbild Nikkei-Nacht über 32 Jahre: 1994-2013 t 2,97 (unabhängige Prüfung), 2013-2025 t 2,54
(Dukascopy, Runde 43), unberührtes Jahr 2025/26 +11,98 bp (t 1,21). Während der Nikkei 1994-2013
praktisch nicht stieg, lag die Nachtrendite bei +6 % p.a. und die Tagesrendite deutlich negativ.
Zweiter robuster Befund neben Gotobi (Runden 46-49) -- ebenfalls kostensensitiv.
Umsetzung (nicht simuliert): OSE-Nikkei-225-Mini/Micro-Futures (IBKR). Tagessitzung endet mit
Schlussauktion (15:45 JST), Tagessitzung beginnt mit Eröffnungsauktion (08:45 JST) -> Handel in den
Auktionen ohne Spread, nur Kommission (~0,2 bp) -> 0,5 bp je Seite realistisch. Abweichung: Future-
Zeiten 15:45/08:45 statt Index 15:00(15:30)/09:00; Micro-Kontrakt ~2.500-4.000 EUR Nennwert passt
zu 20k EUR. Nächster Schritt wäre ein Vorwärtstest (Papierhandel).

## Kontrolle zu Runde 53: Future-Sitzungszeiten (vorregistriert, kein neuer Versuch)

Dukascopy jpnidxjpy (2013-10..2026-09-25, inkl. unberührtem Jahr): Einstieg zur Schlusszeit der
OSE-Tagessitzung (15:15 JST, ab 2024-11-05 15:45), Ausstieg 08:45 JST (Eröffnungsauktion), Kosten
0,5 bp je Seite + JPY-Zins. Frage: bleibt Ø netto > 0 mit t >= 1,65 für 2013-2025?
Ergebnis Kontrolle: 2013-2018 (nur 508 Nächte mit Kurs um 15:15 -- Datenlücken) Ø netto 4,19 bp, t 1,05;
2019-2025 4,22 bp (9,8 % p.a.), t 1,69; 2013-2025 4,21 bp (9,9 % p.a.), t 1,98 -> ok (>= 1,65);
unberührtes Jahr 13,67 bp, t 1,46. Der Effekt besteht auch zu handelbaren Future-Sitzungszeiten.

# Runde 54: Tägliche Fixing-Umkehr im Devisenmarkt (Krohn, Mueller & Whelan, JF 2024) (2026-09-27)

Paper (Stichprobe 1999-2018, G9-Währungen): USD steigt vor den drei großen Fixings und fällt danach,
jeden Tag. Fenster (wie im Paper, Zeitzonen je Ort, Sommerzeit berücksichtigt):
- vor Tokio: 17:00 New York (Vortag) -> 09:55 Tokio: USD long
- nach Tokio: 09:55 Tokio -> 08:00 Frankfurt: USD short
- vor EZB: 08:00 Frankfurt -> 14:15 Frankfurt: USD long
- nach London: 16:00 London -> 17:00 New York: USD short
Familien (je gleichgewichtet über EURUSD, GBPUSD, USDJPY; Dukascopy-Bid-Minuten):
- CB Europa-Fenster = vor EZB + nach London (2 Round-Trips je Tag und Paar).
- CC Tokio-Fenster = vor Tokio + nach Tokio (2 Round-Trips).
Kosten 0,5 bp je Seite je Round-Trip (ECN), Stress 1,0 bp berichtet. Tagesrendite = Summe der
Fenster. Zeiträume: 2008-2018 = Replikation im Paper-Zeitraum (nur berichtet), 2019-2025-09-19 =
nach der Stichprobe des Papers (echte Prüfung), plus unberührtes Jahr 2025-09-22..2026-09-25.
Bestehen (2 Familien): t >= 2,24 für 2019-2025 UND Ø > 0 im unberührten Jahr.
Überschneidung: Das Tokio-Fenster enthält die Gotobi-Tage (Runde 46) -- zusätzlich berichtet: CC
ohne Gotobi-Tage.

Ergebnis Runde 54 (netto 0,5 bp je Seite, t; 2008-2018 / 2019-2025 / unberührt):
- CB Europa: +0,47 bp/Tag (t 0,66) / -2,15 (t -2,71) / -3,73 (t -2,19) -> NICHT BESTANDEN.
- CC Tokio: +1,97 bp/Tag (5,0 % p.a., t 4,55) / -2,27 (t -4,80) / -3,66 (t -3,60) -> NICHT BESTANDEN.
- Brutto je Fenster im Paper-Zeitraum stark (vor Tokio t 6,26, nach Tokio 7,50, vor EZB 4,80):
  Replikation gelingt, Daten und Umsetzung sind also richtig. Nach 2018 kehrt sich "vor Tokio" um
  (t -2,42); "vor EZB" schwächt sich auf t 1,57 ab und ist im unberührten Jahr null.
- CC ohne Gotobi-Tage: 2008-2018 t 2,22, 2019-2025 t -5,57. Die Gotobi-Tage (Runde 46) hielten
  nach 2017 als einzige Teilmenge -- die gewöhnliche tägliche Fixing-Umkehr ist nach der
  Veröffentlichung verschwunden bzw. umgekehrt.

## 2026-09-27 -- Gesichtet, nicht getestet (kein Versuch gezählt)

- Quantpedia "GDX Overnight Drift" (>30 % p.a.): von Quantpedia selbst als OHLC-Artefakt entlarvt
  (Eröffnungskurs der Tageskerze nicht handelbar; mit 1-Minuten-Ausführung weitgehend weg).
- Quantpedia "Sectoral Intramonth Momentum Cycle" (veröffentlicht 2026-08-17, Stichprobe bis 2026-06,
  Sharpe 0,55 ohne Kosten): keine Daten nach der Stichprobe verfügbar; drei nachträglich gewählte
  Teilfenster mit Vorzeichenwechsel -> hohes Überanpassungsrisiko. Frühestens als Vorwärtstest.

# Runde 55: Aktien-Impuls -> FX-Nachzügler (Idee aus r/algotrading, "an edge is a reason someone pays you") (2026-09-27)

Hypothese: Nach einer großen Übernacht-Bewegung des S&P 500 ziehen Devisenpaare, die ihrer üblichen
Sensitivität noch nicht gefolgt sind, in den nächsten Stunden nach (langsamerer FX-Fluss zahlt).
Daten: Dukascopy-Minuten (Bid) usa500idxusd, EURUSD, GBPUSD, USDJPY, 2013-10 bis 2026-09-25.
Definition je Handelstag d (New-York-Zeit):
- Impuls: S&P-Rendite 16:00 (Vortag) -> 03:00 (Europa-Eröffnung). Bedingung |Impuls| > 1 x Std. dieser
  Fensterrendite der letzten 60 Tage (ohne d).
- Beta je Paar: OLS-Steigung der Paarrendite (Kurs, z.B. EURUSD) auf die S&P-Rendite im selben
  Fenster über die letzten 250 Tage (ohne d); erwartete Bewegung = Beta x Impuls.
- Nachzügler: Paar hat im Fenster weniger als die Hälfte der erwarteten Bewegung gemacht (in
  Richtung der Erwartung). Dann Position in Richtung der Erwartung von 03:00 bis 07:00 New York.
- Kosten 0,5 bp je Seite. Portfolio: Mittel der Trades eines Tages (0 an Tagen ohne Trade).
Entdeckung 2013-10..2018, Bestätigung 2019..2025-09-19, unberührt 2025-09-22..2026-09-25.
1 Familie, keine Varianten. Bestehen: t >= 2 in Entdeckung UND Bestätigung UND Ø > 0 unberührt.
Ergebnis Runde 55 (Trades = Paar-Tage; Ø netto je Trade; Portfolio-t):
- 2013-2018: 194 Trades, Ø -2,80 bp, 47 % Treffer, t -0,23; 2019-2025: 550 Trades, Ø -2,44 bp, 46 %,
  t -1,22; unberührt: 84 Trades, Ø -0,76 bp, 51 %, t -0,56 -> NICHT BESTANDEN.
- Je Paar 2019-2025: EURUSD -4,3 bp, GBPUSD -5,0 bp, USDJPY +1,6 bp. Kein Nachziehen erkennbar;
  FX verarbeitet den Aktienimpuls bis zur Europa-Eröffnung bereits vollständig.
(Anzeige-Korrektur vor Eintrag: erster Lauf zählte leere Einträge als Trades; Urteil unverändert.)

# Runde 56: Nachteffekt an weiteren asiatisch-pazifischen Indizes (2026-09-27)

Frage: Ist der robuste Nikkei-Nachteffekt (Runde 53) ein asiatisches Phänomen? Hang Seng und ASX 200
wurden nie auf Nachtrenditen angesehen. Daten Dukascopy-CFD (Bid): hkgidxhkd (16:00 -> 09:30
Hongkong), ausidxaud (16:00 -> 10:00 Sydney). Kosten 0,5 bp je Seite + 3M-Zins/360 je Kalendernacht
(HKD: USD-Zins wegen Dollarbindung; AUD: IR3TIB01AUM156N). 2013-10..2025-09-19 und unberührtes Jahr.
Bestehen: Portfolio (gleichgewichtet) netto t >= 2 für 2013-2025 UND beide Indizes einzeln Ø > 0
UND Portfolio im unberührten Jahr Ø > 0.

## 2026-09-27 -- Literatur zu den zwei robusten Befunden

- Nikkei-Nacht: "Stock prices in Japan rise at night" (Pacific-Basin Finance Journal 2002; Nikkei
  1986-1998: Handelszeit Ø negativ, Nacht signifikant positiv). Damit liegen unsere Prüfungen
  1994-2013 (t 2,97) und 2013-2025 (t 2,54) überwiegend NACH der Veröffentlichung -- der Effekt
  hat die Veröffentlichung überlebt. Ursache laut Literatur ungeklärt.
- Gotobi: Bessho, Sugimoto & Suzuki (2023, Stichprobe 2018-2020, 03:00 -> 09:55) und arXiv
  2301.13204; kommerzielle MT4/MT5-"Gotobi-EAs" verbreitet -> Risiko, dass der Effekt zunehmend
  vorweggenommen wird (passt zu den schwachen Jahren 2024/2025, unberührtes Jahr wieder positiv).
Ergebnis Runde 56 (ASX-Daten erst ab 2014; leere Datei 2013 entfernt):
- Hang Seng: 2013-2018 Ø 1,85 bp (t 0,81), 2019-2025 0,91 (0,35), unberührt -0,21 (-0,04).
- ASX 200: -2,43 (-1,06) / 0,34 (0,17), gesamt Ø -0,58 bp, unberührt 1,20 (0,30).
- Portfolio 2013-2025 Ø 0,76 bp, t 0,56 -> NICHT BESTANDEN.
Befund: Der Nachteffekt ist kein allgemeines asiatisch-pazifisches Phänomen; Japan ist ein
Sonderfall (passt zur Literatur, die es als japanspezifisches Rätsel beschreibt).

# Runde 57: NT-Verhältnis vor den japanischen Dividendenstichtagen (2026-09-27)

Mechanismus (QUICK Japan Market View u.a.): Treuhandbanken reinvestieren die erwarteten Dividenden
der Indexfonds Ende März und Ende September per Futures-Kauf, überwiegend TOPIX -> TOPIX schlägt
Nikkei 225 in den Tagen vor dem Dividendenabschlag (NT-Verhältnis fällt).
Daten: Yahoo 1306.T (TOPIX-ETF) und 1321.T (Nikkei-225-ETF), adjclose, ab 2009 (beide zahlen im
Juli aus -- keine Ausschüttung im Fenster). Yahoo-Datum = Tokio-Datum - 1 Tag (New-York-Umrechnung)
-> +1 Kalendertag korrigiert.
Ereignis: letzter Tag MIT Dividendenanspruch im März/September = Stichtag (letzter Handelstag des
Monats) - 3 Handelstage bis 2019-07-15 (T+3), danach - 2 Handelstage (T+2).
Position: long 1306 / short 1321 (gleiche Nominale) vom Schluss K Handelstage vor diesem Tag bis zu
dessen Schluss. K {5, 10}. Kosten 4 x 1 bp je Ereignis (Futures).
Bestehen (1 Familie, 2 Varianten): beste Variante Ø je Ereignis mit t >= 2,24 über 2009-2025 UND
Ø > 0 in beiden Hälften (2009-2016, 2017-2025) UND Ø > 0 bei den Ereignissen im unberührten Jahr
(Sept. 2025, März 2026).
Ergebnis Runde 57 (33 Ereignisse 2009-2025):
- K=5: Ø 4,8 bp, 64 % Treffer, t 0,33 (2009-2016 -1,4 bp; 2017-2025 +10,7 bp).
- K=10: Ø 38,1 bp, t 1,25 (2009-2016 -27,8 bp; 2017-2025 +100,1 bp); unberührt Sept. 2025 -220 bp,
  März 2026 +187 bp -> NICHT BESTANDEN.
Programmfehler (ohne Einfluss aufs Urteil): Sept. 2026 wurde als Ereignis gezählt, obwohl die Daten
vor dem echten Monatsende enden (Prüfung "Tag >= 25" nach Datumskorrektur zu schwach). Der Effekt ist
erst seit 2017 sichtbar (+100 bp bei K=10) -- nachträglich betrachtet, kein Beleg.

# Runde 58: Rohstoff-Saisonalität "vorweggenommen" (Quantpedia, 2024-12-05) (2026-09-27)

Regel (Paper, Stichprobe 2007-01..2024-06): 4 Sektoren (Agrar, Industriemetalle, Energie,
Edelmetalle); für Monat X Signal = Rendite des Monats X-11 (Vorjahres-Folgemonat); die 2 besten
long, die 2 schlechtesten short, je 25 %, 1 Monat. (Achtung: Die X-12-Variante versagte im Paper,
X-11 wurde also nach Ansicht der Ergebnisse gewählt.)
Prüfung außerhalb der Paper-Stichprobe:
- Vorher 2001-09..2006-12: IMF-Monatsindizes via FRED (PNRGINDEXM Energie, PMETAINDEXM Metalle,
  PFOODINDEXM Nahrung als Agrar-Näherung; Monatsdurchschnitte) + Gold (Yahoo GC=F Monatsende).
  Keine Roll-Sprünge (ausser gering bei Gold).
- Nachher 2024-07..2026-08: DB-ETFs DBA, DBB, DBE, DBP (Yahoo adjclose, Monatsende).
- Replikation 2007-01..2024-06 mit den ETFs nur berichtet.
Kosten 10 bp je Seite. 1 Familie. Bestehen: vorher t >= 2 UND nachher Ø > 0.
Hinweis: Macht gering (erwartetes t vorher ~1,3 bei Paper-Sharpe 0,55).
Ergebnis Runde 58: vorher 2001-2006 (64 Monate) Ø -0,3 bp/Monat, t -0,01; Replikation 2008-2024-06
Ø +18 bp/Monat, Sharpe 0,25, t 1,01 (Paper: 0,55); nachher 2024-07..2026-08 (26 Monate) -7,8 % p.a.,
t -0,99 -> NICHT BESTANDEN. Außerhalb der Paper-Stichprobe keine Spur des Effekts.

## 2026-09-27 -- Literatur: "What survives honest evaluation?" (arXiv 2608.27734, Aug. 2026)

LLM-gestützte Strategiesuche (453 US-Aktien zeitpunktgenau, 39 ETFs, bis 100 Kandidaten, Deflated
Sharpe, PBO): KEINE der gefundenen Strategien besteht; nur passive Benchmarks haben Konfidenz-
intervalle ohne Null. Deckt sich mit dieser Suche.

# Runde 59: Prämie an Makro-Ankündigungstagen (Savor & Wilson 2013) (2026-09-27)

Hypothese: Aktien verdienen an Tagen mit CPI-, Arbeitsmarkt- (Employment Situation) und FOMC-
Ankündigungen deutlich mehr als an anderen Tagen (1958-2009: ~11 bp vs. ~1 bp).
Daten: Veröffentlichungstermine aus den BLS-Archivseiten (Employment Situation, CPI; ab 2002-07,
data_cache/bls_release_dates.json), FOMC-Entscheidungstage (anomalies.fomc_decision_days); SPY
Yahoo adjclose bis 2026-09-25 (data_cache/yahoo_unseen).
Regel: S&P 500 (SPY/Future) nur an Ankündigungstagen halten (Kauf zum Vortagesschluss, Verkauf zum
Schluss des Ankündigungstags); sonst Cash (T-Bill). Kosten 1 bp je Seite.
Kennzahl: Überrendite (über T-Bill) je Ankündigungstag. Zeiträume: 2002-07..2012 (vor
Veröffentlichung, berichtet), 2013..2025-09-19 (nach Veröffentlichung), unberührtes Jahr.
1 Familie. Bestehen: Ø Überrendite je Ankündigungstag mit t >= 2 für 2013-2025 UND Ø > 0 im
unberührten Jahr. Berichtet: je Ankündigungsart; Ø der übrigen Tage.
Ergebnis Runde 59 (Überrendite je Tag, netto 2 bp):
- 2002-07..2012: 329 Ankündigungstage Ø 7,5 bp (t 1,05), übrige Tage Ø 1,4 bp; FOMC allein 46 bp (t 3,14).
- 2013..2025: 392 Tage Ø 7,0 bp (t 1,22), übrige Tage Ø 4,9 bp; NFP 12,9 (t 1,41), CPI 5,7, FOMC 10,5.
- unberührt: 29 Tage Ø -27,9 bp (t -1,70) -> NICHT BESTANDEN.
Die Ankündigungsprämie ist nach der Veröffentlichung weitgehend verschwunden (Abstand zu übrigen
Tagen nur noch ~2 bp); die starke FOMC-Prämie vor 2013 passt zum Pre-FOMC-Drift (Runde 9), der
ebenfalls verschwand.

# Runde 60: Favoriten-Außenseiter-Verzerrung auf Polymarket (2026-09-27)

Hypothese (Wettmärkte, u.a. Thaler & Ziemba 1988; Snowberg & Wolfers 2010): Außenseiter sind zu
teuer, Favoriten zu billig. Daten: Polymarket Gamma-API (geschlossene, eindeutig aufgelöste Ja/Nein-
Märkte, Volumen >= 50.000 USD) und CLOB-Preisverlauf (Tagesauflösung).
Regel: 7 Tage vor Schluss (closedTime) Preis q des Favoriten (= max(p_ja, 1-p_ja)); kaufen, wenn
0,80 <= q <= 0,97; Einstieg zu q + 0,01 (Spread/Schlupf); Auszahlung 1 bei Gewinn.
Rendite je Trade = 1/(q+0,01) - 1 bzw. -1. Märkte desselben Ereignisses (Gamma "events") werden zu
EINEM Ereignis-Mittelwert zusammengefasst (korrelierte Ausgänge); t über Ereignisse.
Zeiträume nach Schlussdatum: 2023-01..2024-12 (Entdeckung), 2025-01..2025-09-19 (Bestätigung),
2025-09-22..2026-09-25 (unberührt). Berichtet: Kalibrierung (Trefferquote vs. Preis je Klasse).
Bestehen (1 Familie): Ø Rendite je Ereignis t >= 2 in Entdeckung UND Bestätigung UND Ø > 0 unberührt.
Umsetzbarkeit DE (nicht simuliert): Polymarket-Zugang/Rechtslage aus Deutschland prüfen; Einsatz in
USDC (Krypto), Gebühren je Markt unterschiedlich.
Stand Runde 60 (unvollständig, kein Urteil):
- Erster Lauf hatte einen Paginierungsfehler (Gamma liefert max. 100 je Seite, Versatz um 500 ->
  nur jede 5. Seite; zudem Obergrenze ~2.100 Treffer je Abfrage, älteste zuerst) -> fast nur
  Märkte bis Anfang 2025. Vorläufiges Ergebnis darauf (NICHT gewertet): Kalibrierung nahezu perfekt
  (z.B. Preis 0,85 -> Trefferquote 0,84; 0,93 -> 0,95), 2023-2024 Ø Rendite je Ereignis -2,95 %
  (t -1,57, 295 Ereignisse) -- kein Favoriten-Vorteil erkennbar.
- Korrigierter Abruf monatsweise: Marktliste vollständig (45.385 Märkte 2023-01..2026-09), Preis-
  verläufe bei ~10.400 vom System wegen Speichermangel gestoppt. Fortsetzung mit
  research/scripts/r60_fetch.py (überspringt Vorhandenes), dann r60.py.
Ergebnis Runde 60 (vollständiger Abruf: 45.385 Märkte, 30.589 Preisverläufe; 22.511 Märkte mit Preis
7 Tage vor Schluss, 7.972 ohne Preis in diesem Fenster, 106 ohne Verlauf/eindeutige Auflösung):
Kalibrierung (alle Zeiträume, Preis -> Trefferquote):
0,55->0,53 | 0,65->0,61 | 0,75->0,72 | 0,85->0,81 | 0,93->0,91 | 0,96->0,95 | 0,993->0,994 (n=10.380)
- 2023-2024:      494 Ereignisse, Ø Preis 0,908, Treffer 0,893, Ø Rendite je Ereignis -5,02 % (t -3,21)
- 2025-01..09-19: 797 Ereignisse, Ø Preis 0,904, Treffer 0,882, Ø -4,98 % (t -4,14)
- unberührt:     1565 Ereignisse, Ø Preis 0,899, Treffer 0,867, Ø -5,68 % (t -6,31)
-> NICHT BESTANDEN. Auf Polymarket ist es umgekehrt: Favoriten zwischen 0,5 und 0,95 sind um
2-4 Prozentpunkte ZU TEUER, in allen drei Zeiträumen gleichgerichtet.
Nachträgliche Beobachtung (nicht vorregistriert, NICHT gewertet): Die Gegenseite (Außenseiter zu
~0,10 kaufen) hätte rechnerisch positiv abgeschnitten (unberührt grob +20 % je Ereignis vor Gebühren).
Das ist mit denselben, bereits gesehenen Daten gefunden und dürfte nur in einem echten
Vorwärtstest (Märkte, die nach 2026-09-27 schließen) gewertet werden; Liquidität/Spread bei 0,10-
Preisen und Zugang aus Deutschland sind ungeprüft.
Nachtrag: Laut Nutzer ist Polymarket in Deutschland illegal -> Prognosemärkte werden nicht weiter
verfolgt, die nachträgliche Außenseiter-Beobachtung entfällt.

# Runde 61: Gold -- Asien-Nacht und Nachmittags-Fixing (2026-09-27)

Quellen: Abrantes-Metz & Metz (2014/2018): große Kursbewegungen beim Londoner PM-Fixing
(15:00 London) 2004-2013 überwiegend nach unten; seit 2015 elektronische LBMA-Auktion (Bruch).
Verbreitete Behauptung: Gold steigt außerhalb der US-Handelszeiten (Asien-Nacht).
Daten: Dukascopy XAUUSD-Minuten (Bid), 2008-01..2025-09 im Cache; unberührt 2025-09-22..2026-09-25
wird erst NACH dieser Vorregistrierung geladen.
Familien (2 -> Schwelle t >= 2,24 in der Entdeckung):
- GA Asien-Nacht long: Kauf 18:00 New York (Wiedereröffnung nach der Tagespause), Verkauf 08:00
  London am nächsten Morgen. Nächte So->Mo bis Do->Fr; Einstieg/Ausstieg = Open der ersten Minute
  ab dem Zeitpunkt (max. 5 min später, sonst Nacht verworfen).
- GF Fixing short: Leerverkauf 14:55 London, Eindeckung 15:10 London, an jedem Werktag Mo-Fr mit
  Daten. (Umsetzung per Gold-CFD, short erlaubt.)
Kosten: 1 bp je Seite (wie Runde 20). Kennzahl: Ø Nettorendite je Trade, t = Mittel/SE.
Zeiträume: Entdeckung 2008-01..2014-12 (Fixing-Ära), Bestätigung 2015-01..2025-09-19 (Auktion),
unberührt 2025-09-22..2026-09-25.
Bestehen je Familie: Entdeckung t >= 2,24 UND Bestätigung t >= 2 UND unberührt Ø > 0 (alles netto).
Zusätzlich berichtet (nicht gewertet): Bruttowerte, Jahreswerte.
Ergebnis Runde 61 (7,89 Mio. Minuten 2008-01..2026-09-25; netto 1 bp je Seite):
- GA Asien-Nacht long: Entdeckung n 1618, Ø 6,56 bp netto (t 4,67); Bestätigung n 2581, Ø 2,83 bp
  (t 3,42); unberührt n 261, Ø 13,81 bp (t 2,09). Negative Jahre: 2014, 2018, 2022 (je > -2 bp).
  -> BESTANDEN.
- GF Fixing short: Entdeckung Ø -0,34 bp (t -0,60), Bestätigung Ø -1,40 bp (t -4,18), unberührt
  +0,52 bp -> NICHT BESTANDEN (brutto 2008-2009 positiv, danach verschwunden).
Vorbehalte vor jeder Umsetzung (-> Runde 62): (1) Gold stieg 2008-2026 stark; die Nacht könnte nur
den Gesamttrend einsammeln -> Vergleich mit der Tagessitzung. (2) Spread direkt nach der
Wiedereröffnung 18:00 NY ist breiter als 1 bp -> echte Bid/Ask-Kurse. (3) Kein Swap, da Einstieg
nach und Ausstieg vor dem Rollover 17:00 NY -- beim Broker prüfen.

# Runde 62: Robustheit Gold-Asien-Nacht (vorregistriert vor Laden der Ask-Kurse, 2026-09-27)

Gleiche Zeiträume wie Runde 61. Alle drei Prüfungen müssen bestehen:
- R1 Echte Kosten: Kauf zum ASK (Dukascopy XAUUSD Ask-Minuten, Open) 18:00 NY, Verkauf zum BID
  08:00 London, zusätzlich 0,5 bp je Seite (Broker-Aufschlag/Kommission). Bestehen: t >= 2 in
  Entdeckung UND Bestätigung, Ø > 0 unberührt.
- R2 Nicht nur Trend: je Handelstag Nachtrendite (brutto, 18:00 NY -> 08:00 London) minus
  Tagesrendite (brutto, 08:00 London -> 17:00 NY desselben Tages, Bid). Bestehen: Ø Differenz
  t >= 2 in Entdeckung UND Bestätigung, Ø > 0 unberührt.
- R3 Keine Punktlandung: 9 Varianten Einstieg {18, 19, 20 Uhr NY} x Ausstieg {07, 08, 09 Uhr
  London}, Kosten wie R1. Bestehen: alle 9 mit Ø > 0 in der Bestätigung.
Ergebnis Runde 62 (Ask-Minuten 2008-2026 geladen, 7,75 Mio.):
- R1 echte Kosten: Entdeckung Ø +0,89 bp (t 0,60), Bestätigung Ø -3,20 bp (t -3,92), unberührt
  +5,87 bp (t 0,89) -> NICHT bestanden. Dukascopy-Spread um 18:00 NY frisst die ~5 bp brutto auf.
- R2 Nacht minus Tag: 17,1 bp (t 4,56) / 5,6 bp (t 2,96) / 29,7 bp (t 2,45) -> bestanden; die
  Tagessitzung ist in allen Zeiträumen negativ (-5,8 / -1,6 / -9,7 bp). Der Effekt ist echt,
  nicht nur Trend.
- R3: alle 9 Varianten in der Bestätigung netto negativ (-1,5 bis -3,2 bp) -> NICHT bestanden.
-> Runde 62 NICHT BESTANDEN: Gold-Nachteffekt existiert (brutto), ist aber per CFD mit
Dukascopy-Spreads nicht handelbar. Nachträglich (nicht gewertet): Mit COMEX-Micro-Gold-Futures
(MGC, Tick 0,10 $ ~ 0,25 bp) wären die Kosten evtl. ~1-1,5 bp Round-Trip -- ungeprüft, keine
kostenlosen Futures-Quotes; wie beim Nikkei nur per Futures-Broker (IBKR) denkbar.
Nicht getestet (Literatur): "Overnight Drift" (Boyarchenko, Larsen & Whelan, RFS 2023; US-Aktien-
futures 02:00-03:00 ET, stärker nach Ausverkäufen) -- laut NY Fed (Liberty Street Economics,
2026-07, "The Disappearing Overnight Drift") seit 2021 im Mittel ~0. Ein weiterer Fall von
Verfall nach Veröffentlichung.

# Runde 63: Heimatstunden-Effekt im Devisenmarkt (Breedon & Ranaldo, JMCB 2013) (2026-09-27)

Befund (EBS-Daten 1997-2007): Währungen werten in ihren eigenen Handelsstunden ab (Kundenfluss
kauft Fremdwährung); EUR/USD nach Kosten profitabel (Sharpe 1,3 Morgen-Short, 0,9 Nachmittag-Long).
Alle unsere Daten (ab 2008) liegen nach der Stichprobe des Papiers.
Regel (Sitzungen laut Tabelle 1 des Papiers): je Werktag Mo-Fr
- Bein 1: Paar SHORT von 07:00 London (Europa-Eröffnung) bis 08:00 New York (US-Eröffnung),
- Bein 2: Paar LONG von 08:00 New York bis 16:00 New York.
Tagesrendite = Summe beider Beine. Familien: EUR/USD, GBP/USD (2 -> Schwelle 2,24).
Kosten: echte Dukascopy-Bid/Ask-Minuten (Short zum Bid eröffnen, zum Ask schließen; Long zum Ask
kaufen, zum Bid verkaufen) + 0,25 bp je Seite Kommission (4 Seiten je Tag). Preis = Open der ersten
Minute ab Zeitpunkt (max. 5 min später, sonst Tag verworfen).
Zeiträume: Entdeckung 2008-01..2016-12, Bestätigung 2017-01..2025-09-19, unberührt 2025-09-22..
2026-09-25. Bestehen je Familie: t >= 2,24 Entdeckung UND t >= 2 Bestätigung UND Ø > 0 unberührt.
Zusätzlich berichtet: Brutto (Bid) je Bein.
Ergebnis Runde 63 (Ask-Minuten EUR/USD, GBP/USD 2008-2026 geladen):
- EUR/USD: Entdeckung Ø 2,62 bp netto (t 1,85), Bestätigung 1,51 bp (t 1,66), unberührt -2,15 bp
  (t -1,16). Brutto beide Beine weiter positiv (2008-2016 +2,9/+1,5 bp, 2017-2025 +1,7/+1,3 bp),
  aber schwächer als 1997-2007 und seit 2024 negativ.
- GBP/USD: 0,69 (t 0,55) / 0,51 (t 0,47) / -1,88 bp.
-> NICHT BESTANDEN. Richtung des Papiers hält brutto 2008-2025, nach Kosten zu schwach; im
unberührten Jahr verschwunden.
Gelesen, nicht testbar: Zhao (arXiv 2608.03703, 2026-08) "Preying on Leveraged ETFs" -- koreanische
Einzelaktien-LETFs seit 2026-05 (Samsung, SK Hynix), Umkehr nach dem Schluss; zu kurz, nicht
zugänglich. arXiv 2609.12227 (Rohstoff-Saisonalität 2016-2024 mit Kosten): kein Vorteil ggü.
Gleichgewicht nach Holm-Korrektur -- bestätigt Runde 58.

# Runde 64: Intraday-Momentum am Nikkei (Baltussen, Da, Lammers & Martens, JFE 2021) (2026-09-27)

Mechanismus: Gamma-Absicherung von Options-Market-Makern -> Rendite des Tages bis 30 min vor
Schluss setzt sich in den letzten 30 min fort (in ~60 Futures-Märkten). US (Runde 1) und DAX
(Runde 42) nicht bestanden; Japan war bisher zweimal die Ausnahme -> ein fairer Einzeltest.
Daten: Dukascopy JPNIDXJPY (Nikkei-CFD, Bid) 2013-2025-09 + unberührtes Jahr (neu zu laden).
Regel: Schluss S = OSE-Tagessitzung (15:15 JST bis 2024-11-04, 15:45 JST ab 2024-11-05).
Signal = Vorzeichen(Kurs S-30min heute / Kurs S am Vortag - 1); Position in Signalrichtung von
S-30min bis S (long und short, CFD/Micro-Future). Nur japanische Handelstage mit Kurs zu allen drei
Zeitpunkten (max. 5 min Toleranz). Kosten 0,75 bp je Seite.
Zeiträume: Entdeckung 2013-2019, Bestätigung 2020-2025-09-19, unberührt 2025-09-22..2026-09-25.
1 Familie, keine Varianten. Bestehen: t >= 2 in beiden Zeiträumen UND Ø > 0 unberührt (netto).
Ergebnis Runde 64: Entdeckung n 1546, Ø 1,14 bp netto (brutto 2,64), t 1,79; Bestätigung n 1418,
Ø 1,07 bp (brutto 2,57), t 1,42; unberührt Ø -2,51 bp (t -1,28) -> NICHT BESTANDEN. Brutto
schwach positiv wie im Papier, aber zu klein für Kosten; im unberührten Jahr negativ.

# Runde 65: Bitcoin "10-Uhr-Dump" zur US-Börseneröffnung (2026-09-27)

Behauptung (Medien/Trader 2025-2026, u.a. "Jane Street"-These): BTC fällt in der ersten Stunde des
US-Aktienhandels; Mechanismus angeblich ETF-Flüsse seit den Spot-Bitcoin-ETFs (2024-01-11).
Kennzahlen dort nur aus Nov. 2025-Feb. 2026 (Bärenphase) -> genau dort ansetzen ist Datenschnüffelei;
daher Test über die ganze ETF-Ära plus Kontrolle vor den ETFs.
Daten: Binance BTCUSDT 1-Minuten-Kerzen (data.binance.vision, kostenlos).
Regel: an US-Werktagen (Mo-Fr, NYSE-Feiertage aus der Liste unten ausgenommen) BTC SHORT von 09:30
bis 10:30 New York (Open der Minute). Kosten 5 bp je Seite (CFD/Krypto-Future für DE-Privatanleger).
Zeiträume: Entdeckung 2024-01-11..2025-06-30 (ETF-Ära, bevor das Muster populär wurde), Bestätigung
2025-07-01..2026-09-25 (enthält den Medienzeitraum -> Bestätigung ist hier weniger streng).
Kontrolle (berichtet, nicht gewertet): 2020-01..2024-01-10 (vor ETFs).
1 Familie. Bestehen: t >= 2 in Entdeckung UND Bestätigung (netto).
NYSE-Feiertage: aus Yahoo-SPY-Handelstagen abgeleitet (Werktage ohne SPY-Kurs entfallen).
Ergebnis Runde 65 (Binance BTCUSDT 1m 2020-01..2026-09-25):
- Kontrolle vor ETF 2020-2024-01: brutto -0,27 bp (short), netto -10,3 bp.
- Entdeckung 2024-01-11..2025-06: n 367, brutto +2,85 bp, netto -7,15 bp (t -1,27).
- Bestätigung 2025-07..2026-09: n 312, brutto +2,80 bp, netto -7,20 bp (t -1,33); Short-Trefferquote
  51-53 %. Halbjahre brutto stark schwankend (2026-H1 +11,5 bp, 2026-H2 -25,2 bp).
-> NICHT BESTANDEN. Der "10-Uhr-Dump" ist brutto kaum messbar (~3 bp bei ~70 bp Stunden-Vola)
und nach Kosten klar negativ; die Medienzahlen stammen aus einem ausgewählten Bärenmarkt-Fenster.

# Runde 66: US-Feiertagseffekt im Devisenmarkt (Ranaldo 2009; Breedon & Ranaldo 2013, Fußnote 6) (2026-09-27)

Mechanismus: Inländer kaufen in ihren Arbeitsstunden Fremdwährung (Runde 63). An US-Feiertagen, an
denen Europa arbeitet, fehlt der US-Fluss -> USD wertet auf (Fußnote: USD stieg ggü. EUR am
4. Juli in 15 von 20 Jahren).
Feiertage (nach Regel berechnet, nur wenn Europa geöffnet): MLK (3. Mo Jan), Presidents Day
(3. Mo Feb), Memorial Day (letzter Mo Mai), Juneteenth (19.6., Sa->Fr, So->Mo; ab 2022), Independence
Day (4.7., gleiche Verschiebung), Labor Day (1. Mo Sep), Thanksgiving (4. Do Nov). Tage, an denen
laut SPY-Kalender doch gehandelt wurde, entfallen (Plausibilitätsprüfung).
Regel: USD long = Paar SHORT von 07:00 London bis 16:00 New York am Feiertag. Echte Dukascopy-
Bid/Ask-Minuten (Short zum Bid, Eindeckung zum Ask) + 0,25 bp je Seite.
Familien: EUR/USD, GBP/USD (2 -> 2,24). Zeiträume: Entdeckung 2008-2016, Bestätigung 2017-2025-09-19,
unberührt 2025-09-22..2026-09-25 (nur ~6 Feiertage, Vorzeichen). Bestehen: t >= 2,24 / >= 2 / Ø > 0.
Wenige Beobachtungen (~7 je Jahr) -> geringe Teststärke, vorab bekannt.
Ergebnis Runde 66 (118 Feiertage 2008-2026; EUR/USD 2008-2016 nur 36 mit Ask-Kurs):
- EUR/USD: Entdeckung Ø 12,3 bp netto (t 1,87, 64 % Treffer); Bestätigung -0,3 bp (t -0,09);
  unberührt -7,2 bp (7 Tage).
- GBP/USD: Entdeckung Ø 16,2 bp (t 2,34); Bestätigung -4,0 bp (t -1,01); unberührt -10,4 bp.
-> NICHT BESTANDEN. Bis 2016 deutlich (passt zum Papier), seit 2017 verschwunden -- wieder Verfall
nach Veröffentlichung (2013).

# Runde 67: Japanischer Monatswechsel (Ziemba 1991) am Nikkei (2026-09-27)

Befund (Ziemba 1991, Japan and the World Economy, Daten bis 1988): In Japan liegt der Monatswechsel-
Effekt auf den Handelstagen -5 bis +2 (Tag -1 = letzter Handelstag); Gehälter werden am 25. gezahlt.
Daten: Yahoo ^N225 (Kursindex) 1993-01..2026-09-24 (Tagesschlüsse).
Regel: Tagesrenditen (Schluss/Schluss) der Handelstage -5..-1 und +1..+2 eines jeden Monats = TOM-
Tage; alle übrigen = Rest. Kennzahl: Ø Tagesrendite TOM minus Ø Rest (Welch-t). Umsetzung: long
Micro-Nikkei vom Schluss des Tages -6 bis Schluss Tag +2 (1 bp je Seite ~ 0,25 bp je TOM-Tag,
von der TOM-Rendite abgezogen).
Zeiträume: Entdeckung 1993-2008, Bestätigung 2009-2025-09-19, unberührt 2025-09-22..2026-09-24.
1 Familie. Bestehen: Welch-t >= 2 in Entdeckung UND Bestätigung UND Differenz > 0 unberührt.
Berichtet: TOM-Strategie p.a. vs Halten.
Ergebnis Runde 67: Entdeckung 1993-2008 TOM Ø 10,4 bp vs Rest -6,3 bp, Diff 16,6 bp (t 3,28);
Bestätigung 2009-2025 TOM 1,7 bp vs Rest 6,4 bp, Diff -4,7 bp (t -1,06); unberührt Diff +9,8 bp
(t 0,41) -> NICHT BESTANDEN. Stark bis 2008, danach verschwunden.

# Überprüfung früherer Runden (2026-09-27, auf Wunsch des Nutzers)

Durchgesehen: alle "nicht getestet / keine Daten / ungeprüft"-Vermerke. Ergebnis:
- Pre-EZB-Drift (Runde 52: "Termine nicht abrufbar"): EZB-Termine jetzt per Browser von
  ecb.europa.eu (Jahreslisten 2000-2026, "Monetary policy decisions") -> Runde 68.
- Nikkei-Nachteffekt mit echten OSE-Auktionskursen: JPX-Historie kostenpflichtig (auch Nikkei-
  Datensatz, Barchart nur 1 Download/Tag) -> bleibt offen; CFD-Kurse leiten sich vom Future ab.
- Gold per COMEX-Micro-Future (Runde 62), DAX per FDXS (Runde 41): keine kostenlosen
  Futures-Quotes -> offen.
- Aus der Quantpedia-Warteschlange nie getestet: REIT-Momentum, FED-Modell (beide Monats-
  Allokation, kein Day-Trading, niedrige Priorität).
- Stooq (lange Historien) war per Automatisierung blockiert; per Browser lesbar, aber bisher kein
  Test, der davon abhängt.

# Runde 68: Pre-EZB-Drift am DAX (2026-09-27)

Analog Lucca & Moench (2015) für die Fed; Brusa, Savor & Wilson (2020) fanden KEINEN Pre-EZB-Drift
(Erwartung daher: nicht bestanden). Termine: ecb.europa.eu, geplante und Sondersitzungen mit
Zinsentscheid (Liste "Monetary policy decisions"; 2016-12-08 fehlt dort und wird ergänzt).
Regel: DAX-CFD long vom Xetra-Schluss 17:30 Berlin am Vortag bis 5 min vor der Bekanntgabe am
Sitzungstag (13:40 bis 2021, 14:10 ab 2022). Daten: Dukascopy DEUIDXEUR-Minuten (ab 2013-09-30).
Kosten: 1,5 Punkte Round-Trip + 1 bp Übernacht-Finanzierung.
Zeiträume: Entdeckung 2013-10..2019, Bestätigung 2020..2025-09-19, unberührt 2025-09-22..2026-09-25.
Berichtet zum Vergleich: gleiche Zeitfenster an allen anderen Tagen (Kontrolle).
1 Familie. Bestehen: t >= 2 in Entdeckung UND Bestätigung, Ø > 0 unberührt (netto).
Ergebnis Runde 68 (89 von 109 Sitzungen mit Kursen zu beiden Zeitpunkten):
- Entdeckung 2013-10..2019: n 35, Ø 15,7 bp netto (t 1,94, 63 % Treffer); Kontrolle (alle anderen
  Tage, gleiches Fenster) 2,6 bp.
- Bestätigung 2020..2025-09: n 46, Ø -24,0 bp (t -1,38); Kontrolle 2,2 bp.
- unberührt: n 8, Ø -48,9 bp; Kontrolle 4,2 bp.
-> NICHT BESTANDEN (wie Brusa, Savor & Wilson 2020 erwarten lassen). Die Lücke aus Runde 52 ist
damit geschlossen.

# Runde 69 (beschreibend): Kopieren erfolgreicher Anleger -- echte Kopier-ETFs (2026-09-27)

Frage des Nutzers: Trades sehr erfolgreicher Trader kopieren. Bereits getestet: Insiderkäufe
(Runde 11, unter SPY), 13F-"beste Ideen" der Hedgefonds (Runde 51, Alpha ~0). Hier die
Echtgeld-Bilanz von ETFs, die genau das umsetzen (Yahoo adjclose, Alpha ggü. SPY mit Beta):
- NANC (kopiert gemeldete Trades demokratischer Kongressabgeordneter, ab 2023-02-07, 3,6 J):
  22,8 % p.a. vs SPY 20,3 %, Beta 1,07, Alpha +0,9 % p.a. (t 0,36) -> nicht signifikant (Tech-Übergewicht).
- KRUZ (republikanische Abgeordnete): bei Yahoo delistet (Fonds geschlossen).
- GURU (Top-Positionen von Hedgefonds aus 13F, ab 2012-06, 14,3 J): 12,1 % p.a. vs SPY 15,4 %,
  Beta 1,03, Alpha -2,9 % p.a. (t -1,37).
Literatur Echtzeit-Kopieren (eToro u.a.): Kopierer schneiden schlechter ab als die Vorbilder;
Ranglisten erhöhen Risiko und Herdenverhalten; Popularität folgt nur teilweise der Leistung.
Außerdem: US-ETFs (NANC, GURU) für DE-Privatanleger wegen PRIIPs nicht kaufbar.
Fazit: Kein Kopieransatz mit öffentlich verfügbaren Meldungen schlägt den Markt nach Kosten;
Meldeverzug (13F 45 Tage, Kongress bis 45 Tage) nimmt den Informationsvorsprung vorweg.

# Runde 70: Ranglisten-Kopieren auf Hyperliquid -- halten Top-Verdiener ihren Vorsprung? (2026-09-27)

Frage des Nutzers: Trades der Top-Verdiener einer Plattform in Echtzeit automatisch kopieren.
Hyperliquid (On-Chain-Perp-Börse) veröffentlicht Positionen, Fills und PnL-Historie ALLER Konten.
Notwendige Bedingung fürs Kopieren: Top-Verdiener einer Periode verdienen auch in der nächsten.
Daten: stats-data.hyperliquid.xyz Leaderboard (46.957 Konten, inkl. Verlierer; Stand 2026-09-27);
Universum = Konten mit Gesamtvolumen >= 100 Mio. USD (7.011). Je Konto info/portfolio "perpAllTime":
pnlHistory + accountValueHistory (~wöchentlich seit Kontoeröffnung).
Regel: Formationsstichtage alle 28 Tage ab 2025-01-01 bis 2026-08-30. Je Stichtag T: PnL im Fenster
[T-28 T] und [T, T+28] je Konto (lineare Interpolation der kumulierten PnL-Historie auf die
Stichtage; nur Konten mit Historie über beide Fenster und Kontowert >= 100.000 USD bei T-28 und T).
Rendite = PnL / Kontowert bei Fensterbeginn.
Gruppen: G1 Top 20 nach absoluter PnL in [T-28, T] (wie die Rangliste), G2 Top 20 nach Rendite.
Kennzahl je Stichtag: Ø Folgerendite der Gruppe minus Median-Folgerendite aller Konten.
Zeiträume: Entdeckung Stichtage 2025, Bestätigung Stichtage 2026.
Bestehen (2 Gruppen -> 2,24): Ø Überschuss t >= 2,24 in 2025 UND t >= 2 in 2026 UND Ø Folgerendite
der Gruppe > 0. Vorbehalte (vorab): Konten ohne Leaderboard-Eintrag fehlen (Rest-Survivorship);
Market-Maker mit stetiger PnL sind nicht kopierbar -- berichtet: Anteil Konten mit Volumen/Kontowert
> 1.000 in den Gruppen. Kopierkosten (Verzögerung, Gebühren) nicht abgezogen -> Obergrenze.
Gesichtet, nicht getestet: CME-Bitcoin-Gap-Fill ("77 % schließen binnen einer Woche") -- seit
Mai 2026 handelt CME Bitcoin-Futures rund um die Uhr, die Wochenend-Gaps existieren nicht mehr.

# Runde 71: Spot-Bitcoin-ETF-Flüsse sagen die BTC-Rendite des Folgetags voraus (2026-09-27)

Quelle: Lim (SSRN 6592830): tägliche Nettoflüsse der US-Spot-BTC-ETFs erklären 21 % der Tages-
renditen und sagen die Folgetagsrendite voraus (Stichprobe 2024-01..2025-04, 313 Tage).
Daten: Farside Investors "Bitcoin ETF Flow -- All Data" (Spalte Total, Mio. USD, US-Handelstage;
per Browser). Kurse: Binance BTCUSDT 1m (Runde 65).
Regel (handelbar, Veröffentlichung abwarten): Fluss F am US-Handelstag t; Position ab 14:00 UTC am
Kalendertag t+1 für 24 h: long wenn F > 0, short wenn F < 0 (Perp/CFD). Kosten 5 bp je Seite.
Zeiträume: Entdeckung 2024-01-11..2025-04-30 (Stichprobe des Papiers), Bestätigung 2025-05-01..
2026-09-25 (nach der Stichprobe). 1 Familie. Bestehen: t >= 2 in beiden Zeiträumen (netto).
Berichtet: nur große Flüsse (|F| > 200 Mio.), Korrelation F mit gleichzeitiger Rendite.
Ergebnis Runde 71 (695 Flusstage 2024-01-11..2026-09-25): Fluss korreliert mit der GLEICHZEITIGEN
Rendite der US-Sitzung (r = 0,27), aber nicht mit der handelbaren Folgeperiode:
- Entdeckung: n 326, Ø netto 5,3 bp (brutto 15,3), t 0,42, Treffer 52 %; |F|>200: t 0,20.
- Bestätigung: n 352, Ø netto 2,0 bp, t 0,18, Treffer 46 %; |F|>200: t 0,52.
-> NICHT BESTANDEN. Die "Vorhersage" des Papiers entsteht vermutlich aus Überlappung von
Flussmeldung und Kursbewegung (Flüsse folgen dem Kurs), nicht aus handelbarer Information.
Ergebnis Runde 70 (7.011 Konten geladen, 22 Stichtage 2025-01..2026-08, Ø 785 Konten je Stichtag
mit Kontowert >= 100.000 USD; Median-Folgerendite aller Konten -1,3 % je 28 Tage):
- G1 Top 20 nach PnL (wie Rangliste): Formationsrendite Ø +135 % / +96 %; Folgerendite 2025
  Ø +17,1 % (Überschuss 19,4 %, t 2,02), 2026 Ø -63,3 % (Überschuss -63,8 %, t -1,43).
- G2 Top 20 nach Rendite: Formation Ø +356 % / +280 %; Folgerendite 2025 +7,6 % (t 0,92), 2026
  -2,7 % (t -0,36).
-> NICHT BESTANDEN (beide Gruppen). Die Top-Verdiener behalten ihren Vorsprung nicht; 2026 erlitten
die Top-20 nach PnL im Folgemonat im Mittel -63 % (Großverluste einzelner, hoch gehebelter Konten).
27 % (G1) bzw. 74 % (G2) der Gruppenkonten haben Volumen/Kontowert > 1.000 (Market-Maker/HFT-artig,
ohnehin nicht kopierbar). Kopierkosten nicht abgezogen -- real noch schlechter.

# Runde 72: Vortagesrendite des S&P 500 -> Nikkei-Intraday (Umkehr früh, Momentum spät) (2026-09-27)

Quelle: "How the prior day's S&P 500 returns influence the intraday returns of Nikkei 225 futures"
(ScienceDirect S3050700626000204, 2026; nur Zusammenfassung gelesen, Volltext hinter Captcha):
höhere S&P-Vortagesrendite -> niedrigere Rendite in den ersten 30 min, höhere in den letzten 30 min.
Unsere Daten 2013-2025 liegen vermutlich in der Stichprobe des Papiers; echt neu ist nur das
unberührte Jahr.
Daten: Dukascopy JPNIDXJPY-Minuten (wie Runde 64); S&P-Signal = SPY Schluss/Schluss des letzten
US-Handelstags VOR dem Tokio-Datum (Yahoo adjclose).
- HA Früh-Umkehr: Position -Vorzeichen(S&P) von 08:45 bis 09:15 JST.
- HB Spät-Momentum: Position +Vorzeichen(S&P) von S-30min bis S (S = 15:15 bis 2024-11-04,
  15:45 ab 2024-11-05).
Kosten 0,75 bp je Seite. Zeiträume: Entdeckung 2013-2019, Bestätigung 2020-2025-09-19, unberührt
2025-09-22..2026-09-25. 2 Familien -> Bestehen je Familie: t >= 2,24 / >= 2 / Ø > 0 (netto).
Ergebnis Runde 72:
- HA Früh-Umkehr 08:45-09:15: Entdeckung n 650 (CFD-Kurse um 08:45 erst ab ~2016 lückenlos),
  Ø 0,90 bp netto (t 0,70); Bestätigung n 1341, Ø 1,98 bp (t 2,02); unberührt -2,42 bp -> NICHT BESTANDEN.
- HB Spät-Momentum: -1,17 (t -1,84) / -0,24 (t -0,31) / -0,45 bp -> NICHT BESTANDEN.
Brutto beide Richtungen wie im Papier nur 1-3 bp; nach Kosten und im unberührten Jahr nichts.

# Runde 73: Monatsend-Rendite von US-Staatsanleihen (Hartley & Schwarz 2019) (2026-09-27)

Befund (1990-2018): Die gesamte Laufzeitprämie fällt in den letzten Handelstagen des Monats an
(10 Jahre, letzte 3 Tage: +0,25 % je Monat, Sharpe ~1); Ursache Index-Rebalancing/Window-Dressing
(Lebensversicherer kaufen am Index-Stichtag). Veröffentlicht 2019 -> 2019-2026 ist echt neu.
Regel: IEF (7-10 J., Yahoo adjclose) long vom Schluss des 4.-letzten bis Schluss des letzten
Handelstags des Monats (= Renditen der letzten 3 Handelstage). Überrendite = Rendite minus T-Bill
(FRED TB3MS, anteilig je Kalendertag). Kosten 1 bp je Seite (Umsetzung DE: 10Y-T-Note-Future
über IBKR, günstiger). Kennzahl je Monat: Überrendite im Fenster; zusätzlich übrige Tage.
Zeiträume: Replikation 2003-2018 (Stichprobe des Papiers, nur berichtet), Bestätigung
2019-01..2025-09-19 (nach Veröffentlichung), unberührt 2025-09-22..2026-09-25.
1 Familie. Bestehen: Bestätigung t >= 2 UND unberührt Ø > 0 (netto). Berichtet: TLT (20+ J.).
Ergebnis Runde 73 (Monatsende = letzte 3 Handelstage, netto 2 bp je Monat):
- IEF: 2003-2018 Ø +17,3 bp je Monat (t 3,65, 62 % positiv; übrige Tage +8,1 bp);
  Bestätigung 2019-2025-08 (nach Veröffentlichung) Ø +22,3 bp (t 3,00, 61 %; übrige Tage -35,8 bp);
  unberührt 2025-09..2026-08 (12 Monate) Ø -12,1 bp (t -0,81, 42 % positiv).
- TLT: +35,7 (t 3,74) / +33,2 (t 2,23) / -50,3 bp (t -1,62).
Korrektur vor dem Urteil: Erster Lauf zählte den unvollständigen Monat 2026-09 (Daten bis 09-25,
Monatsende noch nicht erreicht) und ließ 2025-09 (Monatsende nach dem 19.09. = unberührt) weg; oben
die korrigierte Abgrenzung.
-> NICHT BESTANDEN (unberührtes Jahr negativ). Aber: stärkster Nach-Veröffentlichungs-Befund
außerhalb Japans (t 3,00 über 80 Monate nach 2019, Mechanismus Index-Rebalancing belegt). Das
unberührte Jahr ist mit 12 Beobachtungen schwach aussagekräftig -> Kandidat für den Vorwärtstest
(monatlich, 3 Tage, per 10Y-T-Note-Future oder UCITS-Treasury-ETF).

# Runde 74: Monatsend-Effekt bei Euro-Staatsanleihen (unabhängiger Markt, gleicher Mechanismus) (2026-09-27)

Mechanismus wie Runde 73: Rentenindizes (Bloomberg Euro Treasury, iBoxx) werden am letzten Handels-
tag des Monats umgestellt; Indexfonds/Versicherer kaufen Duration. Unabhängiger Markt, direkt aus DE
handelbar (UCITS-ETF oder Bund-Future).
Daten: Yahoo SXRQ.DE (iShares EUR Govt Bond 7-10yr, thesaurierend, Xetra) ab 2009-12; berichtet
zusätzlich EXX6.DE (Bund 10,5+ J.). Überrendite ggü. FRED IR3TIB01EZM156N (3M-Euro-Zins).
Regel wie Runde 73: letzte 3 Handelstage des Monats long, 2 bp je Monat Kosten.
Zeiträume: Entdeckung 2010-01..2018-12, Bestätigung 2019-01..2025-08, unberührt 2025-09..2026-08.
1 Familie. Bestehen: t >= 2 Entdeckung UND t >= 2 Bestätigung UND Ø > 0 unberührt (netto).
Ergebnis Runde 74:
- SXRQ.DE (EUR 7-10 J.): 2010-2018 Ø +12,9 bp je Monat (t 3,00, 65 %); 2019-2025-08 Ø +7,5 bp
  (t 1,03, 54 %); unberührt +7,2 bp (t 0,57, 58 %) -> NICHT BESTANDEN.
- EXX6.DE (Bund 10,5+): +34,1 (t 3,65) / +16,9 (t 1,35) / +4,6 bp.
In allen Zeiträumen positiv, seit 2019 aber schwächer und nicht signifikant. Zusammen mit Runde 73:
Der Monatsend-Effekt bei Staatsanleihen ist in zwei unabhängigen Märkten vorhanden, aber seit etwa
2019 (EUR) bzw. im letzten Jahr (USD) schwächer -- kein Kandidat nach den Kriterien.

# Runde 75: Aufnahme in den Nikkei 225 -- Nachfragedruck zwischen Ankündigung und Stichtag (2026-09-27)

Mechanismus (Hanaeda & Serita; Okada, Isagawa & Fujiwara 2006 "temporary demand effect of index
arbitrageurs"): Nikkei-225-Indexfonds (sehr groß, preisgewichteter Index) müssen neue Titel zum
Schlusskurs vor dem Stichtag kaufen. Aus DE handelbar: japanische Einzelaktien über IBKR (long).
Ereignisse: alle ordentlichen Überprüfungen laut Nikkei-Pressemitteilungen (indexes.nikkei.co.jp,
Newsroom 2005-2026, PDFs; 2024/2025 als Bild-PDF -> Namen aus ja.wikipedia + Nikkei-Meldungen).
Nur Neuaufnahmen aus Liquiditäts-/Sektorgründen; ausgeschlossen: Nachfolge-Holdings nach Fusion
(Weiterführung), außerordentliche Ersetzungen wegen Delisting/Fusion (2011-08, Rohm, Ibiden, ...),
2026-09 (Stichtag noch nicht erreicht). Aktien ohne Yahoo-Daten (delistet) fallen weg.
Regel: Kauf zum Eröffnungskurs des ersten Handelstags NACH der Ankündigung (Mitteilung nach
Börsenschluss), Verkauf zum Schlusskurs des letzten Handelstags VOR dem Stichtag. Überrendite =
Aktie minus ^N225 im selben Fenster (Open->Close). Kosten 20 bp Round-Trip.
Zeiträume: Entdeckung Ankündigungen 2005-2016, Bestätigung 2017-2026-03. Bestehen: Ø Überrendite je
Ereignis t >= 2 in beiden (über Ereignisse). Berichtet: Umkehr vom Stichtag bis +10 Handelstage.
Ergebnis Runde 75 (40 Aufnahmen mit Yahoo-Daten; ohne Daten: 4795, 8815):
- Entdeckung 2005-2016: n 14, Ø Überrendite ggü. ^N225 netto +2,79 % je Ereignis (t 0,82, 64 %
  positiv); Umkehr in den 10 Handelstagen nach dem Stichtag Ø -6,40 %.
- Bestätigung 2017-2026-03: n 26, Ø -0,89 % (t -0,68, 54 %); Umkehr +1,35 %.
-> NICHT BESTANDEN. Seit 2017 kein Vorlauf mehr zwischen Ankündigung und Stichtag -- der Nachfrage-
effekt wird offenbar vorab gehandelt (Kandidaten werden von Brokern Wochen vorher prognostiziert).
Hinweis: 2005 Stichtage aus dem uneinheitlichen PDF-Layout einheitlich 27.09. angenommen.

# Runde 76: Leerverkauf zum Ablauf der IPO-Haltefrist (Lockup) (2026-09-27)

Nutzerwunsch: Short-Strategien. Befund (Field & Hanka 2001; Brav & Gompers 2003): um den Ablauf der
Insider-Haltefrist (meist 180 Kalendertage nach dem IPO) fallen die Kurse um 1-3 % (Angebotsüberhang).
Umsetzung DE: Leerverkauf US-Aktien über IBKR (Leihe nötig) oder Aktien-CFD.
Daten: Nasdaq-IPO-Kalender (api.nasdaq.com, "priced", monatlich 2016-01..2025-02), Alpaca-Tagespanel
(inkl. delisteter Titel, bis 2025-09-19), SPY.
Filter: Emissionsvolumen >= 50 Mio. USD; keine SPACs/Fonds (Name enthält Acquisition, Merger, SPAC,
Capital Corp, Trust, Fund, Units). Erster Handelstag = erster Panel-Tag ab Preisdatum (max. 5 Tage
später, sonst verworfen). Stichtag E = erster Handelstag ab (erster Handelstag + 180 Kalendertage).
Regel: short vom Schluss E-5 bis Schluss E+5 (Handelstage). Überrendite = -(Aktie - SPY). Nur
Einstiegskurs >= 5 USD und Ø-Dollarvolumen der 20 Vortage >= 1 Mio. USD.
Kosten: 20 bp Round-Trip + Leihgebühr 0,5 % je Trade (~18 % p.a. für 10 Tage, IPO-typisch hoch).
Zeiträume: IPO 2016-2019 (Entdeckung), IPO 2020-2025-02 (Bestätigung). 1 Familie.
Bestehen: Ø Überrendite netto t >= 2 in beiden Zeiträumen (Ereignisse; zusätzlich berichtet:
t über Monatsmittel wegen Häufung).
Ergebnis Runde 76 (1.715 IPOs nach Filter, 650 Ereignisse mit Panel-Daten und Liquidität):
- IPO 2016-2019: n 256, Ø Short-Überrendite netto +2,38 % (brutto 3,08 %), t 2,91; über Monats-
  mittel nur t 1,09 (42 Monate, Häufung); 59 % positiv, Median +1,48 %.
- IPO 2020-2025-02: n 394, Ø -1,13 % (brutto -0,43 %), t -1,59; Monats-t -1,01; 46 % positiv.
-> NICHT BESTANDEN. Bis 2019 wie in der Literatur, seit dem IPO-Boom 2020/21 verschwunden bzw.
umgekehrt (erwartete Verkäufe vorab eingepreist, teils frühere Lockup-Freigaben).

# Runde 77: Leerverkauf neu gelisteter Krypto-Token (2026-09-27)

Mechanismus: Neue Token starten mit kleinem Streubesitz und hoher voll verwässerter Bewertung;
Airdrop-/Launchpool-Empfänger und spätere Freigaben verkaufen -> Abwärtsdrift nach dem Listing
(verbreitete Beobachtung 2024-2025). Umsetzung: Perp-Short (Hyperliquid/Bybit), Kurse hier Binance-Spot.
Daten: data_cache/crypto (Binance-Spot-Tageskerzen USDT, 662 heute gehandelte Paare; erster Tag =
Listing). Delistete Token fehlen -> Verzerrung GEGEN die Short-Strategie (konservativ).
Regel: Listingtag L >= 2020-01-01; Einstieg short zum Schluss L+1, Ausstieg Schluss L+30.
Nur wenn Quote-Volumen an L+1 >= 5 Mio. USD. Überrendite = -(Token - BTC) (marktneutral).
Kosten: 10 bp Round-Trip + Funding 3 bp je Tag (Shorts zahlen bei neuen Listings oft).
Zeiträume: Listings 2020-2023 (Entdeckung), 2024-01..2025-08-20 (Bestätigung), 2025-08-21..
2026-08-26 (unberührt). Bestehen: t >= 2 in Entdeckung UND Bestätigung, Ø > 0 unberührt.
Berichtet: reiner Short ohne BTC-Absicherung, Median, schlimmster Einzelverlust.
Ergebnis Runde 77 (408 Listings mit Liquidität; Ø / Median / Anteil positiv, netto, BTC-abgesichert):
- 2020-2023: n 227, Ø +2,5 % je Trade (t 0,30), Median +21,2 %, 74 % positiv; schlimmster -1.758 %
  (GMT 2022: Token x18).
- 2024-2025-08: n 120, Ø +9,9 % (t 1,58), Median +24,5 %, 76 % positiv; schlimmster -504 % (USUAL).
- unberührt 2025-08..2026-08: n 61, Ø +25,0 % (t 6,27), Median +25,6 %, 84 % positiv; schlimmster -73 %.
-> NICHT BESTANDEN (Entdeckung/Bestätigung t < 2). Typischer neuer Token fällt im ersten Monat
~20-25 % ggü. BTC, aber 2,9 % der Trades verlieren > 100 % (unbegrenztes Short-Risiko) und zerstören
den Mittelwert. Nur Jahre 2022 und 2024 im Mittel negativ (je ein Extremfall).
Nachträglich (NICHT gewertet): Eine Variante mit Verlustbegrenzung (Stopp, kleine gleichgewichtete
Positionen) liegt nahe, wäre aber auf gesehenen Daten gewählt -> nur als Vorwärtstest zulässig.
Offene Kostenrisiken: Funding bei gehypten Listings für Shorts teils -0,1 %/8 h und mehr (hier 3 bp/Tag
angenommen); Perp oft nicht am Listingtag verfügbar. Verzerrung durch fehlende delistete Token
spricht FÜR die Strategie (echte Ergebnisse eher besser).
Nutzerpräferenz (2026-09-27): keine Strategien mit unbegrenztem Verlustrisiko (Short neuer Listings
wird nicht weiterverfolgt).

# Runde 78: FOMC-Zyklus -- Aktienrenditen in "geraden Wochen" (Cieslak, Morse & Vissing-Jorgensen, JF 2019) (2026-09-27)

Befund 1994-2016: Die gesamte US-Aktienprämie fällt in den Wochen 0, 2, 4, 6 des FOMC-Zyklus an
(Woche 0 = Handelstage -1..+3 um die geplante Sitzung, Woche 1 = +4..+8, usw.); Erklärung:
informelle Fed-Kommunikation im Zweiwochenrhythmus. Umsetzung DE: US500-CFD/MES-Future long.
Daten: data_cache/fomc.json (geplante Sitzungen), Yahoo SPY adjclose, FRED TB3MS.
Regel: Handelstag k relativ zur letzten Sitzung (Sitzungstag = 0; der Tag vor der nächsten Sitzung
zählt als -1 der nächsten); Woche = floor((k+1)/5). Gerade Wochen (0, 2, 4, 6): SPY long, sonst Cash.
Kennzahl: Ø tägliche Überrendite gerade minus ungerade Wochen (Welch-t). Kosten vernachlässigt
bei der Kennzahl; Strategie p.a. mit 1 bp je Seite berichtet.
Zeiträume: Replikation 1994-2016 (Stichprobe des Papiers, berichtet), Bestätigung 2017-2025-09-19
(nach Veröffentlichung), unberührt 2025-09-22..2026-09-25.
1 Familie. Bestehen: Bestätigung t >= 2 UND unberührt Differenz > 0.
Ergebnis Runde 78: Replikation 1994-2016 gerade Wochen Ø 8,8 bp/Tag vs ungerade -3,5 bp (t 3,91;
Strategie 12,4 % p.a. vs SPY 9,1 % bei halber Marktzeit) -- bestätigt das Papier.
Nach Veröffentlichung 2017-2025-09: gerade 3,3 bp vs ungerade 7,8 bp (t -0,90; Strategie 4,3 % vs
SPY 15,2 %); unberührt 4,2 vs 6,3 bp (t -0,20) -> NICHT BESTANDEN. Klarer Verfall nach 2016.
Präzisierung der Nutzerpräferenz (2026-09-27): Hohes Risiko ist akzeptabel, wenn der Ertrag es
überwiegt; ausgeschlossen sind nur neue Memecoins/Listings (long wie short).

# Positionsgrößen-Analyse Gotobi + Nikkei-Nacht (beschreibend, 2026-09-27; research/scripts/sizing.py)

Handelslogik = tradingbot/forward_test.py (feature/forward-test); 2017-01..2026-09-25; Kosten wie
Vorwärtstest (Nikkei 0,5 bp/Seite + JPY-Zins; Gotobi Ask->Bid + 0,35 bp/Seite).
- Nikkei-Nacht: 1.907 Nächte, Ø 5,41 bp, Std 117 bp, schlechteste Nacht -8,56 %; Jahre 2018 -1,9 bp,
  2022 -7,0 bp, sonst positiv (2025 +13,9, 2026 +15,3). Kelly 3,9x.
- Gotobi: 699 Trades, Ø 1,06 bp, Std 17,9 bp, schlechtester -0,89 %; 2024 -1,4 bp, 2025 -3,3 bp.
  Kelly rechnerisch 33x -- wegen Schätzfehler des kleinen Mittelwerts bedeutungslos.
- Korrelation an gemeinsamen Tagen 0,03.
Hebel (Nikkei/Gotobi, Anteil des Kontos als Nominale) -> CAGR, MaxDD (doppelte Kosten):
  1x/1x 10,5 %, -27 % (7,8 %) | 1x/5x 13,6 %, -35 % (8,6 %) | 1x/10x 17,0 %, -45 % (9,1 %) |
  1,5x/10x 21,3 %, -53 % (12,0 %) | 2x/10x 24,9 %, -60 % | 3x/5x 26,0 %, -68 % | 5x/8x 27,2 %, -88 %
  | 8x/12x 0,6 %, -99 %. Rendite-Maximum bei ~3-5x Nikkei; darüber zerstört die Volatilität den Ertrag.
Bootstrap 1 Jahr: 2x/3x Median +20,7 %, P(Verlust) 28 %, P(DD < -30 %) 31 %, 5-%-Quantil -30 %.
Nachtsitzungs-Stopp -3 % beim Nikkei (Minuten-Tiefs, 5 bp Schlupf): Ø 4,82 bp, schlechteste Nacht
-3,06 %, 53 Stopps; 1x/10x 15,8 %, MaxDD -41 %; 1,5x/10x 19,6 %, -47 %. Senkt Extremtage, kaum
den MaxDD (Verlustserien statt Einzelnächte).
Einordnung: alles In-Sample-Hebelung zweier bereits geprüfter Befunde; Umsetzung erst nach
bestätigendem Vorwärtstest.
Gesichtet, nicht lesbar: SSRN 7115197 (ML-Signale und Handelsfriktionen bei Krypto) -- Cloudflare-
Prüfung, nicht umgangen.

# Runde 79: Vor-Feiertags-Effekt am Nikkei (Ziemba 1991) (2026-09-27)

Befund bis 1988: Japanische Aktien steigen am Handelstag vor Börsenfeiertagen stark. Unser Test der
anderen Ziemba-Anomalie (Monatswechsel, Runde 67) zeigte Verfall nach 2008.
Daten: Yahoo ^N225 Schlusskurse 1993-2026-09-24. Feiertag = Werktag (Mo-Fr) ohne Nikkei-Kurs;
Vor-Feiertag = letzter Handelstag davor (inkl. Jahresende 30.12. vor den Neujahrsferien).
Kennzahl: Ø Tagesrendite Vor-Feiertag minus übrige Tage (Welch-t); Kosten 2 bp je Round-Trip
(Micro-Future) von den Vor-Feiertagsrenditen abgezogen.
Zeiträume: Entdeckung 1993-2008, Bestätigung 2009-2025-09-19, unberührt 2025-09-22..2026-09-24.
1 Familie. Bestehen: t >= 2 in Entdeckung UND Bestätigung, Differenz > 0 unberührt.
Datenfehler entdeckt (vor dem Urteil zu Runde 79): Der Yahoo-Helfer (history.fetch_yahoo/_ohlc)
wandelte Zeitstempel fest in New-York-Zeit um; asiatisch-pazifische Indizes (Tagesstempel 09:00 Ortszeit
= Vorabend in NY) stehen im Cache um einen Kalendertag zu früh (Handelstage So-Do). Betroffen:
^N225 in Runden 52, 53, 67, 79. Runden 52/53 nutzen nur aufeinanderfolgende Kurse -> Ergebnis unverändert
(nur Periodengrenzen um einen Tag verschoben). Runde 67 (Lage im Monat) neu gerechnet mit Datum+1:
Entdeckung Diff 17,5 bp (t 3,45), Bestätigung -3,8 bp (t -0,86), unberührt -1,5 bp (t -0,06) ->
Urteil unverändert NICHT BESTANDEN. Helfer korrigiert (Börsenzeitzone aus den Yahoo-Metadaten);
bestehende Caches asiatischer Symbole in den Skripten mit +1 Tag behandeln.
Ergebnis Runde 79 (mit korrigiertem Datum; 13-20 Feiertage je Jahr):
- 1993-2008: Vor-Feiertag n 182, Ø +1,0 bp vs übrige -0,7 bp (t 0,14).
- 2009-2025-09: n 205, Ø -5,1 bp vs +5,3 bp (t -1,23); unberührt n 14, -19,9 bp vs +19,1 bp.
-> NICHT BESTANDEN. Der Vor-Feiertags-Effekt ist in Japan schon seit 1993 nicht mehr vorhanden.

# Runde 80: SqueezeMetrics DIX (Dark-Pool-Käufe) und GEX (Dealer-Gamma) als Marktsignal (2026-09-27)

Quelle: SqueezeMetrics-White-Papers (DIX 2017, "Short is Long"; GEX 2017, "The Implied Order Book"):
hoher DIX (Kaufdruck in Dark Pools) -> höhere S&P-Renditen in den Folgewochen; niedriges/negatives
GEX (Dealer short Gamma) -> höhere Vola, oft Tiefpunkte. Daten: squeezemetrics.com/monitor/static/
DIX.csv (kostenlos, täglich 2011-05..2026-09-25). Umsetzung DE: US500-CFD/MES-Future long.
Signale (rollierend, keine Vorausschau): Perzentil des heutigen Werts in den letzten 252 Handelstagen.
- DA DIX hoch: DIX >= 80. Perzentil -> Signal.
- DB GEX niedrig: GEX <= 20. Perzentil -> Signal.
Position: SPY long vom Schluss des Folgetags nach dem Signal für 20 Handelstage (überlappende Signale
verlängern; Engagement 1x solange ein Signal aktiv), sonst Cash (T-Bill). Kosten 1 bp je Seite.
Kennzahl: Alpha-t ggü. SPY (Überrenditen, Beta geschätzt).
Zeiträume: Entdeckung 2012-05..2017-12 (Papierzeitraum, nach 1 Jahr Vorlauf), Bestätigung 2018-01..
2025-09-19, unberührt 2025-09-22..2026-09-25. 2 Familien -> Bestehen je Familie: t >= 2,24 / >= 2 /
Alpha > 0.
Ergebnis Runde 80 (Alpha-t ggü. SPY):
- DA DIX hoch: Entdeckung Alpha -0,1 % p.a. (t -0,07; 68 % investiert), Bestätigung -0,0 % (t -0,01),
  unberührt +11,2 % (t 1,81) -> NICHT BESTANDEN. Kein Vorhersagewert über das Marktbeta hinaus.
- DB GEX niedrig: Entdeckung +4,8 % (t 2,15 < 2,24), Bestätigung -3,1 % (t -1,14), unberührt +5,0 %
  (t 0,80) -> NICHT BESTANDEN.

# Runde 81: Extreme Spekulantenpositionen (CFTC COT) als Umkehrsignal (Tornell & Yuan 2012) (2026-09-27)

Befund: Spitzen der Netto-Spekulantenposition in Devisenfutures gehen Umkehrbewegungen voraus.
Daten: CFTC Legacy Futures-only (deacot{Jahr}.zip, 2006-2026), Märkte EURO FX, JAPANESE YEN, BRITISH
POUND (CME), GOLD (COMEX). Kurse Dukascopy-Minuten (EURUSD, GBPUSD, USDJPY, XAUUSD; Bid).
Signal je Markt und Woche: Netto-Nichtkommerzielle (long - short) / Open Interest; Perzentil in den
letzten 156 Berichtswochen. >= 90. Perzentil -> Instrument SHORT (gegen die Spekulanten), <= 10. ->
LONG, sonst flach (Instrument = Fremdwährung ggü. USD bzw. Gold; bei JPY: USDJPY umgekehrt).
Zeitpunkt: Bericht mit Stand Dienstag, veröffentlicht Freitag; Einstieg Montag 07:00 UTC danach,
Halten eine Woche (Neubewertung wöchentlich). Kosten 1 bp (FX) bzw. 2 bp (Gold) je Seite bei Wechsel.
Portfolio gleichgewichtet über aktive Positionen der 4 Märkte (Tagesdurchschnitt, flach = 0).
Zeiträume: Entdeckung 2009-2016, Bestätigung 2017-2025-09-19, unberührt 2025-09-22..2026-09-25.
1 Familie. Bestehen: Wochenrendite-t >= 2 in Entdeckung UND Bestätigung, Ø > 0 unberührt.
Ergebnis Runde 81 (vor dem Urteil korrigiert: CFTC führte das Pfund bis 2021 als "BRITISH POUND
STERLING" -> Namen vereinheitlicht):
- 2009-2016: Ø -5,0 bp/Woche (t -0,72; 67 % der Wochen mit Position); Gold -10,1 bp je aktive Woche.
- 2017-2025-09: Ø -0,3 bp (t -0,05); unberührt +7,9 bp (t 0,59).
-> NICHT BESTANDEN. Gegen extreme Spekulantenpositionen zu handeln bringt nichts; bei Gold eher
Verlust (Spekulanten lagen mit Extrempositionen häufig richtig).

# Runde 82: Optionsverkauf jenseits von PutWrite -- CBOE-Strategieindizes (2026-09-27)

Runde 44 prüfte nur PUT (monatlich ATM-Puts). Hier vier weitere, bisher ungetestete Strukturen
(CBOE-Indexhistorien, cdn.cboe.com, kostenlos, Gesamtrendite inkl. T-Bill-Besicherung):
- WPUT wöchentlicher Put-Verkauf (ab 2006), BXMD Covered Call 30-Delta (ab 1986) -> gerichtet:
  Kennzahl Alpha ggü. S&P 500 TR (Yahoo ^SP500TR), Überrenditen über T-Bill.
- CNDR Iron Condor monatlich, BFLY Iron Butterfly monatlich (ab 1986, begrenztes Risiko) ->
  marktneutral gedacht: Kennzahl ebenfalls Alpha ggü. S&P 500 TR (Beta wird geschätzt).
Kosten (Indizes rechnen zu Mittelkursen): Abzug 1,0 % p.a. (monatliche Strategien) bzw. 3,0 % p.a.
(WPUT) gleichmäßig je Handelstag.
Zeiträume: Entdeckung Indexbeginn..2009, Bestätigung 2010..2025-09-19, unberührt 2025-09-22..2026-09-25.
4 Familien -> Bestehen je Familie: Alpha-t >= 2,50 Entdeckung UND >= 2 Bestätigung UND Alpha > 0
unberührt. Umsetzbarkeit DE: SPX/XSP-Optionen über IBKR (XSP = 1/10 SPX); mit 20k EUR nur XSP.
Ergebnis Runde 82 (Beginn 1993 wegen ^SP500TR bei Yahoo; nach Kostenabzug):
- WPUT: 2006-2009 Alpha 0,5 % (t 0,12); 2010-2025 1,1 % p.a. vs S&P TR 14,2 %, Alpha -7,3 % (t -5,31).
- BXMD: 1993-2009 Alpha 1,3 % (t 1,29); 2010-2025 Alpha -2,8 % (t -2,78).
- CNDR (Iron Condor): 1993-2009 7,2 % p.a., MaxDD -17 %, Alpha 2,9 % (t 1,69); 2010-2025 -1,4 % p.a.,
  Alpha -4,4 % (t -2,48); unberührt +10,8 %.
- BFLY: 1993-2009 Alpha 3,2 % (t 1,25); 2010-2025 -5,5 % p.a., MaxDD -61 %, Alpha -7,1 % (t -2,47).
-> alle NICHT BESTANDEN. Nach realistischen Kosten ist Optionsverkauf auf den S&P 500 seit 2010
klar unterlegen (Volatilitätsprämie zu klein bzw. durch Kosten und Crash-Tage aufgezehrt).

# Runde 83: Medienpessimismus (GDELT-Ton) sagt kurzfristige Aktienrenditen voraus (Tetlock 2007) (2026-09-27)

Befund (Tetlock 2007, WSJ-Kolumne 1984-1999): hoher Medienpessimismus -> fallende Kurse am Folgetag,
Umkehr innerhalb einer Woche. Daten: GDELT DOC 2.0 "timelinetone" für "stock market" (englische
Quellen), täglicher Durchschnittston 2017-01..2026-09 (kostenlos). Kurse Yahoo SPY adjclose.
Signal: Ton-z-Wert am Kalendertag t = (Ton_t - Mittel der 60 Vortage) / Std der 60 Vortage;
pessimistisch, wenn z <= -1,5. Tag t zählt zum nächsten US-Handelstag d (Ton liegt vor dessen Eröffnung
nur teilweise vor -> Position ab Schluss von d).
- NA Folgetag: nach pessimistischem Signal SPY SHORT vom Schluss d bis Schluss d+1 (CFD).
- NB Umkehr: nach pessimistischem Signal SPY LONG vom Schluss d+1 bis Schluss d+5.
Kosten 2 bp je Round-Trip. Kennzahl: Ø Rendite je Signal (t über Signale), plus Vergleich mit allen
Tagen (Kontrolle). Zeiträume: Entdeckung 2017-2021, Bestätigung 2022-2025-09-19, unberührt
2025-09-22..2026-09-25. 2 Familien -> Bestehen je Familie: t >= 2,24 / >= 2 / Ø > 0.
Runde 83 nicht durchführbar: GDELT-API sperrt unsere IP (HTTP 429) nach wenigen Anfragen; Abruf
abgebrochen, keine Daten gesehen.

# Runde 83b: Nachrichtenstimmung (SF Fed Daily News Sentiment Index) -> SPY kurzfristig (2026-09-27)

Ersatzquelle für Runde 83 (vor Sicht der Daten festgelegt): Shapiro, Sudhof & Wilson, SF Fed,
täglich 1980-01..2026-08-09 (news-sentiment-chart-1.csv). Index ist geglättet -> Signal = tägliche
Änderung D_t = S_t - S_{t-1}; z = (D_t - Mittel) / Std über die 250 Vortage; pessimistisch z <= -1,5.
Zuordnung, Regeln NA (Folgetag short) / NB (Umkehr long d+1..d+5), Kosten, Kontrolle wie Runde 83.
Wird wöchentlich veröffentlicht -> prüft Vorhersagekraft der Nachrichtenlage (Umsetzung bräuchte eigene
Echtzeit-Stimmungsmessung).
Zeiträume: Entdeckung 1993-2008, Bestätigung 2009-2025-09-19, unberührt 2025-09-22..2026-08-09.
2 Familien -> t >= 2,24 / >= 2 / Ø > 0.
Ergebnis Runde 83b (Signale ~20 je Jahr):
- NA Folgetag short: 1993-2008 Ø -11,1 bp (t -1,49), 2009-2025 Ø -15,4 bp (t -2,67), unberührt -7,2 bp
  -> NICHT BESTANDEN. Nach pessimistischen Nachrichtentagen steigt der Markt am Folgetag eher
  (umgekehrt zu Tetlock); eine Long-Regel wäre nachträglich gewählt (nicht gewertet).
- NB Umkehr long d+1..d+5: -3,4 bp (t -0,26) / +31,6 bp (t 3,00, Kontrolle alle Tage 24,0 bp) /
  -23,5 bp -> NICHT BESTANDEN (Bestätigung kaum über der Kontrolle).

# Runde 84: Maschinelles Lernen als Filter für den Nikkei-Nachteffekt (2026-09-27)

Frage: Verbessert ein streng vorwärts geschätztes Modell den robusten Nachteffekt, indem es
schlechte Nächte auslässt? (ML-Kombination schwacher Signale, auf den besten Befund angewandt.)
Nächte: Logik wie tradingbot/forward_test.nikkei_trades (Dukascopy-CFD, 0,5 bp/Seite + JPY-Zins),
2013-10..2026-09-25. Merkmale (zum Einstieg bekannt): Nikkei-Tagessitzung 08:45->Schluss, Vornacht,
SPY-Rendite des letzten US-Tages vor dem Tokio-Tag, USDJPY 05:00 JST->Schluss, VIX-Schluss des
Vortags (z über 250 Tage), Nikkei-20-Tage-Vola, Wochentag (Fr), Monatsende (letzte 2 Handelstage),
Gotobi am Folgetag. Modell: Ridge-Regression (alpha 10) auf standardisierten Merkmalen, Ziel =
Netto-Nachtrendite; jährlich neu geschätzt auf allen Vorjahren (expandierend), Vorhersagen ab 2017.
Regel: Nacht handeln, wenn Vorhersage > 0, sonst flach.
Kennzahl: tägliche Differenz (ML-gefiltert minus immer investiert), t-Wert gepaart.
Zeiträume: Walk-forward 2017-01..2025-09-19, unberührt 2025-09-22..2026-09-25.
1 Familie. Bestehen: Differenz-t >= 2 im Walk-forward UND Differenz > 0 unberührt.
Ergebnis Runde 84: Walk-forward 2017-2025-09 (1.678 Nächte, 56 % gehandelt): immer investiert Ø 3,53 bp
(Sharpe 0,51), ML-gefiltert Ø 3,28 bp (Sharpe 0,63), Differenz t -0,14; unberührt (220 Nächte, 87 %
gehandelt): 19,11 vs 15,93 bp, t -0,69 -> NICHT BESTANDEN. Der Filter senkt das Risiko etwas (höheres
Sharpe bei halber Marktzeit), verbessert den Ertrag aber nicht; die Nacht ist nicht vorhersagbar
über ihren Durchschnitt hinaus.

# Runde 85: Gotobi in EUR/JPY und AUD/JPY (Bestätigung des Mechanismus, Diversifikation) (2026-09-27)

Mechanismus Gotobi: Importeure kaufen vor dem 9:55-Fixing Fremdwährung -> Yen schwächt sich
allgemein ab; Yen-Kreuze sollten mitlaufen. Regel exakt wie Runde 49/Vorwärtstest: long 05:00 ->
09:55 JST an Gotobi-Tagen, Kauf zum Ask, Verkauf zum Bid (Dukascopy-Minuten), + 0,35 bp/Seite.
Familien: EUR/JPY, AUD/JPY (2 -> Schwelle 2,24). Zeiträume: 2017-01..2025-09-19 (Ask-Daten wie
Runde 49), unberührt 2025-09-22..2026-09-25. Bestehen je Familie: t >= 2,24 in 2017-2025 UND Ø > 0
unberührt. Berichtet: Korrelation mit USD/JPY-Gotobi-Trades.
