"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  CheckCircle2,
  XCircle,
  ShieldAlert,
  ArrowRight,
  TrendingUp,
  TrendingDown,
  Pause,
  Play,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DEMO_SCENARIOS, type DemoScenario, type DemoTrade } from "@/lib/demo-data";

function TimelineEntry({ trade }: { trade: DemoTrade }) {
  const isEntered = trade.action === "entered";
  const isExited = trade.action === "exited";
  const isSkipped = trade.action === "skipped";

  return (
    <div className={cn(
      "flex gap-3 items-start px-3 py-2 rounded-md",
      isSkipped && "bg-muted/30",
      isExited && trade.pnl && trade.pnl > 0 && "bg-profit/5",
      isExited && trade.pnl && trade.pnl < 0 && "bg-loss/5",
    )}>
      {/* Icon */}
      <div className="flex-shrink-0 mt-0.5">
        {isEntered && <Play className="h-3.5 w-3.5 text-profit" />}
        {isExited && trade.pnl && trade.pnl > 0 && <CheckCircle2 className="h-3.5 w-3.5 text-profit" />}
        {isExited && trade.pnl && trade.pnl <= 0 && <XCircle className="h-3.5 w-3.5 text-loss" />}
        {isSkipped && <ShieldAlert className="h-3.5 w-3.5 text-warning" />}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium">{trade.date}</span>
          <Badge
            variant="outline"
            className={cn(
              "text-[10px]",
              isEntered && "text-profit border-profit/20",
              isExited && trade.pnl && trade.pnl > 0 && "text-profit border-profit/20",
              isExited && trade.pnl && trade.pnl <= 0 && "text-loss border-loss/20",
              isSkipped && "text-warning border-warning/20",
            )}
          >
            {isEntered ? "ENTRY" : isExited ? "EXIT" : "SKIPPED"}
          </Badge>
          {trade.stocks.length > 0 && (
            <span className="text-[11px] text-muted-foreground">
              {trade.stocks.join(", ")}
            </span>
          )}
        </div>
        <p className="text-[11px] text-muted-foreground mt-0.5">{trade.reason}</p>
      </div>

      {/* Right side */}
      <div className="flex-shrink-0 text-right">
        {trade.pnl !== undefined && trade.pnl !== 0 && (
          <p className={cn("text-xs font-medium", trade.pnl > 0 ? "text-profit" : "text-loss")}>
            {trade.pnl > 0 ? "+" : ""}₹{trade.pnl.toLocaleString()}
          </p>
        )}
        <p className="text-[11px] text-muted-foreground">
          NIFTY {trade.niftyChange}
        </p>
      </div>
    </div>
  );
}

export function ReplayMode() {
  const [selectedYear, setSelectedYear] = useState("2023");
  const scenario = DEMO_SCENARIOS.find((s) => s.year === selectedYear);

  return (
    <Card>
      <CardHeader className="pb-2 px-4 pt-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">
            Replay: How the System Behaved
          </CardTitle>
          <div className="flex gap-1">
            {DEMO_SCENARIOS.map((s) => (
              <button
                key={s.year}
                onClick={() => setSelectedYear(s.year)}
                className={cn(
                  "px-2.5 py-1 rounded-md text-xs font-medium transition-colors",
                  selectedYear === s.year
                    ? "bg-foreground text-background"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted/50",
                )}
              >
                {s.year}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>

      {scenario && (
        <CardContent className="px-4 pb-4 space-y-4">
          {/* Scenario description */}
          <div className={cn(
            "rounded-lg border p-3",
            scenario.regime === "bull" && "border-profit/20 bg-profit/5",
            scenario.regime === "bear" && "border-loss/20 bg-loss/5",
            scenario.regime === "sideways" && "border-border/50 bg-muted/30",
          )}>
            <div className="flex items-center gap-2 mb-1">
              {scenario.regime === "bull" ? (
                <TrendingUp className="h-4 w-4 text-profit" />
              ) : scenario.regime === "bear" ? (
                <TrendingDown className="h-4 w-4 text-loss" />
              ) : (
                <Pause className="h-4 w-4 text-muted-foreground" />
              )}
              <span className="text-sm font-medium">{scenario.label}</span>
            </div>
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              {scenario.description}
            </p>
          </div>

          {/* Scenario metrics */}
          <div className="grid grid-cols-5 gap-2">
            <div className="text-center">
              <p className="text-[11px] text-muted-foreground">P&L</p>
              <p className={cn("text-sm font-semibold", scenario.totalPnl > 0 ? "text-profit" : "text-loss")}>
                {scenario.totalPnl > 0 ? "+" : ""}₹{scenario.totalPnl.toLocaleString()}
              </p>
            </div>
            <div className="text-center">
              <p className="text-[11px] text-muted-foreground">Win Rate</p>
              <p className="text-sm font-semibold">{scenario.winRate}%</p>
            </div>
            <div className="text-center">
              <p className="text-[11px] text-muted-foreground">Trades</p>
              <p className="text-sm font-semibold">{scenario.trades}</p>
            </div>
            <div className="text-center">
              <p className="text-[11px] text-muted-foreground">Max DD</p>
              <p className="text-sm font-semibold text-loss">{scenario.maxDd}%</p>
            </div>
            <div className="text-center">
              <p className="text-[11px] text-muted-foreground">IC</p>
              <p className={cn("text-sm font-semibold", scenario.ic > 0 ? "text-profit" : "text-loss")}>
                {scenario.ic > 0 ? "+" : ""}{scenario.ic.toFixed(3)}
              </p>
            </div>
          </div>

          {/* Timeline */}
          <div className="space-y-1">
            <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider mb-2">
              Trade Timeline
            </p>
            {scenario.timeline.map((trade, i) => (
              <TimelineEntry key={i} trade={trade} />
            ))}
          </div>
        </CardContent>
      )}
    </Card>
  );
}
