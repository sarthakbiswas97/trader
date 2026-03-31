"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  TrendingUp,
  TrendingDown,
  Pause,
  Zap,
  Repeat,
  Banknote,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useApi } from "@/hooks/use-api";
import { api } from "@/lib/api";
import type { MultiEngineStatus } from "@/lib/api";
import { PnlText, formatCurrency } from "@/components/pnl-text";

const REGIME_CONFIG = {
  BULL: {
    label: "Bull Market",
    icon: TrendingUp,
    color: "text-profit",
    bg: "bg-profit/5",
    border: "border-profit/20",
    desc: "Uptrend confirmed — both engines active",
  },
  NEUTRAL: {
    label: "Neutral",
    icon: Pause,
    color: "text-muted-foreground",
    bg: "bg-muted/30",
    border: "border-border/50",
    desc: "Mixed signals — large-cap primary, midcap reduced",
  },
  WEAK: {
    label: "Weak / Bear",
    icon: TrendingDown,
    color: "text-loss",
    bg: "bg-loss/5",
    border: "border-loss/20",
    desc: "Downtrend — reduced exposure but active (IC is strongest here)",
  },
} as const;

const ENGINE_ICONS: Record<string, typeof Zap> = {
  largecap: Repeat,
  midcap: Zap,
};

function EngineCard({
  name,
  engine,
  allocation,
}: {
  name: string;
  engine: MultiEngineStatus["engines"][string];
  allocation: number;
}) {
  const Icon = ENGINE_ICONS[name] || Zap;

  return (
    <div
      className={cn(
        "rounded-lg border p-3 space-y-2",
        engine.active
          ? "border-profit/20 bg-profit/5"
          : "border-border/50 bg-muted/20 opacity-60",
      )}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Icon className={cn("h-3.5 w-3.5", engine.active ? "text-profit" : "text-muted-foreground")} />
          <span className="text-xs font-semibold capitalize">{name}</span>
        </div>
        <Badge
          variant="outline"
          className={cn(
            "text-[10px]",
            engine.active
              ? "text-profit border-profit/20"
              : "text-muted-foreground border-border/60",
          )}
        >
          {engine.active ? `${allocation.toFixed(0)}%` : "OFF"}
        </Badge>
      </div>

      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <p className="text-[10px] text-muted-foreground">Capital</p>
          <p className="text-xs font-medium">{formatCurrency(engine.capital)}</p>
        </div>
        <div>
          <p className="text-[10px] text-muted-foreground">P&L</p>
          <PnlText value={engine.pnl} className="text-xs font-medium" />
        </div>
        <div>
          <p className="text-[10px] text-muted-foreground">WR</p>
          <p className="text-xs font-medium">
            {engine.total_trades > 0 ? `${engine.win_rate.toFixed(0)}%` : "—"}
          </p>
        </div>
      </div>

      <div className="flex items-center justify-between text-[10px] text-muted-foreground/60">
        <span>{engine.open_positions} open</span>
        <span>{engine.total_trades} trades</span>
      </div>
    </div>
  );
}

export function RegimeStatus() {
  const { data: status } = useApi(api.multiEngineStatus, { pollInterval: 15000 });

  if (!status) return null;

  const regime = REGIME_CONFIG[status.regime] || REGIME_CONFIG.NEUTRAL;
  const RegimeIcon = regime.icon;

  return (
    <Card>
      <CardHeader className="pb-2 px-4 pt-3">
        <CardTitle className="text-sm font-medium flex items-center gap-1.5">
          <Banknote className="h-3.5 w-3.5" />
          Multi-Engine System
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-4 space-y-3">
        {/* Regime Banner */}
        <div className={cn("rounded-lg border p-3", regime.border, regime.bg)}>
          <div className="flex items-center gap-2 mb-1">
            <RegimeIcon className={cn("h-4 w-4", regime.color)} />
            <span className={cn("text-sm font-semibold", regime.color)}>
              {regime.label}
            </span>
            {status.regime_detail.pending && (
              <Badge variant="outline" className="text-[10px] text-warning border-warning/20">
                → {status.regime_detail.pending} ({status.regime_detail.pending_days}d)
              </Badge>
            )}
          </div>
          <p className="text-[11px] text-muted-foreground">{regime.desc}</p>
        </div>

        {/* Allocation Bar */}
        <div>
          <p className="text-[10px] text-muted-foreground/60 mb-1 uppercase tracking-wider">
            Capital Allocation
          </p>
          <div className="h-2 rounded-full bg-muted overflow-hidden flex">
            {Object.entries(status.allocation).map(([key, pct]) => {
              if (pct === 0) return null;
              const colors: Record<string, string> = {
                largecap: "bg-blue-500",
                midcap: "bg-amber-500",
                cash: "bg-muted-foreground/20",
              };
              return (
                <div
                  key={key}
                  className={cn("h-full", colors[key] || "bg-muted-foreground/20")}
                  style={{ width: `${pct}%` }}
                />
              );
            })}
          </div>
          <div className="flex gap-3 mt-1">
            {Object.entries(status.allocation).map(([key, pct]) => (
              <span key={key} className="text-[10px] text-muted-foreground/60">
                <span className="capitalize">{key}</span> {pct.toFixed(0)}%
              </span>
            ))}
          </div>
        </div>

        {/* Engine Cards */}
        <div className="grid grid-cols-2 gap-2">
          {Object.entries(status.engines).map(([name, engine]) => (
            <EngineCard
              key={name}
              name={name}
              engine={engine}
              allocation={status.allocation[name] || 0}
            />
          ))}
        </div>

        {/* Portfolio Summary */}
        <div className="flex items-center justify-between pt-2 border-t border-border/50">
          <div>
            <p className="text-[10px] text-muted-foreground">Total P&L</p>
            <PnlText
              value={status.total_pnl}
              percent={status.total_pnl_pct}
              className="text-sm font-semibold"
            />
          </div>
          <div className="text-center">
            <p className="text-[10px] text-muted-foreground">Rolling IC</p>
            <p className={cn(
              "text-sm font-semibold",
              status.rolling_ic === null ? "text-muted-foreground" :
              status.rolling_ic > 0 ? "text-profit" :
              status.rolling_ic > -0.02 ? "text-warning" : "text-loss"
            )}>
              {status.rolling_ic !== null ? status.rolling_ic.toFixed(3) : "—"}
            </p>
          </div>
          <div className="text-right">
            <p className="text-[10px] text-muted-foreground">Cash</p>
            <p className="text-sm font-medium">{formatCurrency(status.cash)}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
