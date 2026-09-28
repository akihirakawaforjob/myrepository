//+------------------------------------------------------------------+
//| GotobiFade.mq5                                                    |
//| 事前登録 002: 五十日の仲値後(09:55 JST)に USDJPY を売り、          |
//| 11:00 JST に買い戻す。デモ口座での前向きテスト用。                  |
//| 時刻は PC の時計(TimeGMT)から JST を計算する。PC の時計は           |
//| 自動同期にしておくこと。                                           |
//+------------------------------------------------------------------+
#property copyright "fxlab"
#property version   "1.00"

#include <Trade\Trade.mqh>

input double Lots              = 0.10;   // 取引数量(ロット)
input long   Magic             = 2002;   // この EA の注文を見分ける番号
input double MaxSpreadPips     = 5.0;    // これより広いスプレッドなら入らない(安全装置)
input double EmergencySLPips   = 100.0;  // 非常用の損切り(検証では最大損失 41 pips)
input bool   AllowRealAccount  = false;  // true にしない限りリアル口座では動かない
input string LogFile           = "GotobiFade_log.csv";

// 日本の祝日と銀行休業日(12/31〜1/3)。2029 年末まで。以降は追記が必要。
const datetime JP_HOLIDAYS[] = {
   D'2026.09.21',D'2026.09.22',D'2026.09.23',D'2026.10.12',D'2026.11.03',D'2026.11.23',
   D'2026.12.31',D'2027.01.01',D'2027.01.02',D'2027.01.03',D'2027.01.11',D'2027.02.11',
   D'2027.02.23',D'2027.03.21',D'2027.03.22',D'2027.04.29',D'2027.05.03',D'2027.05.04',
   D'2027.05.05',D'2027.07.19',D'2027.08.11',D'2027.09.20',D'2027.09.23',D'2027.10.11',
   D'2027.11.03',D'2027.11.23',D'2027.12.31',D'2028.01.01',D'2028.01.02',D'2028.01.03',
   D'2028.01.10',D'2028.02.11',D'2028.02.23',D'2028.03.20',D'2028.04.29',D'2028.05.03',
   D'2028.05.04',D'2028.05.05',D'2028.07.17',D'2028.08.11',D'2028.09.18',D'2028.09.22',
   D'2028.10.09',D'2028.11.03',D'2028.11.23',D'2028.12.31',D'2029.01.01',D'2029.01.02',
   D'2029.01.03',D'2029.01.08',D'2029.02.11',D'2029.02.12',D'2029.02.23',D'2029.03.20',
   D'2029.04.29',D'2029.04.30',D'2029.05.03',D'2029.05.04',D'2029.05.05',D'2029.07.16',
   D'2029.08.11',D'2029.09.17',D'2029.09.23',D'2029.09.24',D'2029.10.08',D'2029.11.03',
   D'2029.11.23',D'2029.12.31'
};

const int ENTRY_H = 9,  ENTRY_M = 55;   // JST
const int EXIT_H  = 11, EXIT_M  = 0;    // JST
const int ENTRY_WINDOW_SEC = 120;       // 09:55:00〜09:57:00 の間だけ入る

CTrade trade;
double pip;
string gvLastEntry;

//--- 日付ユーティリティ ------------------------------------------------
datetime DayStart(datetime t) { return t - (t % 86400); }

datetime MakeDate(int y, int m, int d)
{
   MqlDateTime s; ZeroMemory(s);
   s.year = y; s.mon = m; s.day = d;
   return StructToTime(s);
}

int DaysInMonth(int y, int m)
{
   static const int dim[] = {31,28,31,30,31,30,31,31,30,31,30,31};
   if(m == 2 && ((y % 4 == 0 && y % 100 != 0) || y % 400 == 0)) return 29;
   return dim[m - 1];
}

bool IsJpHoliday(datetime d)
{
   for(int i = 0; i < ArraySize(JP_HOLIDAYS); i++)
      if(JP_HOLIDAYS[i] == d) return true;
   return false;
}

bool IsJpBusinessDay(datetime d)
{
   MqlDateTime s; TimeToStruct(d, s);
   if(s.day_of_week == 0 || s.day_of_week == 6) return false;
   return !IsJpHoliday(d);
}

datetime PrevBusinessDay(datetime d)
{
   while(!IsJpBusinessDay(d)) d -= 86400;
   return d;
}

// d(JST の日付, 0 時)が五十日か。5,10,15,20,25,30 日と月末営業日、休日なら直前の営業日に繰り上げ。
bool IsGotobi(datetime d)
{
   if(!IsJpBusinessDay(d)) return false;
   MqlDateTime s; TimeToStruct(d, s);
   // 繰り上げは最大で数日なので、当月と翌月の候補日を見れば足りる
   for(int k = 0; k < 2; k++)
   {
      int y = s.year, m = s.mon + k;
      if(m > 12) { m = 1; y++; }
      int dim = DaysInMonth(y, m);
      for(int day = 5; day <= 30; day += 5)
         if(day <= dim && PrevBusinessDay(MakeDate(y, m, day)) == d) return true;
      if(PrevBusinessDay(MakeDate(y, m, dim)) == d) return true;
   }
   return false;
}

datetime NowJst() { return TimeGMT() + 9 * 3600; }

//--- ログ -------------------------------------------------------------
void Log(string action, double price, string note)
{
   int h = FileOpen(LogFile, FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(h == INVALID_HANDLE) { Print("log open failed: ", GetLastError()); return; }
   if(FileSize(h) == 0)
      FileWrite(h, "utc", "jst", "action", "bid", "ask", "spread_pips", "price", "note");
   FileSeek(h, 0, SEEK_END);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   FileWrite(h, TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS), TimeToString(NowJst(), TIME_DATE | TIME_SECONDS),
             action, DoubleToString(bid, _Digits), DoubleToString(ask, _Digits),
             DoubleToString((ask - bid) / pip, 2), DoubleToString(price, _Digits), note);
   FileClose(h);
}

//--- ポジション ---------------------------------------------------------
ulong FindPosition()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) == Magic && PositionGetString(POSITION_SYMBOL) == _Symbol)
         return ticket;
   }
   return 0;
}

//--- 本体 -------------------------------------------------------------
int OnInit()
{
   if(StringFind(_Symbol, "USDJPY") != 0)
   {
      Alert("GotobiFade: USDJPY のチャートに入れてください(今: ", _Symbol, ")");
      return INIT_FAILED;
   }
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_DEMO && !AllowRealAccount)
   {
      Alert("GotobiFade: デモ口座ではないので停止しました(AllowRealAccount=false)");
      return INIT_FAILED;
   }
   pip = (_Digits == 3 || _Digits == 5) ? _Point * 10 : _Point;
   gvLastEntry = "GotobiFade_last_" + IntegerToString(Magic);
   trade.SetExpertMagicNumber(Magic);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(30);
   EventSetTimer(1);
   datetime today = DayStart(NowJst());
   PrintFormat("GotobiFade 開始: JST=%s, 今日は五十日=%s, サーバー時刻とPCのUTCの差=%d 秒",
               TimeToString(NowJst()), IsGotobi(today) ? "はい" : "いいえ",
               (int)(TimeTradeServer() - TimeGMT()));
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) { EventKillTimer(); }

void OnTimer()
{
   datetime jst = NowJst();
   datetime today = DayStart(jst);
   int sec = (int)(jst - today);
   ulong ticket = FindPosition();

   // 決済: 11:00 JST 以降、または建ててから 2 時間を超えたら
   if(ticket != 0)
   {
      datetime opened = (datetime)PositionGetInteger(POSITION_TIME);
      if(sec >= EXIT_H * 3600 + EXIT_M * 60 || TimeTradeServer() - opened > 2 * 3600)
      {
         if(trade.PositionClose(ticket))
            Log("close", trade.ResultPrice(), "retcode=" + IntegerToString(trade.ResultRetcode()));
         else
            Log("close_failed", 0, "retcode=" + IntegerToString(trade.ResultRetcode()));
      }
      return;
   }

   // 新規: 五十日の 09:55:00〜09:57:00 JST に 1 回だけ
   int entrySec = ENTRY_H * 3600 + ENTRY_M * 60;
   if(sec < entrySec || sec >= entrySec + ENTRY_WINDOW_SEC) return;
   if(!IsGotobi(today)) return;
   if(GlobalVariableCheck(gvLastEntry) && (datetime)GlobalVariableGet(gvLastEntry) == today) return;

   GlobalVariableSet(gvLastEntry, (double)today);   // 失敗しても同じ日に再挑戦しない
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double spread = (ask - bid) / pip;
   if(spread > MaxSpreadPips)
   {
      Log("skip_spread", 0, "spread too wide");
      return;
   }
   double sl = NormalizeDouble(bid + EmergencySLPips * pip, _Digits);
   if(trade.Sell(Lots, _Symbol, 0.0, sl, 0.0, "gotobi-fade"))
      Log("sell", trade.ResultPrice(), "retcode=" + IntegerToString(trade.ResultRetcode()));
   else
      Log("sell_failed", 0, "retcode=" + IntegerToString(trade.ResultRetcode()));
}
