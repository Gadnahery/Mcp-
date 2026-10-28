#property strict
#property version "0.3.0"
#property description "Candle-behaviour EA prototype. Demo account only."
#include <Trade/Trade.mqh>
CTrade trade;

input bool EnableTrading=true;
input bool DemoAccountOnly=true;
input double RiskPercent=0.25;
input bool UseFixedLotSize=true;
input double FixedLotSize=0.01;
input double MinimumRewardRisk=3.0;
input int MagicNumber=28102026;
input int MaxTradesPerDay=3;
input double MaxDailyLossPercent=1.0;
input int SwingLookback15M=24;
input int SwingLookback5M=24;
input int SweepLookback5M=6;
input int ConfirmationCloses=2;
input double MinBodyToRange=0.45;
input double MinSingleBodyToRange=0.20;
input double StopBufferPoints=3.0;
input double MaxSpreadPoints=0.0;
input int MaxEntryAgeMinutes=5;
input bool UseM5Confirmation=false; // retained for symbols where M1 entry confirmation is unsuitable
input bool AllowMixedH1Context=false;

datetime dayStart=0;
double dayEquity=0;
int tradesToday=0;
enum Side { NONE=0, BUY_SIDE=1, SELL_SIDE=-1 };
ENUM_TIMEFRAMES EntryTF(){return UseM5Confirmation?PERIOD_M5:PERIOD_M1;}
datetime StartOfDay(datetime t){MqlDateTime d;TimeToStruct(t,d);d.hour=0;d.min=0;d.sec=0;return StructToTime(d);}

void RefreshDay(){
 datetime now=TimeCurrent(),s=StartOfDay(now); if(s==dayStart)return;
 dayStart=s;dayEquity=AccountInfoDouble(ACCOUNT_EQUITY);tradesToday=0;
 if(HistorySelect(s,now))for(int i=0;i<HistoryDealsTotal();i++){
  ulong d=HistoryDealGetTicket(i);if(!d)continue;
  if(HistoryDealGetString(d,DEAL_SYMBOL)!=_Symbol||(long)HistoryDealGetInteger(d,DEAL_MAGIC)!=MagicNumber)continue;
  if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(d,DEAL_ENTRY)==DEAL_ENTRY_IN)tradesToday++;
 }
}
bool LossLimit(){return dayEquity>0&&(dayEquity-AccountInfoDouble(ACCOUNT_EQUITY))/dayEquity*100>=MaxDailyLossPercent;}
bool OurPosition(){for(int i=PositionsTotal()-1;i>=0;i--){if(!PositionGetTicket(i))continue;if(PositionGetString(POSITION_SYMBOL)==_Symbol&&(long)PositionGetInteger(POSITION_MAGIC)==MagicNumber)return true;}return false;}
bool Rates(ENUM_TIMEFRAMES tf,int n,MqlRates &r[]){ArraySetAsSeries(r,true);return CopyRates(_Symbol,tf,0,n,r)>=n;}
double BodyRatio(MqlRates &c){double z=c.high-c.low;return z>0?MathAbs(c.close-c.open)/z:0;}

int H1Bias(){
 MqlRates r[];if(!Rates(PERIOD_H1,5,r))return 0;
 if(r[1].close>r[2].close&&r[2].close>r[3].close&&r[3].close>r[4].close)return BUY_SIDE;
 if(r[1].close<r[2].close&&r[2].close<r[3].close&&r[3].close<r[4].close)return SELL_SIDE;return 0;
}
int M15Structure(){
 MqlRates r[];if(!Rates(PERIOD_M15,SwingLookback15M+5,r))return 0;
 double h[2],l[2];int nh=0,nl=0;
 for(int i=3;i<SwingLookback15M&&(nh<2||nl<2);i++){
  bool sh=true,sl=true;for(int j=1;j<=2;j++){if(r[i].high<=r[i-j].high||r[i].high<=r[i+j].high)sh=false;if(r[i].low>=r[i-j].low||r[i].low>=r[i+j].low)sl=false;}
  if(sh&&nh<2)h[nh++]=r[i].high;if(sl&&nl<2)l[nl++]=r[i].low;
 }
 if(nh<2||nl<2)return 0;if(h[0]>h[1]&&l[0]>l[1])return BUY_SIDE;if(h[0]<h[1]&&l[0]<l[1])return SELL_SIDE;return 0;
}
bool RecentSwing(ENUM_TIMEFRAMES tf,bool wantHigh,int lookback,double &v){
 MqlRates r[];if(!Rates(tf,lookback+5,r))return false;
 for(int i=3;i<lookback;i++){bool ok=true;for(int j=1;j<=2;j++){if(wantHigh&&(r[i].high<=r[i-j].high||r[i].high<=r[i+j].high))ok=false;if(!wantHigh&&(r[i].low>=r[i-j].low||r[i].low>=r[i+j].low))ok=false;}if(ok){v=wantHigh?r[i].high:r[i].low;return true;}}
 return false;
}
bool Sweep(int &side,double &extreme,datetime &when){
 MqlRates r[];if(!Rates(PERIOD_M5,SwingLookback5M+SweepLookback5M+5,r))return false;
 for(int i=1;i<=SweepLookback5M;i++){double hi=-DBL_MAX,lo=DBL_MAX;int end=MathMin(i+SwingLookback5M,ArraySize(r)-1);
  for(int j=i+1;j<=end;j++){hi=MathMax(hi,r[j].high);lo=MathMin(lo,r[j].low);}
  if(r[i].high>hi&&r[i].close<hi&&r[i].close<r[i].open){side=SELL_SIDE;extreme=r[i].high;when=r[i].time;return true;}
  if(r[i].low<lo&&r[i].close>lo&&r[i].close>r[i].open){side=BUY_SIDE;extreme=r[i].low;when=r[i].time;return true;}
 }return false;
}
bool ConfirmM5(int side,datetime sweptAt,datetime &confirmedAt){
 int n=MathMax(2,MathMin(3,ConfirmationCloses));MqlRates r[];if(!Rates(PERIOD_M5,n+4,r))return false;
 // The full run of consecutive dominance candles must close after the sweep candle.
 if(r[n].time<sweptAt+300)return false;
 double sum=0,prev=0;
 for(int i=n;i>=1;i--){
  if(side==BUY_SIDE?r[i].close<=r[i].open:r[i].close>=r[i].open)return false;
  double b=BodyRatio(r[i]);if(b<MinSingleBodyToRange)return false;sum+=b;
  if(i<n&&(side==BUY_SIDE?r[i].close<=prev:r[i].close>=prev))return false;
  prev=r[i].close;
 }
 if(sum/n<MinBodyToRange)return false;
 confirmedAt=r[1].time+300; // latest M5 dominance candle has fully closed
 return true;
}
bool M1Entry(int side,datetime m5ConfirmedAt,double &entry,double &sl){
 if(UseM5Confirmation){ // optional fallback: use M5 close-based entry with original sweep invalidation
  MqlRates r[];if(!Rates(PERIOD_M5,3,r)||r[1].time<m5ConfirmedAt)return false;
  entry=side==BUY_SIDE?SymbolInfoDouble(_Symbol,SYMBOL_ASK):SymbolInfoDouble(_Symbol,SYMBOL_BID);
  sl=side==BUY_SIDE?r[1].low-StopBufferPoints*_Point:r[1].high+StopBufferPoints*_Point;
  return true;
 }
 MqlRates r[];if(!Rates(PERIOD_M1,8,r))return false;
 // Wait for a fresh 1M directional response after M5 dominance is confirmed.
 if(r[1].time<m5ConfirmedAt||TimeCurrent()-r[1].time>MaxEntryAgeMinutes*60)return false;
 if(side==BUY_SIDE?(r[1].close<=r[1].open||r[1].close<=r[2].close):(r[1].close>=r[1].open||r[1].close>=r[2].close))return false;
 if(BodyRatio(r[1])<MinSingleBodyToRange)return false;
 double microExtreme=side==BUY_SIDE?DBL_MAX:-DBL_MAX;
 // Tight invalidation comes from the most recent 1M micro-structure, not the entire 5M sweep.
 for(int i=1;i<=5;i++){if(side==BUY_SIDE)microExtreme=MathMin(microExtreme,r[i].low);else microExtreme=MathMax(microExtreme,r[i].high);}
 entry=side==BUY_SIDE?SymbolInfoDouble(_Symbol,SYMBOL_ASK):SymbolInfoDouble(_Symbol,SYMBOL_BID);
 sl=side==BUY_SIDE?microExtreme-StopBufferPoints*_Point:microExtreme+StopBufferPoints*_Point;
 return (side==BUY_SIDE?sl<entry:sl>entry);
}
bool Target(int side,double entry,double &tp){
 double v=0,c=0;bool found=false;
 if(side==BUY_SIDE){if(RecentSwing(PERIOD_M5,true,SwingLookback5M,v)&&v>entry){c=v;found=true;}if(RecentSwing(PERIOD_M15,true,SwingLookback15M,v)&&v>entry&&(!found||v<c)){c=v;found=true;}}
 else{if(RecentSwing(PERIOD_M5,false,SwingLookback5M,v)&&v<entry){c=v;found=true;}if(RecentSwing(PERIOD_M15,false,SwingLookback15M,v)&&v<entry&&(!found||v>c)){c=v;found=true;}}
 if(found)tp=c;return found;
}
double Lots(double entry,double sl){
 if(UseFixedLotSize){
  double requested=FixedLotSize,minV=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN),maxV=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX),stepV=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
  if(requested<minV||requested>maxV||stepV<=0)return 0;
  double normalized=MathFloor((requested+1e-9)/stepV)*stepV;
  return normalized>=minV?NormalizeDouble(normalized,3):0;
 }
 double money=AccountInfoDouble(ACCOUNT_EQUITY)*RiskPercent/100,tick=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE),value=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE),dist=MathAbs(entry-sl);
 if(money<=0||tick<=0||value<=0||dist<=0)return 0;double raw=money/(dist/tick*value),minLot=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);if(raw<minLot)return 0;
 double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);if(step<=0)return 0;return NormalizeDouble(MathFloor(MathMin(raw,SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX))/step)*step,step<0.01?3:2);
}

void Evaluate(){
 RefreshDay();
 if(!EnableTrading){Comment("ANALYSIS ONLY: EnableTrading=false");return;}
 if(DemoAccountOnly&&AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO){Comment("BLOCKED: demo account required");return;}
 if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)||!MQLInfoInteger(MQL_TRADE_ALLOWED)||LossLimit()||tradesToday>=MaxTradesPerDay||OurPosition()){Comment("Trading guard active (permissions/risk/position cap)");return;}
 double spread=(SymbolInfoDouble(_Symbol,SYMBOL_ASK)-SymbolInfoDouble(_Symbol,SYMBOL_BID))/_Point;if(MaxSpreadPoints>0&&spread>MaxSpreadPoints){Comment("NO TRADE: spread gate");return;}
 int h=H1Bias(),m=M15Structure();if((h==0&&!AllowMixedH1Context)||m==0||(h!=0&&h!=m)){Comment("NO TRADE: H1/M15 context unclear or conflicting");return;}
 int side=0;double sweepExtreme=0;datetime st=0;if(!Sweep(side,sweepExtreme,st)){Comment("NO TRADE: no M5 sweep/reclaim");return;}
 datetime dominanceClosedAt=0;
 if(side!=m||(h!=0&&side!=h)||!ConfirmM5(side,st,dominanceClosedAt)){Comment("NO TRADE: M5 sweep or consecutive dominance confirmation conflicts with context");return;}
 double entry=0,sl=0,tp=0;
 if(!M1Entry(side,dominanceClosedAt,entry,sl)){Comment("NO TRADE: waiting for a fresh M1 entry response after M5 dominance");return;}
 if(!Target(side,entry,tp)){Comment("NO TRADE: no opposing reaction area");return;}
 double risk=MathAbs(entry-sl),reward=side==BUY_SIDE?tp-entry:entry-tp;if(risk<=0||reward/risk+1e-8<MinimumRewardRisk){Comment("NO TRADE: next area fails 1:3 R:R");return;}
 double minDist=(double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)*_Point;
 if((side==BUY_SIDE&&(sl>=entry||tp<=entry||entry-sl<minDist||tp-entry<minDist))||(side==SELL_SIDE&&(sl<=entry||tp>=entry||sl-entry<minDist||entry-tp<minDist))){Comment("NO TRADE: broker stop distance");return;}
 double lots=Lots(entry,sl);if(lots<=0){Comment("NO TRADE: risk sizing invalid or minimum lot too large");return;}
 trade.SetExpertMagicNumber(MagicNumber);trade.SetDeviationInPoints(10);trade.SetTypeFillingBySymbol(_Symbol);
 bool ok=side==BUY_SIDE?trade.Buy(lots,_Symbol,0,NormalizeDouble(sl,_Digits),NormalizeDouble(tp,_Digits),"CandleBehaviourEA BUY"):trade.Sell(lots,_Symbol,0,NormalizeDouble(sl,_Digits),NormalizeDouble(tp,_Digits),"CandleBehaviourEA SELL");
 if(ok){tradesToday++;Print("DEMO EA ",side==BUY_SIDE?"BUY":"SELL"," lots=",lots," SL=",sl," TP=",tp," RR=",reward/risk);}else Print("Order rejected: ",trade.ResultRetcodeDescription());
}
int OnInit(){if(MinimumRewardRisk<3.0||ConfirmationCloses<2||ConfirmationCloses>3||RiskPercent<=0||FixedLotSize<0.01||MaxDailyLossPercent<=0||MaxTradesPerDay<1)return INIT_PARAMETERS_INCORRECT;if(DemoAccountOnly&&AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO){Print("Refusing non-demo account");return INIT_FAILED;}RefreshDay();Print("EA prototype. Demo-only; EnableTrading=",EnableTrading," fixedLots=",UseFixedLotSize," lot=",FixedLotSize);return INIT_SUCCEEDED;}
void OnTick(){\n ManageOpenTrade(); // runs on every tick so SL protection is not delayed to the next entry candle\n static datetime last=0;datetime t=iTime(_Symbol,EntryTF(),1);if(t<=0||t==last)return;last=t;Evaluate();\n}
