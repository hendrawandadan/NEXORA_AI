//+------------------------------------------------------------------+
//| NEXORA Multi-Symbol Historical Exporter                          |
//| Exports selected Market Watch symbols across configurable MT5 timeframes    |
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs
input string InpSymbols = ""; // Empty = all symbols visible in Market Watch
input string InpTimeframes = "M1,M2,M3,M4,M5,M6,M10,M12,M15,M20,M30,H1,H2,H3,H4,H6,H8,H12,D1,W1,MN1";
input datetime InpFromDate = D'2016.11.07 00:00';
input datetime InpToDate = D'2026.11.07 23:59';
input int InpChunkDays = 30;
input bool InpUseCommonFolder = false;
input int InpRetryCount = 5;

ENUM_TIMEFRAMES ParseTF(string s)
{
   StringToUpper(s);
   if(s=="M1") return PERIOD_M1; if(s=="M2") return PERIOD_M2; if(s=="M3") return PERIOD_M3; if(s=="M4") return PERIOD_M4; if(s=="M5") return PERIOD_M5; if(s=="M6") return PERIOD_M6;
   if(s=="M10") return PERIOD_M10; if(s=="M12") return PERIOD_M12; if(s=="M15") return PERIOD_M15; if(s=="M20") return PERIOD_M20; if(s=="M30") return PERIOD_M30;
   if(s=="H1") return PERIOD_H1; if(s=="H2") return PERIOD_H2; if(s=="H3") return PERIOD_H3; if(s=="H4") return PERIOD_H4; if(s=="H6") return PERIOD_H6; if(s=="H8") return PERIOD_H8; if(s=="H12") return PERIOD_H12;
   if(s=="D1" || s=="DAILY") return PERIOD_D1; if(s=="W1" || s=="WEEKLY") return PERIOD_W1; if(s=="MN1" || s=="MONTHLY") return PERIOD_MN1;
   return PERIOD_CURRENT;
}
string CleanName(string s)
{
   StringReplace(s,"/","_"); StringReplace(s,"\\","_"); StringReplace(s,".","_");
   return s;
}
int SplitList(string source,string &out[])
{
   StringReplace(source," ","");
   return StringSplit(source,',',out);
}
void ExportOne(string symbol,ENUM_TIMEFRAMES tf,datetime from,datetime to)
{
   if(!SymbolSelect(symbol,true))
   {
      PrintFormat("NEXORA: symbol unavailable: %s",symbol); return;
   }
   string tfname=EnumToString(tf);
   StringReplace(tfname,"PERIOD_","");
   string filename="NEXORA\\"+CleanName(symbol)+"_"+tfname+".csv";
   int flags=FILE_WRITE|FILE_CSV|FILE_ANSI;
   if(InpUseCommonFolder) flags|=FILE_COMMON;
   FolderCreate("NEXORA",InpUseCommonFolder);
   int fh=FileOpen(filename,flags,',');
   if(fh==INVALID_HANDLE)
   {
      PrintFormat("NEXORA: cannot open %s err=%d",filename,GetLastError()); return;
   }
   FileWrite(fh,"time","open","high","low","close","tick_volume","real_volume","spread");
   int digits=(int)SymbolInfoInteger(symbol,SYMBOL_DIGITS);
   datetime cursor=from,last=0;
   long total=0;
   while(cursor<=to)
   {
      datetime end=cursor+(InpChunkDays*86400);
      if(end>to) end=to;
      MqlRates rates[]; ArraySetAsSeries(rates,false);
      int copied=-1,err=0;
      for(int attempt=0;attempt<InpRetryCount;attempt++)
      {
         ResetLastError();
         copied=CopyRates(symbol,tf,cursor,end,rates);
         err=GetLastError();
         if(copied>0) break;
         Sleep(500);
      }
      if(copied<=0)
         PrintFormat("NEXORA WARNING %s %s %s..%s copied=%d err=%d",
            symbol,tfname,TimeToString(cursor),TimeToString(end),copied,err);
      else
      {
         for(int i=0;i<copied;i++)
         {
            if(rates[i].time<from || rates[i].time>to || rates[i].time<=last) continue;
            FileWrite(fh,TimeToString(rates[i].time,TIME_DATE|TIME_MINUTES),
              DoubleToString(rates[i].open,digits),DoubleToString(rates[i].high,digits),
              DoubleToString(rates[i].low,digits),DoubleToString(rates[i].close,digits),
              (long)rates[i].tick_volume,(long)rates[i].real_volume,(int)rates[i].spread);
            last=rates[i].time; total++;
         }
      }
      if(end>=to) break;
      cursor=end+1;
   }
   FileFlush(fh); FileClose(fh);
   PrintFormat("NEXORA EXPORT DONE: %s %s bars=%I64d file=%s",symbol,tfname,total,filename);
}
void OnStart()
{
   if(InpToDate<=InpFromDate || InpChunkDays<1) { Print("NEXORA: invalid date/chunk inputs"); return; }
   string syms[],tfs[];
   int ns=0;
   if(StringLen(InpSymbols)>0) ns=SplitList(InpSymbols,syms);
   else
   {
      ns=SymbolsTotal(true);
      ArrayResize(syms,ns);
      for(int i=0;i<ns;i++) syms[i]=SymbolName(i,true);
   }
   int nt=SplitList(InpTimeframes,tfs);
   if(ns<=0 || nt<=0) { Print("NEXORA: no symbols/timeframes"); return; }
   PrintFormat("NEXORA export starting: symbols=%d timeframes=%d",ns,nt);
   for(int i=0;i<ns;i++)
      for(int j=0;j<nt;j++)
      {
         ENUM_TIMEFRAMES tf=ParseTF(tfs[j]);
         if(tf==PERIOD_CURRENT) { PrintFormat("NEXORA: unsupported timeframe %s",tfs[j]); continue; }
         ExportOne(syms[i],tf,InpFromDate,InpToDate);
      }
   Print("NEXORA export process finished. Check Journal warnings and per-symbol bar counts.");
}
