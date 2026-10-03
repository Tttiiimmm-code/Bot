//+------------------------------------------------------------------+
//| GoldBreakout.mq5                                                  |
//| Nachbau "The Gold Reaper" -- Regeln wie Vorwärtstest gold_breakout |
//| (Forschungsrunde 134, tradingbot/forward_gold.py). NUR DEMO.       |
//|                                                                    |
//| Zu Beginn jeder Stunde (UTC, erste 10 Minuten), wenn keine eigene  |
//| Position und keine eigene Order offen ist: Buy-Stop 0,1 ATR über   |
//| dem höchsten Hoch der letzten 48 abgeschlossenen H1-Kerzen, gültig |
//| bis 12 Stunden nach Stundenbeginn. Stop 2 ATR, Ziel 4 ATR ab       |
//| FÜLLKURS (nach der Füllung nachgezogen). ATR14 nach Wilder auf H1. |
//| Keine neuen Orders Fr ab 20:00 UTC, eigene Orders Fr ab 20:55 UTC  |
//| löschen. Risiko 1 % des Kontowerts je Trade. Jeder geschlossene    |
//| Trade wird in MQL5/Files/gold_breakout_trades.csv protokolliert.   |
//+------------------------------------------------------------------+
#property copyright "tradingbot research"
#property version   "1.00"

#include <Trade/Trade.mqh>

input double RiskPercent = 1.0;     // Risiko je Trade in % des Kontowerts
input int    LevelBars   = 48;      // Hoch der letzten N abgeschlossenen H1-Kerzen
input int    ExpiryHours = 12;      // Gültigkeit der Buy-Stop-Order (ab Stundenbeginn)
input double StopATR     = 2.0;     // Stop-Abstand in ATR
input double TargetATR   = 4.0;     // Ziel-Abstand in ATR
input double BufferATR   = 0.1;     // Puffer über dem Hoch in ATR
input long   Magic       = 134001;  // Kennung der eigenen Orders
input bool   AllowLive   = false;   // Sicherheitsschalter: Echtgeldkonto erlauben (NICHT empfohlen)

CTrade trade;
int    lastHourKey = -1;
string csvName = "gold_breakout_trades.csv";

//+------------------------------------------------------------------+
int OnInit()
  {
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_DEMO && !AllowLive)
     {
      Alert("GoldBreakout: Kein Demokonto -- EA startet nicht (AllowLive=false).");
      return(INIT_FAILED);
     }
   trade.SetExpertMagicNumber(Magic);
   EventSetTimer(30);
   Print("GoldBreakout gestartet auf ", _Symbol, ", Konto ", AccountInfoInteger(ACCOUNT_LOGIN));
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason) { EventKillTimer(); }

//+------------------------------------------------------------------+
//| Wilder-ATR(14) und Level aus abgeschlossenen H1-Kerzen            |
//+------------------------------------------------------------------+
bool SignalLevels(double &level, double &atr)
  {
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int n = CopyRates(_Symbol, PERIOD_H1, 1, 500, r);   // ab Verschiebung 1 = nur abgeschlossene Kerzen
   if(n < LevelBars + 15) return(false);
   atr = 0.0;
   for(int i = 1; i < n; i++)
     {
      double tr = MathMax(r[i].high - r[i].low,
                          MathMax(MathAbs(r[i].high - r[i-1].close), MathAbs(r[i].low - r[i-1].close)));
      if(i == 1) atr = tr;
      else       atr = atr + (tr - atr) / 14.0;
     }
   double hi = r[n-1].high;
   for(int i = n - LevelBars; i < n; i++) hi = MathMax(hi, r[i].high);
   level = hi + BufferATR * atr;
   return(atr > 0);
  }

//+------------------------------------------------------------------+
bool HasOwnPosition()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(PositionSelectByTicket(t) && PositionGetInteger(POSITION_MAGIC) == Magic &&
         PositionGetString(POSITION_SYMBOL) == _Symbol)
         return(true);
     }
   return(false);
  }

int OwnOrders(ulong &tickets[])
  {
   ArrayResize(tickets, 0);
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(OrderSelect(t) && OrderGetInteger(ORDER_MAGIC) == Magic && OrderGetString(ORDER_SYMBOL) == _Symbol)
        {
         int k = ArraySize(tickets);
         ArrayResize(tickets, k + 1);
         tickets[k] = t;
        }
     }
   return(ArraySize(tickets));
  }

double LotsForRisk(double slDist)
  {
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double step      = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin      = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax      = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(tickValue <= 0 || tickSize <= 0 || step <= 0) return(0);
   double lossPerLot = slDist / tickSize * tickValue;
   double lots = AccountInfoDouble(ACCOUNT_EQUITY) * RiskPercent / 100.0 / lossPerLot;
   lots = MathFloor(lots / step) * step;
   if(lots < vmin) return(0);
   return(MathMin(lots, vmax));
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   datetime gmt = TimeGMT();
   MqlDateTime g;
   TimeToStruct(gmt, g);
   bool friday = (g.day_of_week == 5);

   ulong own[];
   int cnt = OwnOrders(own);
   for(int i = 0; i < cnt; i++)
     {
      if(!OrderSelect(own[i])) continue;
      // Ablauf: 12 Stunden nach dem Stundenbeginn der Platzierung (eigene Verwaltung)
      datetime setup  = (datetime)OrderGetInteger(ORDER_TIME_SETUP);
      datetime expiry = setup - (setup % 3600) + ExpiryHours * 3600;
      bool fridayCancel = friday && (g.hour > 20 || (g.hour == 20 && g.min >= 55));
      if(TimeCurrent() >= expiry || fridayCancel)
         trade.OrderDelete(own[i]);
     }

   AdjustStopsAfterFill();

   int hourKey = (int)(gmt / 3600);
   if(hourKey != lastHourKey && g.min < 10)
     {
      lastHourKey = hourKey;
      if(!(friday && g.hour >= 20) && !HasOwnPosition() && OwnOrders(own) == 0)
         PlaceOrder();
     }
  }

void PlaceOrder()
  {
   double level, atr;
   if(!SignalLevels(level, atr)) return;
   double sl = StopATR * atr, tp = TargetATR * atr;
   double lots = LotsForRisk(sl);
   if(lots <= 0) { Print("GoldBreakout: Konto zu klein für Mindestgröße"); return; }
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double price = NormalizeDouble(level, digits);
   string comment = StringFormat("gb sd=%.3f", sl);
   if(price <= ask)        // Kurs schon über dem Level -> wie Backtest: sofortige Füllung
     {
      if(!trade.Buy(lots, _Symbol, 0, NormalizeDouble(ask - sl, digits), NormalizeDouble(ask + tp, digits), comment))
         Print("GoldBreakout: Kauf fehlgeschlagen ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
      return;
     }
   if(!trade.BuyStop(lots, price, _Symbol, NormalizeDouble(price - sl, digits), NormalizeDouble(price + tp, digits),
                     ORDER_TIME_GTC, 0, comment))
      Print("GoldBreakout: BuyStop fehlgeschlagen ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
   else
      PrintFormat("GoldBreakout: BuyStop %.2f Lots @ %.3f (SL %.2f, TP %.2f)", lots, price, sl, tp);
  }

// Stop/Ziel auf den tatsächlichen Füllkurs setzen (Backtest: Abstände ab Füllung)
void AdjustStopsAfterFill()
  {
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double pt = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(!PositionSelectByTicket(t) || PositionGetInteger(POSITION_MAGIC) != Magic) continue;
      string c = PositionGetString(POSITION_COMMENT);
      int p = StringFind(c, "sd=");
      if(p < 0) continue;
      double sd = StringToDouble(StringSubstr(c, p + 3));
      if(sd <= 0) continue;
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double wantSL = NormalizeDouble(open - sd, digits);
      double wantTP = NormalizeDouble(open + sd * TargetATR / StopATR, digits);
      if(MathAbs(PositionGetDouble(POSITION_SL) - wantSL) > 2 * pt || MathAbs(PositionGetDouble(POSITION_TP) - wantTP) > 2 * pt)
         trade.PositionModify(t, wantSL, wantTP);
     }
  }

//+------------------------------------------------------------------+
//| Geschlossene Trades protokollieren (R aus Stop-Abstand)           |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &req, const MqlTradeResult &res)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(!HistoryDealSelect(trans.deal)) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != Magic) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_ENTRY) != DEAL_ENTRY_OUT) return;
   long     posId  = HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID);
   double   profit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT);
   double   swap   = HistoryDealGetDouble(trans.deal, DEAL_SWAP);
   double   comm   = HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);
   double   exitPx = HistoryDealGetDouble(trans.deal, DEAL_PRICE);
   double   vol    = HistoryDealGetDouble(trans.deal, DEAL_VOLUME);
   datetime exitT  = (datetime)HistoryDealGetInteger(trans.deal, DEAL_TIME);
   double   entryPx = 0, sd = 0;
   datetime entryT = 0;
   if(HistorySelectByPosition(posId))
      for(int i = 0; i < HistoryDealsTotal(); i++)
        {
         ulong d = HistoryDealGetTicket(i);
         if(HistoryDealGetInteger(d, DEAL_ENTRY) == DEAL_ENTRY_IN)
           {
            entryPx = HistoryDealGetDouble(d, DEAL_PRICE);
            entryT  = (datetime)HistoryDealGetInteger(d, DEAL_TIME);
            string c = HistoryDealGetString(d, DEAL_COMMENT);
            int p = StringFind(c, "sd=");
            if(p >= 0) sd = StringToDouble(StringSubstr(c, p + 3));
           }
        }
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double riskMoney = (sd > 0 && tickSize > 0) ? sd / tickSize * tickValue * vol : 0;
   double r    = riskMoney > 0 ? profit / riskMoney : 0;
   double rNet = riskMoney > 0 ? (profit + swap + comm) / riskMoney : 0;
   bool isNew = !FileIsExist(csvName);
   int h = FileOpen(csvName, FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(h == INVALID_HANDLE) { Print("GoldBreakout: CSV nicht schreibbar"); return; }
   FileSeek(h, 0, SEEK_END);
   if(isNew)
      FileWrite(h, "position", "entry_time_server", "exit_time_server", "lots", "entry", "exit", "sl_dist",
                "profit", "swap", "commission", "r", "r_net");
   FileWrite(h, posId, TimeToString(entryT, TIME_DATE | TIME_SECONDS), TimeToString(exitT, TIME_DATE | TIME_SECONDS),
             DoubleToString(vol, 2), DoubleToString(entryPx, 3), DoubleToString(exitPx, 3), DoubleToString(sd, 3),
             DoubleToString(profit, 2), DoubleToString(swap, 2), DoubleToString(comm, 2),
             DoubleToString(r, 4), DoubleToString(rNet, 4));
   FileClose(h);
   PrintFormat("GoldBreakout: Trade %d geschlossen, %.2f R netto", posId, rNet);
  }
//+------------------------------------------------------------------+
