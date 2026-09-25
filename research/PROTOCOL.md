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
