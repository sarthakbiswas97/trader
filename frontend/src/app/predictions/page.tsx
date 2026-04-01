"use client";

import { useEffect, useState } from "react";
import {
  BrainCircuit,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  Loader2,
  ShieldAlert,
  TrendingDown,
  Eye,
  Lock,
  RefreshCw,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { StatCard } from "@/components/stat-card";
import { type ReversalStock, type ReversalResponse, api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { MarketStatusBanner } from "@/components/market-status";

const ACTION_CONFIG = {
  BUY: {
    icon: ArrowUpRight,
    color: "text-profit",
    border: "border-profit/20",
    bg: "bg-profit/5",
    badge: "bg-profit/10 text-profit border-profit/20",
    label: "Would Buy",
  },
  HELD: {
    icon: Eye,
    color: "text-blue-400",
    border: "border-blue-400/20",
    bg: "bg-blue-400/5",
    badge: "bg-blue-400/10 text-blue-400 border-blue-400/20",
    label: "In Portfolio",
  },
  WATCH: {
    icon: Minus,
    color: "text-muted-foreground",
    border: "border-border/50",
    bg: "",
    badge: "text-muted-foreground border-border/60",
    label: "Watching",
  },
  SKIP: {
    icon: ShieldAlert,
    color: "text-yellow-500",
    border: "border-yellow-500/20",
    bg: "bg-yellow-500/5",
    badge: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20",
    label: "Skipped",
  },
  BLOCKED: {
    icon: Lock,
    color: "text-loss",
    border: "border-loss/20",
    bg: "bg-loss/5",
    badge: "bg-loss/10 text-loss border-loss/20",
    label: "Blocked",
  },
} as const;

function ReversalStockCard({ stock }: { stock: ReversalStock }) {
  const config = ACTION_CONFIG[stock.action];
  const Icon = config.icon;

  return (
    <Card className={cn("transition-all", config.border, config.bg)}>
      <CardContent className="px-4 py-3">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Icon className={cn("h-4 w-4", config.color)} />
            <span className="text-sm font-semibold">{stock.symbol}</span>
            <Badge variant="outline" className="text-[10px]">
              #{stock.rank} {stock.universe}
            </Badge>
          </div>
          <Badge variant="outline" className={cn("text-xs", config.badge)}>
            {config.label}
          </Badge>
        </div>

        {/* Reversal Score Bar */}
        <div className="space-y-1.5 mb-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              Reversal Score
            </span>
            <span className="text-xs font-semibold">
              {(stock.score * 100).toFixed(0)}%
            </span>
          </div>
          <div className="w-full h-2 rounded-full bg-muted overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all",
                stock.score >= 0.8
                  ? "bg-profit"
                  : stock.score >= 0.5
                    ? "bg-yellow-500"
                    : "bg-muted-foreground/30",
              )}
              style={{ width: `${stock.score * 100}%` }}
            />
          </div>
        </div>

        {/* Returns */}
        <div className="grid grid-cols-3 gap-2 text-center">
          <div>
            <p className="text-[10px] text-muted-foreground">5d</p>
            <p
              className={cn(
                "text-xs font-medium",
                stock.ret_5d < 0 ? "text-loss" : "text-profit",
              )}
            >
              {stock.ret_5d > 0 ? "+" : ""}
              {stock.ret_5d.toFixed(1)}%
            </p>
          </div>
          <div>
            <p className="text-[10px] text-muted-foreground">10d</p>
            <p
              className={cn(
                "text-xs font-medium",
                stock.ret_10d < 0 ? "text-loss" : "text-profit",
              )}
            >
              {stock.ret_10d > 0 ? "+" : ""}
              {stock.ret_10d.toFixed(1)}%
            </p>
          </div>
          <div>
            <p className="text-[10px] text-muted-foreground">21d</p>
            <p
              className={cn(
                "text-xs font-medium",
                stock.ret_21d < 0 ? "text-loss" : "text-profit",
              )}
            >
              {stock.ret_21d > 0 ? "+" : ""}
              {stock.ret_21d.toFixed(1)}%
            </p>
          </div>
        </div>

        {/* Price and Reason */}
        <div className="mt-2 pt-2 border-t border-border/50 flex items-center justify-between">
          <span className="text-[11px] text-muted-foreground/60">
            {stock.reason}
          </span>
          <span className="text-xs font-medium">₹{stock.price.toLocaleString()}</span>
        </div>
      </CardContent>
    </Card>
  );
}

function RegimeBanner({
  regime,
  killSwitch,
}: {
  regime: ReversalResponse["regime"];
  killSwitch: ReversalResponse["kill_switch"];
}) {
  const regimeColor =
    regime.current === "BULL"
      ? "text-profit border-profit/20 bg-profit/5"
      : regime.current === "WEAK"
        ? "text-loss border-loss/20 bg-loss/5"
        : "text-yellow-500 border-yellow-500/20 bg-yellow-500/5";

  return (
    <Card className={cn("border", regimeColor)}>
      <CardContent className="px-4 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div>
              <p className="text-xs text-muted-foreground">Market Regime</p>
              <p className="text-lg font-bold">{regime.current}</p>
            </div>
            <div className="text-right">
              <p className="text-xs text-muted-foreground">Capital Deployed</p>
              <p className="text-lg font-bold">{regime.total_exposure}%</p>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1">
            {regime.pending && (
              <Badge variant="outline" className="text-[10px]">
                Pending → {regime.pending} ({regime.pending_days}/2 days)
              </Badge>
            )}
            {killSwitch.ic_killed && (
              <Badge
                variant="outline"
                className="text-[10px] text-loss border-loss/20"
              >
                Kill Switch Active (IC: {killSwitch.rolling_ic?.toFixed(4)})
              </Badge>
            )}
            {killSwitch.rolling_ic !== null && !killSwitch.ic_killed && (
              <Badge variant="outline" className="text-[10px]">
                IC: {killSwitch.rolling_ic?.toFixed(4)}
              </Badge>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function PredictionsPage() {
  const [data, setData] = useState<ReversalResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadScores = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.reversalScores();
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load scores");
    }
    setLoading(false);
  };

  // Load on mount
  useEffect(() => {
    loadScores();
  }, []);

  const buyStocks = data?.stocks.filter((s) => s.action === "BUY") ?? [];
  const heldStocks = data?.stocks.filter((s) => s.action === "HELD") ?? [];
  const skipStocks = data?.stocks.filter((s) => s.action === "SKIP") ?? [];
  const blockedStocks =
    data?.stocks.filter((s) => s.action === "BLOCKED") ?? [];
  const watchStocks = data?.stocks.filter((s) => s.action === "WATCH") ?? [];

  return (
    <div className="px-6 py-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">
            Reversal Scanner
          </h1>
          <p className="text-xs text-muted-foreground">
            Cross-sectional oversold ranking for NIFTY 100 — what the trading
            engine sees
          </p>
        </div>
        <button
          onClick={loadScores}
          disabled={loading}
          className={cn(
            "flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-md transition-colors",
            "bg-foreground text-background hover:opacity-80",
            loading && "opacity-50",
          )}
        >
          {loading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
          {loading ? "Scanning..." : "Scan Now"}
        </button>
      </div>

      {/* Market Status */}
      <MarketStatusBanner />

      {/* Error */}
      {error && (
        <Card className="border-loss/20 bg-loss/5">
          <CardContent className="px-4 py-3 text-sm text-loss">
            {error}
          </CardContent>
        </Card>
      )}

      {/* Regime Banner */}
      {data && (
        <RegimeBanner regime={data.regime} killSwitch={data.kill_switch} />
      )}

      {/* Summary Stats */}
      {data && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <StatCard
            title="Stocks Scanned"
            value={String(data.summary.total_stocks)}
          />
          <StatCard
            title="Buy Signals"
            value={String(data.summary.buy_signals)}
            trend={data.summary.buy_signals > 0 ? "profit" : "neutral"}
          />
          <StatCard
            title="In Portfolio"
            value={String(data.summary.held_positions)}
            trend="neutral"
          />
          <StatCard
            title="Blocked"
            value={String(data.summary.blocked)}
            trend={data.summary.blocked > 0 ? "loss" : "neutral"}
          />
          <StatCard
            title="Regime"
            value={data.regime.current}
            trend={
              data.regime.current === "BULL"
                ? "profit"
                : data.regime.current === "WEAK"
                  ? "loss"
                  : "neutral"
            }
          />
        </div>
      )}

      {/* Loading */}
      {loading && !data && (
        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground/50">
          <Loader2 className="h-8 w-8 animate-spin mb-3" />
          <p className="text-sm">Scanning 100 stocks...</p>
        </div>
      )}

      {/* Empty State */}
      {!loading && !data && !error && (
        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground/50">
          <TrendingDown className="h-10 w-10 mb-3" />
          <p className="text-sm font-medium">No scan results</p>
          <p className="text-xs mt-1">Click &quot;Scan Now&quot; to analyze NIFTY 100</p>
        </div>
      )}

      {/* Stock Cards — grouped by action */}
      {data && (
        <div className="space-y-6">
          {/* BUY signals */}
          {buyStocks.length > 0 && (
            <div>
              <h2 className="text-sm font-medium text-profit mb-3 flex items-center gap-1.5">
                <ArrowUpRight className="h-4 w-4" />
                Would Buy ({buyStocks.length})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {buyStocks.map((s) => (
                  <ReversalStockCard key={s.symbol} stock={s} />
                ))}
              </div>
            </div>
          )}

          {/* HELD positions */}
          {heldStocks.length > 0 && (
            <div>
              <h2 className="text-sm font-medium text-blue-400 mb-3 flex items-center gap-1.5">
                <Eye className="h-4 w-4" />
                In Portfolio ({heldStocks.length})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {heldStocks.map((s) => (
                  <ReversalStockCard key={s.symbol} stock={s} />
                ))}
              </div>
            </div>
          )}

          {/* BLOCKED */}
          {blockedStocks.length > 0 && (
            <div>
              <h2 className="text-sm font-medium text-loss mb-3 flex items-center gap-1.5">
                <Lock className="h-4 w-4" />
                Blocked by Regime/Kill Switch ({blockedStocks.length})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {blockedStocks.slice(0, 6).map((s) => (
                  <ReversalStockCard key={s.symbol} stock={s} />
                ))}
              </div>
              {blockedStocks.length > 6 && (
                <p className="text-xs text-muted-foreground mt-2">
                  +{blockedStocks.length - 6} more blocked
                </p>
              )}
            </div>
          )}

          {/* SKIP */}
          {skipStocks.length > 0 && (
            <div>
              <h2 className="text-sm font-medium text-yellow-500 mb-3 flex items-center gap-1.5">
                <ShieldAlert className="h-4 w-4" />
                Skipped — Entry Filter ({skipStocks.length})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {skipStocks.map((s) => (
                  <ReversalStockCard key={s.symbol} stock={s} />
                ))}
              </div>
            </div>
          )}

          {/* WATCH — top 20 only */}
          {watchStocks.length > 0 && (
            <div>
              <h2 className="text-sm font-medium text-muted-foreground mb-3 flex items-center gap-1.5">
                <Minus className="h-4 w-4" />
                Watching ({watchStocks.length})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {watchStocks.slice(0, 12).map((s) => (
                  <ReversalStockCard key={s.symbol} stock={s} />
                ))}
              </div>
              {watchStocks.length > 12 && (
                <p className="text-xs text-muted-foreground mt-2">
                  +{watchStocks.length - 12} more watching
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
