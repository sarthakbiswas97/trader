"use client";

import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  TrendingUp,
  BarChart3,
  Shield,
  Brain,
  Clock,
  Target,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  ArrowRight,
  Activity,
  FlaskConical,
  Layers,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MarketStatusBanner } from "@/components/market-status";
import { ReplayMode } from "@/components/replay-mode";

function Stat({ label, value, trend, icon: Icon }: {
  label: string; value: string; trend?: "profit" | "loss"; icon?: typeof TrendingUp;
}) {
  return (
    <Card>
      <CardContent className="px-4 py-3">
        <div className="flex items-center justify-between">
          <p className="text-xs font-medium text-muted-foreground">{label}</p>
          {Icon && <Icon className="h-3.5 w-3.5 text-muted-foreground/60" />}
        </div>
        <p className={cn("text-lg font-semibold tracking-tight mt-1", trend === "profit" && "text-profit", trend === "loss" && "text-loss")}>
          {value}
        </p>
      </CardContent>
    </Card>
  );
}

const VERSIONS = [
  {
    version: "v1",
    label: "Foundation",
    metric: "Baseline",
    metricColor: "text-muted-foreground" as const,
    desc: "Validated the core edge: stocks that fall hard tend to bounce. Sat in 100% cash during weak markets — safe but left money on the table.",
    status: "base",
  },
  {
    version: "v2",
    label: "Capital Efficiency",
    metric: "+44% better",
    metricColor: "text-profit" as const,
    desc: "Stopped sitting idle. Started deploying capital even in weak markets — because the reversal signal is actually strongest when fear is highest.",
    status: "improved",
  },
  {
    version: "v3",
    label: "Multi-Engine",
    metric: "+53% better",
    metricColor: "text-profit" as const,
    desc: "Added midcap stocks as a second engine. Allocation scales with market momentum — more midcap exposure when trends are strong, less when fading.",
    status: "improved",
  },
  {
    version: "v4",
    label: "Adaptive Intelligence",
    metric: "+53% better",
    metricColor: "text-profit" as const,
    desc: "Replaced hard thresholds with smooth confidence scoring. System continuously adjusts exposure based on signal quality and portfolio health. Protects during drawdowns, leans in during recoveries.",
    status: "locked",
  },
];

const STRATEGIES_TESTED = [
  { name: "ML Prediction (5-min)", result: "failed" as const, insight: "No signal in OHLCV features" },
  { name: "Breakout Detection", result: "failed" as const, insight: "Fakeouts, no follow-through" },
  { name: "Mean Reversion (5-min)", result: "failed" as const, insight: "Too weak after costs" },
  { name: "Trend Following (30-min)", result: "failed" as const, insight: "No intraday trend persistence" },
  { name: "Cross-Sectional ML", result: "failed" as const, insight: "Zero predictive signal" },
  { name: "Daily Reversal", result: "validated" as const, insight: "Structural mean-reversion effect" },
];

export default function LandingPage() {
  return (
    <div className="px-6 py-8 space-y-10 max-w-5xl mx-auto">

      {/* Hero */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-profit" />
          <h1 className="text-xl font-semibold tracking-tight">Autonomous Trading System</h1>
        </div>
        <p className="text-sm text-muted-foreground max-w-2xl">
          A research-backed trading system for Indian equity markets. We tested 6 strategies,
          found one that works, then spent 4 iterations making it smarter — not by changing
          the signal, but by improving how capital is deployed.
        </p>
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1.5 text-xs font-medium px-4 py-2 rounded-md bg-foreground text-background hover:opacity-80 transition-colors mt-2"
        >
          Try It Live (Paper Trading)
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>

      {/* Key Metrics — clear and contextual */}
      <div>
        <h2 className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wider">Backtest Performance (Oct 2020 – Mar 2026)</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Stat label="Annual Return (CAGR)" value="~7%" trend="profit" icon={TrendingUp} />
          <Stat label="Total Return (5.4 yrs)" value="+40%" trend="profit" icon={BarChart3} />
          <Stat label="Win Rate" value="58%" icon={Target} />
          <Stat label="Max Drawdown" value="9–16%" trend="loss" icon={AlertTriangle} />
        </div>
        <p className="text-[11px] text-muted-foreground/50 mt-2">
          Based on ₹1,00,000 simulated capital across 96 NIFTY stocks. Includes transaction costs and slippage. Not investment advice.
        </p>
      </div>

      {/* The Core Idea — simple explanation */}
      <Card>
        <CardHeader className="pb-2 px-4 pt-3">
          <CardTitle className="text-sm font-medium flex items-center gap-1.5">
            <Brain className="h-3.5 w-3.5" />
            The Core Idea
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <p className="text-sm text-muted-foreground leading-relaxed mb-4">
            Markets overreact. When a stock drops sharply, fear pushes it below its fair value.
            Value buyers step in, and the stock bounces back within days. We exploit this effect
            systematically across 96 NIFTY stocks.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="rounded-lg border p-3 space-y-1">
              <p className="text-xs font-medium">1. Read the market</p>
              <p className="text-[11px] text-muted-foreground">
                Classify as Bull, Neutral, or Weak. Adjust how much capital to deploy.
              </p>
            </div>
            <div className="rounded-lg border border-profit/20 bg-profit/5 p-3 space-y-1">
              <p className="text-xs font-medium text-profit">2. Find oversold stocks</p>
              <p className="text-[11px] text-muted-foreground">
                Rank all stocks by how much they fell. Buy the biggest losers — they bounce hardest.
              </p>
            </div>
            <div className="rounded-lg border p-3 space-y-1">
              <p className="text-xs font-medium">3. Hold 5 days, repeat</p>
              <p className="text-[11px] text-muted-foreground">
                Wait for the bounce. Sell after 5 trading days. Pick new losers. Every week.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* System Evolution — the story */}
      <div>
        <h2 className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wider flex items-center gap-1.5">
          <Layers className="h-3.5 w-3.5" />
          System Evolution — Same Signal, Smarter Allocation
        </h2>
        <div className="space-y-3">
          {VERSIONS.map((v) => (
            <Card key={v.version} className={cn(v.status === "locked" && "border-profit/30 bg-profit/5")}>
              <CardContent className="px-4 py-3">
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <Badge variant="outline" className={cn(
                        "text-[10px]",
                        v.status === "locked" ? "text-profit border-profit/30" :
                        v.status === "improved" ? "text-foreground border-border" :
                        "text-muted-foreground border-border/50"
                      )}>
                        {v.version}
                      </Badge>
                      <span className="text-sm font-medium">{v.label}</span>
                      {v.status === "locked" && (
                        <Badge variant="outline" className="text-[10px] text-profit border-profit/30">
                          Current
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">{v.desc}</p>
                  </div>
                  <div className="text-right ml-4 flex-shrink-0">
                    <p className={cn("text-sm font-semibold", v.metricColor)}>{v.metric}</p>
                    {v.status !== "base" && (
                      <p className="text-[10px] text-muted-foreground/50">vs v1 baseline</p>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
        <p className="text-[11px] text-muted-foreground/60 mt-2 text-center">
          Every improvement came from better capital allocation — the underlying signal never changed.
        </p>
      </div>

      {/* Research Journey — compact */}
      <div>
        <h2 className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wider flex items-center gap-1.5">
          <FlaskConical className="h-3.5 w-3.5" />
          Research Journey — 6 Strategies Tested
        </h2>
        <Card>
          <CardContent className="px-4 py-3">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {STRATEGIES_TESTED.map((s, i) => (
                <div
                  key={i}
                  className={cn(
                    "flex items-center gap-2 px-3 py-2 rounded-lg",
                    s.result === "validated" ? "bg-profit/5 border border-profit/20" : "bg-muted/30"
                  )}
                >
                  {s.result === "validated" ? (
                    <CheckCircle2 className="h-3.5 w-3.5 text-profit flex-shrink-0" />
                  ) : (
                    <XCircle className="h-3.5 w-3.5 text-muted-foreground/40 flex-shrink-0" />
                  )}
                  <div className="min-w-0">
                    <p className={cn("text-xs font-medium truncate", s.result === "validated" && "text-profit")}>
                      {s.name}
                    </p>
                    <p className="text-[10px] text-muted-foreground truncate">{s.insight}</p>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Key Discovery */}
      <Card className="border-border/50">
        <CardHeader className="pb-2 px-4 pt-3">
          <CardTitle className="text-sm font-medium flex items-center gap-1.5">
            <Zap className="h-3.5 w-3.5" />
            Key Discovery
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="rounded-lg border border-loss/20 bg-loss/5 p-4">
              <p className="text-xs font-medium text-loss mb-1">Intraday trading</p>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                Doesn't work for retail in Indian markets. Every 5-minute strategy we tested
                lost money — institutions and algorithms are too fast. The edge doesn't exist
                at this resolution.
              </p>
            </div>
            <div className="rounded-lg border border-profit/20 bg-profit/5 p-4">
              <p className="text-xs font-medium text-profit mb-1">Daily reversal (5-day holding)</p>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                Works consistently. Stocks that drop hard attract buyers and bounce within a week.
                This is a behavioral effect — driven by human psychology, not patterns that
                algorithms can arbitrage away.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Protection */}
      <div>
        <h2 className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wider">Capital Protection</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <Card>
            <CardContent className="px-4 py-3">
              <div className="flex items-center gap-2 mb-2">
                <Shield className="h-4 w-4 text-profit" />
                <p className="text-xs font-medium">Regime-Aware Sizing</p>
              </div>
              <p className="text-[11px] text-muted-foreground">
                Automatically reduces exposure in weak markets and increases during strong trends.
                Continuous adjustment, not binary on/off.
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="px-4 py-3">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle className="h-4 w-4 text-warning" />
                <p className="text-xs font-medium">Drawdown Protection</p>
              </div>
              <p className="text-[11px] text-muted-foreground">
                When the portfolio drops, the system automatically reduces position sizes.
                Gentle in uptrends, aggressive in downtrends. Recovers faster after bounces.
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="px-4 py-3">
              <div className="flex items-center gap-2 mb-2">
                <Clock className="h-4 w-4 text-muted-foreground" />
                <p className="text-xs font-medium">Kill Switch</p>
              </div>
              <p className="text-[11px] text-muted-foreground">
                If recent trades show a losing streak, the system pauses automatically.
                Resumes only when signal quality recovers. No manual intervention needed.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Live Market Status */}
      <div>
        <h2 className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wider">
          Live Market Status
        </h2>
        <MarketStatusBanner />
      </div>

      {/* Replay Mode */}
      <div>
        <h2 className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wider">
          Historical Replay — See the System in Action
        </h2>
        <ReplayMode />
      </div>

      {/* CTA */}
      <div className="text-center py-6 space-y-3">
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1.5 text-sm font-medium px-6 py-2.5 rounded-md bg-foreground text-background hover:opacity-80 transition-colors"
        >
          Try the Dashboard (Paper Trading)
          <ArrowRight className="h-4 w-4" />
        </Link>
        <p className="text-[11px] text-muted-foreground/50">
          No account needed. Simulated trading with virtual capital using real market data.
        </p>
      </div>

      {/* Footer */}
      <div className="border-t border-border/50 pt-4 text-center">
        <p className="text-[11px] text-muted-foreground/40">
          Built with Python, FastAPI, Next.js, Zerodha Kite Connect, Neon Postgres
        </p>
      </div>
    </div>
  );
}
