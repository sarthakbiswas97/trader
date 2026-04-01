"use client";

import { useEffect, useRef, useState } from "react";
import {
  Wallet,
  TrendingUp,
  BarChart3,
  Activity,
  ShieldCheck,
  RefreshCw,
  Flame,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { StatCard } from "@/components/stat-card";
import { PnlText, formatCurrency } from "@/components/pnl-text";
import { useApi } from "@/hooks/use-api";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { MarketStatusBanner } from "@/components/market-status";
import { RegimeStatus } from "@/components/regime-status";
import { PipelineComparisonPanel } from "@/components/pipeline-comparison";
import type {
  PositionsResponse,
  BotStatus,
  HealthResponse,
} from "@/lib/api";

function BrokerModeBanner({ health }: { health: HealthResponse | null }) {
  const mode = health?.components?.broker_mode as string | undefined;
  const authenticated = health?.components?.broker_authenticated;

  if (mode === "live_data") {
    return (
      <div className="rounded-lg border border-profit/20 bg-profit/5 px-4 py-2 flex items-center gap-2">
        <span className="h-2 w-2 rounded-full bg-profit animate-pulse" />
        <p className="text-xs font-medium text-profit">
          Paper Trading Mode — Live market data from Zerodha. No real trades executed.
        </p>
      </div>
    );
  }

  if (mode === "paper_only" || (authenticated && mode !== "live_data")) {
    return (
      <div className="rounded-lg border border-warning/30 bg-warning/5 px-4 py-2.5 flex items-center gap-2">
        <span className="h-2 w-2 rounded-full bg-warning animate-pulse" />
        <div>
          <p className="text-xs font-medium text-warning">
            Paper Trading Mode — Kite session expired
          </p>
          <p className="text-[11px] text-muted-foreground mt-0.5">
            Showing last known positions and data. Live market data will resume when the admin authenticates with Zerodha.
          </p>
        </div>
      </div>
    );
  }

  // Not connected at all — auto-connect will fire
  return (
    <div className="rounded-lg border border-muted bg-muted/30 px-4 py-2 flex items-center gap-2">
      <span className="h-2 w-2 rounded-full bg-muted-foreground/30 animate-pulse" />
      <p className="text-xs text-muted-foreground">
        Connecting to paper trading...
      </p>
    </div>
  );
}

function ConnectionBanner({
  health,
  onConnect,
  connecting,
}: {
  health: HealthResponse | null;
  onConnect: () => void;
  connecting: boolean;
}) {
  const connected = health?.components?.broker_authenticated;
  if (connected) return null;

  return (
    <div className="rounded-lg border border-warning/30 bg-warning/5 px-4 py-3 flex items-center justify-between">
      <div>
        <p className="text-sm font-medium">Broker Not Connected</p>
        <p className="text-xs text-muted-foreground">
          Connecting to paper trading mode...
        </p>
      </div>
      <button
        onClick={onConnect}
        disabled={connecting}
        className="text-xs font-medium px-3 py-1.5 rounded-md bg-foreground text-background hover:opacity-80 transition-colors disabled:opacity-30"
      >
        {connecting ? "Connecting..." : "Connect"}
      </button>
    </div>
  );
}

function PositionsTable({ data }: { data: PositionsResponse | null }) {
  if (!data || data.positions.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-muted-foreground/50">
        <TrendingUp className="h-8 w-8 mb-2" />
        <p className="text-sm">No open positions</p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="text-xs">Symbol</TableHead>
          <TableHead className="text-xs text-right">Qty</TableHead>
          <TableHead className="text-xs text-right">Avg Price</TableHead>
          <TableHead className="text-xs text-right">Current</TableHead>
          <TableHead className="text-xs text-right">P&L</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.positions.map((p) => (
          <TableRow key={p.symbol}>
            <TableCell className="text-sm font-medium">{p.symbol}</TableCell>
            <TableCell className="text-sm text-right">{p.quantity}</TableCell>
            <TableCell className="text-sm text-right">
              {formatCurrency(p.avg_price)}
            </TableCell>
            <TableCell className="text-sm text-right">
              {formatCurrency(p.current_price)}
            </TableCell>
            <TableCell className="text-right">
              <PnlText value={p.pnl} percent={p.pnl_percent} className="text-sm" />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function BotStatusBadge({ status }: { status: BotStatus | null }) {
  if (!status) return null;

  const variants: Record<string, { label: string; className: string }> = {
    running: {
      label: "Running",
      className: "bg-profit/10 text-profit border-profit/20 hover:bg-profit/10",
    },
    stopped: {
      label: "Stopped",
      className: "bg-muted text-muted-foreground border-border/60 hover:bg-muted",
    },
    error: {
      label: "Error",
      className: "bg-loss/10 text-loss border-loss/20 hover:bg-loss/10",
    },
  };

  const v = variants[status.status] || variants.stopped;

  return (
    <Badge variant="outline" className={v.className}>
      {status.status === "running" && (
        <span className="h-1.5 w-1.5 rounded-full bg-profit mr-1.5 animate-pulse" />
      )}
      {v.label}
    </Badge>
  );
}

function StatusRow({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div className="flex items-center gap-1.5">
        <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-profit" : "bg-muted-foreground/30"}`} />
        <span className="text-xs font-medium">{value}</span>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { data: health, refresh: refreshHealth } = useApi(api.health, { pollInterval: 10000 });
  const { data: portfolio, refresh: refreshPortfolio } = useApi(api.portfolioSummary, { immediate: false });
  const { data: positions, refresh: refreshPositions } = useApi(api.positions, { immediate: false });
  const { data: botStatus } = useApi(api.botStatus, { pollInterval: 5000 });
  const { data: watchlist } = useApi(api.botWatchlist, { pollInterval: 10000 });

  const connected = health?.components?.broker_authenticated;
  const hasFetched = useRef(false);
  const autoConnectAttempted = useRef(false);
  const [connecting, setConnecting] = useState(false);

  const handleConnect = async () => {
    setConnecting(true);
    try {
      await api.connect(true);
      await refreshHealth();
      await refreshPortfolio();
      await refreshPositions();
    } catch {
      // Connection failed - banner stays visible
    } finally {
      setConnecting(false);
    }
  };

  // Auto-connect in paper mode on first visit
  useEffect(() => {
    if (health && !connected && !autoConnectAttempted.current) {
      autoConnectAttempted.current = true;
      handleConnect();
    }
  }, [health, connected]);

  // Auto-fetch portfolio once when we detect connection
  useEffect(() => {
    if (connected && !hasFetched.current) {
      hasFetched.current = true;
      refreshPortfolio();
      refreshPositions();
    }
  }, [connected, refreshPortfolio, refreshPositions]);

  return (
    <div className="px-6 py-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Dashboard</h1>
          <p className="text-xs text-muted-foreground">Portfolio overview and trading activity</p>
        </div>
        <div className="flex items-center gap-3">
          <BotStatusBadge status={botStatus} />
          <button
            onClick={() => {
              refreshHealth();
              if (connected) {
                refreshPortfolio();
                refreshPositions();
              }
            }}
            className="h-7 w-7 rounded-md flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
            aria-label="Refresh"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Broker Mode Banner */}
      <BrokerModeBanner health={health} />

      {/* Market Status */}
      <MarketStatusBanner />

      {/* Connection Banner (only shows briefly before auto-connect) */}
      <ConnectionBanner health={health} onConnect={handleConnect} connecting={connecting} />

      {/* Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          title="Total Capital"
          value={formatCurrency(portfolio?.total_capital ?? 100000)}
          icon={Wallet}
        />
        <StatCard
          title="Total P&L"
          value={formatCurrency(portfolio?.total_pnl ?? 0)}
          subtitle={
            portfolio
              ? `${portfolio.total_pnl_percent >= 0 ? "+" : ""}${portfolio.total_pnl_percent.toFixed(2)}%`
              : undefined
          }
          icon={TrendingUp}
          trend={
            (portfolio?.total_pnl ?? 0) > 0
              ? "profit"
              : (portfolio?.total_pnl ?? 0) < 0
                ? "loss"
                : "neutral"
          }
        />
        <StatCard
          title="Open Positions"
          value={String(portfolio?.open_positions ?? 0)}
          subtitle={portfolio ? `${formatCurrency(portfolio.invested_value)} invested` : undefined}
          icon={BarChart3}
        />
        <StatCard
          title="Bot Cycles"
          value={String(botStatus?.cycle_count ?? 0)}
          subtitle={
            botStatus?.last_cycle
              ? `Last: ${new Date(botStatus.last_cycle).toLocaleTimeString()}`
              : "Not running"
          }
          icon={Activity}
        />
      </div>

      {/* Multi-Engine Regime Status */}
      <RegimeStatus />

      {/* A/B Pipeline Comparison */}
      <PipelineComparisonPanel />

      {/* Hot Watchlist */}
      {watchlist && watchlist.tier1_count > 0 && (
        <Card>
          <CardHeader className="pb-2 px-4 pt-3">
            <CardTitle className="text-sm font-medium flex items-center gap-1.5">
              <Flame className="h-3.5 w-3.5 text-warning" />
              Hot Watchlist
              <Badge variant="outline" className="text-[11px] ml-1 text-warning border-warning/20">
                {watchlist.tier1_count} / {watchlist.total_symbols}
              </Badge>
              <span className="text-[11px] text-muted-foreground/60 font-normal ml-auto">
                Scanned every 2 min
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <div className="flex flex-wrap gap-2">
              {watchlist.watchlist.map((w) => (
                <div
                  key={w.symbol}
                  className={cn(
                    "flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs",
                    w.direction === "UP" && "border-profit/20 bg-profit/5",
                    w.direction === "DOWN" && "border-loss/20 bg-loss/5",
                    w.direction === "NEUTRAL" && "border-border/60 bg-muted/30",
                  )}
                >
                  {w.direction === "UP" ? (
                    <ArrowUpRight className="h-3 w-3 text-profit" />
                  ) : w.direction === "DOWN" ? (
                    <ArrowDownRight className="h-3 w-3 text-loss" />
                  ) : (
                    <Minus className="h-3 w-3 text-muted-foreground" />
                  )}
                  <span className="font-medium">{w.symbol}</span>
                  <span className="text-muted-foreground/60">
                    {(w.confidence * 100).toFixed(0)}%
                  </span>
                  {w.has_position && (
                    <span className="h-1.5 w-1.5 rounded-full bg-profit" />
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Positions */}
        <Card className="lg:col-span-2">
          <CardHeader className="pb-2 px-4 pt-3">
            <CardTitle className="text-sm font-medium">Open Positions</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <PositionsTable data={positions ?? null} />
          </CardContent>
        </Card>

        {/* System Status */}
        <Card>
          <CardHeader className="pb-2 px-4 pt-3">
            <CardTitle className="text-sm font-medium flex items-center gap-1.5">
              <ShieldCheck className="h-3.5 w-3.5" />
              System Status
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3 space-y-3">
            <div className="space-y-2">
              <StatusRow label="API" value={health?.components?.api ? "Online" : "Offline"} ok={!!health?.components?.api} />
              <StatusRow label="Broker" value={connected ? "Connected" : "Disconnected"} ok={!!connected} />
              <StatusRow label="ML Model" value={health?.components?.model_available ? "Loaded" : "Not Found"} ok={!!health?.components?.model_available} />
              <StatusRow label="Session" value={health?.components?.session_valid ? "Valid" : "Expired"} ok={!!health?.components?.session_valid} />
              <StatusRow label="Bot" value={health?.components?.bot_running ? "Running" : "Stopped"} ok={!!health?.components?.bot_running} />
            </div>

            {portfolio && (
              <div className="border-t border-border/50 pt-3 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">Available Cash</span>
                  <span className="text-xs font-medium">{formatCurrency(portfolio.available_cash)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">Realized P&L</span>
                  <PnlText value={portfolio.realized_pnl} className="text-xs font-medium" />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">Unrealized P&L</span>
                  <PnlText value={portfolio.unrealized_pnl} className="text-xs font-medium" />
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
