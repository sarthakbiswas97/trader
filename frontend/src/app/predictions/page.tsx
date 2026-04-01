"use client";

import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  Loader2,
  ShieldAlert,
  Eye,
  Lock,
  RefreshCw,
  TrendingDown,
  Radio,
  Clock,
  ChevronDown,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { StatCard } from "@/components/stat-card";
import { type ReversalStock, type ReversalResponse, api } from "@/lib/api";
import { cn } from "@/lib/utils";

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

function DataSourceBanner({ data }: { data: ReversalResponse }) {
  const { data_source } = data;
  const isLive = data_source.live_prices;

  if (isLive) {
    return (
      <div className="rounded-lg border border-profit/20 bg-profit/5 px-4 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Radio className="h-4 w-4 text-profit animate-pulse" />
            <div>
              <p className="text-sm font-medium text-profit">Live Market Data</p>
              <p className="text-xs text-profit/70">
                Real-time prices from Zerodha
              </p>
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            <Clock className="h-3 w-3 inline mr-1" />
            {new Date(data.summary.generated_at).toLocaleTimeString("en-IN", {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border/50 bg-muted/30 px-4 py-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Clock className="h-4 w-4 text-muted-foreground" />
          <div>
            <p className="text-sm font-medium">
              {data_source.market_open ? "Market Open — Connecting..." : "Market Closed"}
            </p>
            <p className="text-xs text-muted-foreground">
              {data_source.data_date
                ? `Prices from ${new Date(data_source.data_date + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })} close`
                : "Using last available data"}
            </p>
          </div>
        </div>
        <p className="text-xs text-muted-foreground/60">
          {!data_source.market_open && "Next scan at market open (9:20 AM IST)"}
        </p>
      </div>
    </div>
  );
}

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

        <div className="space-y-1.5 mb-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">Reversal Score</span>
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

        <div className="grid grid-cols-3 gap-2 text-center">
          {[
            { label: "5d", value: stock.ret_5d },
            { label: "10d", value: stock.ret_10d },
            { label: "21d", value: stock.ret_21d },
          ].map((r) => (
            <div key={r.label}>
              <p className="text-[10px] text-muted-foreground">{r.label}</p>
              <p
                className={cn(
                  "text-xs font-medium",
                  r.value < 0 ? "text-loss" : "text-profit",
                )}
              >
                {r.value > 0 ? "+" : ""}
                {r.value.toFixed(1)}%
              </p>
            </div>
          ))}
        </div>

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
          <div className="flex items-center gap-6">
            <div>
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Regime</p>
              <p className="text-lg font-bold">{regime.current}</p>
            </div>
            <div>
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Capital Deployed</p>
              <p className="text-lg font-bold">{regime.total_exposure}%</p>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1">
            {regime.pending && (
              <Badge variant="outline" className="text-[10px]">
                Shifting → {regime.pending} ({regime.pending_days}/2 days)
              </Badge>
            )}
            {killSwitch.ic_killed && (
              <Badge variant="outline" className="text-[10px] text-loss border-loss/20">
                Kill Switch Active (IC: {killSwitch.rolling_ic?.toFixed(4)})
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
  const [unchanged, setUnchanged] = useState(false);
  const [showAllWatch, setShowAllWatch] = useState(false);
  const [prevDataHash, setPrevDataHash] = useState<string>("");

  const loadScores = async () => {
    setLoading(true);
    setError(null);
    setUnchanged(false);
    try {
      const result = await api.reversalScores();

      // Check if data actually changed
      const hash = JSON.stringify(result.stocks.map((s) => s.symbol + s.score));
      if (hash === prevDataHash && prevDataHash !== "") {
        setUnchanged(true);
      }
      setPrevDataHash(hash);
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load scores");
    }
    setLoading(false);
  };

  useEffect(() => {
    loadScores();
  }, []);

  const buyStocks = data?.stocks.filter((s) => s.action === "BUY") ?? [];
  const heldStocks = data?.stocks.filter((s) => s.action === "HELD") ?? [];
  const skipStocks = data?.stocks.filter((s) => s.action === "SKIP") ?? [];
  const blockedStocks = data?.stocks.filter((s) => s.action === "BLOCKED") ?? [];
  const watchStocks = data?.stocks.filter((s) => s.action === "WATCH") ?? [];

  return (
    <div className="px-6 py-6 space-y-5 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">
            Reversal Scanner
          </h1>
          <p className="text-xs text-muted-foreground">
            What the trading engine sees — stocks ranked by how oversold they are
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
          {loading ? "Scanning..." : data ? "Rescan" : "Scan Now"}
        </button>
      </div>

      {/* Data Source Banner */}
      {data && <DataSourceBanner data={data} />}

      {/* Unchanged notice */}
      {unchanged && !loading && (
        <div className="text-xs text-muted-foreground/60 text-center py-1">
          No changes since last scan — prices haven&apos;t updated
        </div>
      )}

      {/* Error */}
      {error && (
        <Card className="border-yellow-500/20 bg-yellow-500/5">
          <CardContent className="px-4 py-3 space-y-1">
            <p className="text-sm font-medium text-yellow-500">Scanner unavailable</p>
            <p className="text-xs text-muted-foreground">
              {error.includes("401") || error.includes("auth")
                ? "Broker not connected. Authenticate first."
                : "Market data not available. Try during market hours (9:15 AM - 3:30 PM IST)."}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Regime Banner */}
      {data && <RegimeBanner regime={data.regime} killSwitch={data.kill_switch} />}

      {/* Summary Stats */}
      {data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
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
          />
          <StatCard
            title="Blocked / Skipped"
            value={String(data.summary.blocked + skipStocks.length)}
            trend={data.summary.blocked > 0 ? "loss" : "neutral"}
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
          <p className="text-sm font-medium">Reversal scanner ready</p>
          <p className="text-xs mt-1 text-center max-w-sm">
            Click &quot;Scan Now&quot; to rank all NIFTY 100 stocks by how
            oversold they are. Works best during market hours.
          </p>
        </div>
      )}

      {/* Stock Cards */}
      {data && (
        <div className="space-y-6">
          {/* BUY */}
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

          {/* HELD */}
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
                Blocked ({blockedStocks.length})
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
                Skipped ({skipStocks.length})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {skipStocks.map((s) => (
                  <ReversalStockCard key={s.symbol} stock={s} />
                ))}
              </div>
            </div>
          )}

          {/* WATCHING — collapsible */}
          {watchStocks.length > 0 && (
            <div>
              <button
                onClick={() => setShowAllWatch(!showAllWatch)}
                className="text-sm font-medium text-muted-foreground mb-3 flex items-center gap-1.5 hover:text-foreground transition-colors"
              >
                <ChevronDown
                  className={cn(
                    "h-4 w-4 transition-transform",
                    showAllWatch && "rotate-180",
                  )}
                />
                Watching ({watchStocks.length})
                <span className="text-xs font-normal text-muted-foreground/60">
                  — ranked but below top cutoff
                </span>
              </button>
              {showAllWatch && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {watchStocks.map((s) => (
                    <ReversalStockCard key={s.symbol} stock={s} />
                  ))}
                </div>
              )}
              {!showAllWatch && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {watchStocks.slice(0, 3).map((s) => (
                    <ReversalStockCard key={s.symbol} stock={s} />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
