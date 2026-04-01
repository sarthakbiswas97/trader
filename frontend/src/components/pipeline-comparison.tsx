"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { PnlText, formatCurrency } from "@/components/pnl-text";
import { api, type PipelineComparison, type PipelineDetail } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Loader2, FlaskConical, Clock, TrendingUp } from "lucide-react";

function PipelineCard({
  id,
  data,
  selected,
  onSelect,
}: {
  id: string;
  data: PipelineComparison[string];
  selected: boolean;
  onSelect: () => void;
}) {
  const pnlPositive = data.total_pnl >= 0;

  return (
    <button
      onClick={onSelect}
      className={cn(
        "w-full text-left rounded-lg border p-4 transition-all",
        selected
          ? "border-foreground/30 bg-foreground/5"
          : "border-border/50 hover:border-border",
      )}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Badge
            variant="outline"
            className={cn(
              "text-xs font-bold",
              selected && "border-foreground/30",
            )}
          >
            {id}
          </Badge>
          <span className="text-sm font-medium">{data.label}</span>
        </div>
        {selected && (
          <span className="h-2 w-2 rounded-full bg-foreground animate-pulse" />
        )}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <p className="text-[10px] text-muted-foreground uppercase">P&L</p>
          <p
            className={cn(
              "text-lg font-bold",
              pnlPositive ? "text-profit" : "text-loss",
            )}
          >
            {pnlPositive ? "+" : ""}
            {formatCurrency(data.total_pnl)}
          </p>
          <p
            className={cn(
              "text-xs",
              pnlPositive ? "text-profit/70" : "text-loss/70",
            )}
          >
            {pnlPositive ? "+" : ""}
            {data.pnl_pct.toFixed(2)}%
          </p>
        </div>
        <div>
          <p className="text-[10px] text-muted-foreground uppercase">
            Portfolio
          </p>
          <p className="text-lg font-bold">
            {formatCurrency(data.portfolio_value)}
          </p>
          <p className="text-xs text-muted-foreground">
            of {formatCurrency(data.capital)}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 mt-3 pt-3 border-t border-border/50">
        <div className="text-center">
          <p className="text-[10px] text-muted-foreground">Trades</p>
          <p className="text-sm font-medium">{data.total_trades}</p>
        </div>
        <div className="text-center">
          <p className="text-[10px] text-muted-foreground">Win Rate</p>
          <p className="text-sm font-medium">{data.win_rate.toFixed(0)}%</p>
        </div>
        <div className="text-center">
          <p className="text-[10px] text-muted-foreground">Scans</p>
          <p className="text-sm font-medium">{data.scan_count}</p>
        </div>
      </div>

      {data.last_scan && (
        <p className="text-[10px] text-muted-foreground mt-2 flex items-center gap-1">
          <Clock className="h-3 w-3" />
          Last scan: {new Date(data.last_scan).toLocaleTimeString("en-IN")}
        </p>
      )}
    </button>
  );
}

function PipelinePositions({ detail }: { detail: PipelineDetail }) {
  if (detail.positions.length === 0) {
    return (
      <p className="text-xs text-muted-foreground py-4 text-center">
        No open positions
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {detail.positions.map((pos) => (
        <div
          key={`${pos.symbol}-${pos.entry_date}`}
          className="flex items-center justify-between px-3 py-2 rounded border border-border/50"
        >
          <div>
            <span className="text-sm font-medium">{pos.symbol}</span>
            <span className="text-xs text-muted-foreground ml-2">
              {pos.engine}
            </span>
          </div>
          <div className="text-right">
            <p className="text-xs font-medium">
              ₹{pos.entry_price.toFixed(0)} × {pos.quantity}
            </p>
            <p className="text-[10px] text-muted-foreground">
              Score: {(pos.score * 100).toFixed(0)}% | {pos.entry_date}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

export function PipelineComparisonPanel() {
  const [comparison, setComparison] = useState<PipelineComparison | null>(null);
  const [selectedPipeline, setSelectedPipeline] = useState<string>("A");
  const [detail, setDetail] = useState<PipelineDetail | null>(null);
  const [loading, setLoading] = useState(true);

  // Load comparison data
  useEffect(() => {
    api
      .pipelineCompare()
      .then((d) => setComparison(d.comparison))
      .catch(() => {})
      .finally(() => setLoading(false));

    const interval = setInterval(() => {
      api
        .pipelineCompare()
        .then((d) => setComparison(d.comparison))
        .catch(() => {});
    }, 30000); // Refresh every 30s

    return () => clearInterval(interval);
  }, []);

  // Load detail when pipeline selected
  useEffect(() => {
    api
      .pipelineDetail(selectedPipeline)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [selectedPipeline, comparison]);

  if (loading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (!comparison || Object.keys(comparison).length === 0) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <FlaskConical className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">A/B Pipeline Testing</h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Card className="border-dashed">
            <CardContent className="px-4 py-6 text-center">
              <p className="text-sm font-medium text-muted-foreground">Pipeline A</p>
              <p className="text-xs text-muted-foreground/60 mt-1">2-hour scan interval</p>
              <p className="text-xs text-muted-foreground/40 mt-3">Waiting for bot to start...</p>
            </CardContent>
          </Card>
          <Card className="border-dashed">
            <CardContent className="px-4 py-6 text-center">
              <p className="text-sm font-medium text-muted-foreground">Pipeline B</p>
              <p className="text-xs text-muted-foreground/60 mt-1">30-min scan interval</p>
              <p className="text-xs text-muted-foreground/40 mt-3">Waiting for bot to start...</p>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <FlaskConical className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-sm font-semibold">A/B Pipeline Testing</h2>
      </div>

      {/* Toggle cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {Object.entries(comparison).map(([id, data]) => (
          <PipelineCard
            key={id}
            id={id}
            data={data}
            selected={selectedPipeline === id}
            onSelect={() => setSelectedPipeline(id)}
          />
        ))}
      </div>

      {/* Detail panel — only show when there are positions or trades */}
      {detail && detail.positions.length > 0 && (
        <Card>
          <CardHeader className="pb-2 px-4 pt-3">
            <CardTitle className="text-sm font-medium">
              Pipeline {detail.pipeline} — Open Positions ({detail.positions.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <PipelinePositions detail={detail} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
