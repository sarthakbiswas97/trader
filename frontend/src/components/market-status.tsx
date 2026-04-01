"use client";

import { useEffect, useState } from "react";
import {
  TrendingDown,
  TrendingUp,
  Minus,
  ShieldCheck,
  ShieldAlert,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface MarketStatusData {
  market_open: boolean;
  nifty_change: number;
  nifty_price: number;
  breadth_falling: number;
  breadth_total: number;
  should_trade: boolean;
  reason: string;
  trade_probability: "high" | "low" | "none";
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export function MarketStatusBanner() {
  const [status, setStatus] = useState<MarketStatusData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, []);

  async function fetchStatus() {
    try {
      const res = await fetch(`${API_BASE}/api/v1/market/status`);
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
      }
    } catch {
      // API not available
    } finally {
      setLoading(false);
    }
  }

  if (loading || !status) return null;

  const isDown = status.nifty_change < -0.005;
  const isUp = status.nifty_change > 0.005;
  const changePct = (status.nifty_change * 100).toFixed(2);

  return (
    <div
      className={cn(
        "rounded-lg border px-4 py-3 flex items-center justify-between",
        isDown
          ? "border-loss/20 bg-loss/5"
          : isUp
            ? "border-profit/20 bg-profit/5"
            : "border-border/50 bg-muted/30"
      )}
    >
      <div className="flex items-center gap-3">
        {/* Market direction icon */}
        {isDown ? (
          <TrendingDown className="h-4 w-4 text-loss" />
        ) : isUp ? (
          <TrendingUp className="h-4 w-4 text-profit" />
        ) : (
          <Minus className="h-4 w-4 text-muted-foreground" />
        )}

        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">
              NIFTY 50: {status.nifty_price.toLocaleString()}
            </span>
            <span
              className={cn(
                "text-xs font-medium",
                isDown ? "text-loss" : isUp ? "text-profit" : "text-muted-foreground"
              )}
            >
              ({isUp ? "+" : ""}{changePct}%)
            </span>
          </div>
          <p className="text-[11px] text-muted-foreground mt-0.5">
            {status.reason}
          </p>
        </div>
      </div>

      {/* Trade signal */}
      <div className="flex items-center gap-2">
        {!status.market_open ? (
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-muted border border-border/50">
            <Minus className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-xs font-medium text-muted-foreground">Market Closed</span>
          </div>
        ) : status.should_trade ? (
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-profit/10 border border-profit/20">
            <ShieldCheck className="h-3.5 w-3.5 text-profit" />
            <span className="text-xs font-medium text-profit">Trade Active</span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-loss/10 border border-loss/20">
            <ShieldAlert className="h-3.5 w-3.5 text-loss" />
            <span className="text-xs font-medium text-loss">No Trade</span>
          </div>
        )}
      </div>
    </div>
  );
}

export function TradeProbabilityBadge({
  probability,
}: {
  probability: "high" | "low" | "none";
}) {
  const config = {
    high: { label: "High", className: "bg-profit/10 text-profit border-profit/20" },
    low: { label: "Low", className: "bg-warning/10 text-warning border-warning/20" },
    none: { label: "None", className: "bg-loss/10 text-loss border-loss/20" },
  };

  const c = config[probability];

  return (
    <span className={cn("text-[10px] font-medium px-1.5 py-0.5 rounded border", c.className)}>
      Trade: {c.label}
    </span>
  );
}
