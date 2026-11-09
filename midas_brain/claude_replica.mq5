//+------------------------------------------------------------------+
//| ClaudeReplica — จำลองพฤติกรรม Claude_Ai_Bot_v1 (XAUUSD_TrailingEntry)
//| สร้างจากพารามิเตอร์ที่ดึงจาก .ex5 + พฤติกรรมดีลจริงบนเดโม
//| กลไก: pending stop ไล่ตามราคา (ratchet) สองฝั่ง ใครโดนกระแทกก่อนเข้า
//+------------------------------------------------------------------+
#property strict

input double InpLotSize=0.1;
input bool   InpUseAutoLot=true;
input double InpBaseBalance=1000.0;
input double InpBaseLot=0.1;
input double InpMaxLot=5.0;
input int    InpEntryGapPoints=300;
input int    InpInitialStopPoints=500;
input int    InpTrailStepPoints=50;
input double InpCommissionPerLot=0.0;
input int    InpProfitBufferPoints=10;
input double InpTrailSpreadMult=2.0;
input int    InpModifyStepPoints=10;
input int    InpMaxSpreadPoints=350;
input long   InpMagicNumber=778242;
input string InpTradeComment="XAUUSD_TrailingEntry";

double pt;

bool send(MqlTradeRequest &req)
{
   MqlTradeResult res;
   req.magic=InpMagicNumber;
   req.deviation=100;
   req.type_filling=ORDER_FILLING_RETURN;
   return OrderSend(req,res) && res.retcode<10009;
}

double calcLot()
{
   if(!InpUseAutoLot) return InpLotSize;
   double lot=InpBaseLot*AccountInfoDouble(ACCOUNT_BALANCE)/InpBaseBalance;
   return MathMin(InpMaxLot,MathMax(0.01,NormalizeDouble(lot,2)));
}

ulong findPending(ENUM_ORDER_TYPE type)
{
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      ulong t=OrderGetTicket(i);
      if(t && OrderGetInteger(ORDER_MAGIC)==InpMagicNumber && OrderGetInteger(ORDER_TYPE)==type)
         return t;
   }
   return 0;
}

bool hasPosition(ENUM_POSITION_TYPE type)
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong t=PositionGetTicket(i);
      if(t && PositionGetInteger(POSITION_MAGIC)==InpMagicNumber && PositionGetInteger(POSITION_TYPE)==type)
         return true;
   }
   return false;
}

void placeStop(ENUM_ORDER_TYPE type,double price,double sl)
{
   MqlTradeRequest req={};
   req.action=TRADE_ACTION_PENDING;
   req.symbol=_Symbol;
   req.volume=calcLot();
   req.type=type;
   req.price=NormalizeDouble(price,_Digits);
   req.sl=NormalizeDouble(sl,_Digits);
   req.comment=InpTradeComment;
   send(req);
}

void modifyPending(ulong ticket,double price,double sl)
{
   MqlTradeRequest req={};
   req.action=TRADE_ACTION_MODIFY;
   req.order=ticket;
   req.price=NormalizeDouble(price,_Digits);
   req.sl=NormalizeDouble(sl,_Digits);
   send(req);
}

void deleteOrder(ulong ticket)
{
   MqlTradeRequest req={};
   req.action=TRADE_ACTION_REMOVE;
   req.order=ticket;
   send(req);
}

void modifyPos(ulong ticket,double sl)
{
   MqlTradeRequest req={};
   req.action=TRADE_ACTION_SLTP;
   req.position=ticket;
   req.symbol=_Symbol;
   req.sl=NormalizeDouble(sl,_Digits);
   req.tp=PositionGetDouble(POSITION_TP);
   send(req);
}

void trailPositions(double bid,double ask,double trailDist,double lockPts,double minMod)
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong t=PositionGetTicket(i);
      if(!t || PositionGetInteger(POSITION_MAGIC)!=InpMagicNumber) continue;
      double sl=PositionGetDouble(POSITION_SL);
      double open=PositionGetDouble(POSITION_PRICE_OPEN);
      if(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY)
      {
         double ns=bid-trailDist;
         if(ns>open+lockPts && ns>sl+minMod) modifyPos(t,ns);
      }
      else
      {
         double ns=ask+trailDist;
         if(ns<open-lockPts && (sl==0 || ns<sl-minMod)) modifyPos(t,ns);
      }
   }
}

int OnInit(){ pt=_Point; return INIT_SUCCEEDED; }

void OnTick()
{
   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double gap=InpEntryGapPoints*pt, mod=InpModifyStepPoints*pt;
   double stopDist=InpInitialStopPoints*pt;
   double spread=(ask-bid)/pt;

   trailPositions(bid,ask,InpTrailStepPoints*InpTrailSpreadMult*pt,
                  InpProfitBufferPoints*pt,mod);

   if(spread>InpMaxSpreadPoints) return;

   ulong tb=findPending(ORDER_TYPE_BUY_STOP);
   if(!hasPosition(POSITION_TYPE_BUY))
   {
      double p=ask+gap;
      if(tb==0) placeStop(ORDER_TYPE_BUY_STOP,p,p-stopDist);
      else if(OrderGetDouble(ORDER_PRICE_OPEN)-p>mod) modifyPending(tb,p,p-stopDist);
   }
   else if(tb!=0) deleteOrder(tb);

   ulong ts=findPending(ORDER_TYPE_SELL_STOP);
   if(!hasPosition(POSITION_TYPE_SELL))
   {
      double p=bid-gap;
      if(ts==0) placeStop(ORDER_TYPE_SELL_STOP,p,p+stopDist);
      else if(p-OrderGetDouble(ORDER_PRICE_OPEN)>mod) modifyPending(ts,p,p+stopDist);
   }
   else if(ts!=0) deleteOrder(ts);
}
//+------------------------------------------------------------------+
