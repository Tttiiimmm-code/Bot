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
