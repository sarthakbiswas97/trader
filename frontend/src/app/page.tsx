"use client";

import Link from "next/link";
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
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MarketStatusBanner } from "@/components/market-status";
import { ReplayMode } from "@/components/replay-mode";

const STRATEGIES = [
  { name: "ML Prediction", tf: "5-min", trades: "1,635", pnl: -6088, pf: 0.29, status: "failed", why: "No signal in OHLCV features" },
  { name: "Breakout Detection", tf: "5-min", trades: "200", pnl: -1684, pf: 0.42, status: "failed", why: "Fakeouts, no follow-through" },
  { name: "Breakout + Regime", tf: "5-min", trades: "22", pnl: -128, pf: 0.69, status: "failed", why: "Too few trades to validate" },
  { name: "Mean Reversion", tf: "5-min", trades: "1,064", pnl: -8693, pf: 0.1, status: "failed", why: "Signal too weak after costs" },
  { name: "Trend Following", tf: "30-min", trades: "405", pnl: -4011, pf: 0.32, status: "failed", why: "No intraday trend persistence" },
  { name: "Cross-Sectional ML", tf: "5-min", trades: "831K", pnl: 0, pf: 0, status: "failed", why: "IC ≈ 0 — no predictive signal" },
  { name: "Daily Reversal", tf: "Daily", trades: "187", pnl: 60337, pf: 1.6, status: "validated", why: "Structural mean-reversion effect" },
];

const YEARS = [
  { year: "2022", pnl: 14872, wr: 59, dd: 7.8, ic: 0.052 },
  { year: "2023", pnl: 49647, wr: 75, dd: 9.6, ic: 0.055 },
  { year: "2024", pnl: 14134, wr: 58, dd: 17.7, ic: 0.011 },
  { year: "2025", pnl: 24655, wr: 49, dd: 8.1, ic: 0.045 },
  { year: "2026", pnl: -17291, wr: 14, dd: 20.8, ic: -0.11 },
];

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
          ML-powered trading system for Indian equity markets. Built through systematic research —
          testing 6+ strategies across 4 years of NIFTY 100 data to find a validated, statistically significant edge.
        </p>
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1.5 text-xs font-medium px-4 py-2 rounded-md bg-foreground text-background hover:opacity-80 transition-colors mt-2"
        >
          Try It Live (Paper Trading)
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>

      {/* Key Metrics */}
      <div>
        <h2 className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wider">Performance</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Stat label="4-Year Return" value="+60%" trend="profit" icon={TrendingUp} />
          <Stat label="CAGR" value="12.5%" trend="profit" icon={BarChart3} />
          <Stat label="Win Rate" value="59%" icon={Target} />
          <Stat label="Years Profitable" value="4 / 5" trend="profit" icon={CheckCircle2} />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
          <Stat label="IC (t-stat)" value="0.029 (5.0)" icon={Brain} />
          <Stat label="Max Drawdown" value="17.6%" trend="loss" icon={AlertTriangle} />
          <Stat label="Universe" value="NIFTY 100" icon={BarChart3} />
          <Stat label="Holding Period" value="5 days" icon={Clock} />
        </div>
      </div>

      {/* How It Works — Multi-Engine */}
      <Card>
        <CardHeader className="pb-2 px-4 pt-3">
          <CardTitle className="text-sm font-medium">How It Works — Multi-Engine Architecture</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <div className="space-y-3">
            {[
              { step: "1", title: "Regime Classifier", desc: "Classify market as BULL, NEUTRAL, or WEAK using NIFTY 50-DMA + 5-day momentum + breadth. 2-day persistence filter prevents whipsaw.", color: "text-foreground" },
              { step: "2", title: "Capital Allocation", desc: "BULL: 35% large-cap + 40% midcap + 25% cash. NEUTRAL: 45% large + 15% mid + 40% cash. WEAK: 15% large + 10% mid + 75% cash — reduced but active (IC is strongest here).", color: "text-foreground" },
              { step: "3", title: "Large-Cap Reversal Engine", desc: "Rank NIFTY 50 stocks by 5d + 10d + 21d past returns. Buy top 10 losers — IC = +0.020, +44% return, Sharpe 0.96.", color: "text-profit" },
              { step: "4", title: "Midcap Reversal Engine", desc: "Rank NIFTY 100 Extra (midcap) stocks by reversal. Buy top 5 losers — IC = +0.025, +69% return, Sharpe 0.99.", color: "text-profit" },
              { step: "5", title: "Hold & Rebalance", desc: "Hold 5 trading days per batch. Each engine manages positions independently with 5% per-stock limit.", color: "text-foreground" },
              { step: "6", title: "Kill Switch", desc: "Per-engine kill switch: if 20-trade win rate < 50%, pause that engine. Market regime gate overrides everything in crashes.", color: "text-warning" },
            ].map((item) => (
              <div key={item.step} className="flex gap-3 items-start">
                <div className="flex-shrink-0 h-6 w-6 rounded-full bg-muted flex items-center justify-center">
                  <span className="text-[11px] font-medium">{item.step}</span>
                </div>
                <div>
                  <p className={cn("text-sm font-medium", item.color)}>{item.title}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{item.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Research Journey */}
      <div>
        <h2 className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wider flex items-center gap-1.5">
          <FlaskConical className="h-3.5 w-3.5" />
          Research Journey — 6 Strategies Tested
        </h2>
        <Card>
          <CardContent className="px-0 py-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs">#</TableHead>
                  <TableHead className="text-xs">Strategy</TableHead>
                  <TableHead className="text-xs">Timeframe</TableHead>
                  <TableHead className="text-xs text-right">Trades</TableHead>
                  <TableHead className="text-xs text-right">P&L</TableHead>
                  <TableHead className="text-xs text-right">PF</TableHead>
                  <TableHead className="text-xs">Result</TableHead>
                  <TableHead className="text-xs">Insight</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {STRATEGIES.map((s, i) => (
                  <TableRow key={i} className={cn(s.status === "validated" && "bg-profit/5")}>
                    <TableCell className="text-xs">{i + 1}</TableCell>
                    <TableCell className="text-xs font-medium">{s.name}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{s.tf}</TableCell>
                    <TableCell className="text-xs text-right">{s.trades}</TableCell>
                    <TableCell className={cn("text-xs text-right font-medium", s.pnl > 0 ? "text-profit" : s.pnl < 0 ? "text-loss" : "")}>
                      {s.pnl > 0 ? "+" : ""}{s.pnl === 0 ? "IC ≈ 0" : `₹${s.pnl.toLocaleString()}`}
                    </TableCell>
                    <TableCell className="text-xs text-right">{s.pf > 0 ? s.pf.toFixed(2) : "—"}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={cn("text-[10px]", s.status === "validated" ? "text-profit border-profit/20" : "text-loss border-loss/20")}>
                        {s.status === "validated" ? "Validated" : "Failed"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-[11px] text-muted-foreground max-w-[180px]">{s.why}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      {/* Walk-Forward Validation */}
      <div>
        <h2 className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wider">
          Walk-Forward Validation — Each Year Tested Independently
        </h2>
        <Card>
          <CardContent className="px-0 py-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs">Year</TableHead>
                  <TableHead className="text-xs text-right">P&L</TableHead>
                  <TableHead className="text-xs text-right">Win Rate</TableHead>
                  <TableHead className="text-xs text-right">Max DD</TableHead>
                  <TableHead className="text-xs text-right">IC</TableHead>
                  <TableHead className="text-xs">Result</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {YEARS.map((y) => (
                  <TableRow key={y.year}>
                    <TableCell className="text-sm font-medium">{y.year}</TableCell>
                    <TableCell className={cn("text-sm text-right font-medium", y.pnl > 0 ? "text-profit" : "text-loss")}>
                      {y.pnl > 0 ? "+" : ""}₹{y.pnl.toLocaleString()}
                    </TableCell>
                    <TableCell className="text-sm text-right">{y.wr}%</TableCell>
                    <TableCell className="text-sm text-right text-loss">{y.dd}%</TableCell>
                    <TableCell className={cn("text-sm text-right", y.ic > 0 ? "text-profit" : "text-loss")}>
                      {y.ic > 0 ? "+" : ""}{y.ic.toFixed(3)}
                    </TableCell>
                    <TableCell>
                      {y.pnl > 0 ? <CheckCircle2 className="h-4 w-4 text-profit" /> : <XCircle className="h-4 w-4 text-loss" />}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      {/* Key Discovery */}
      <Card className="border-border/50">
        <CardHeader className="pb-2 px-4 pt-3">
          <CardTitle className="text-sm font-medium flex items-center gap-1.5">
            <Brain className="h-3.5 w-3.5" />
            Key Discovery
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="rounded-lg border border-loss/20 bg-loss/5 p-4">
              <p className="text-xs font-medium text-loss mb-1">Intraday (5-min candles)</p>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                IC ≈ 0. Every strategy loses money. Indian large-cap stocks are too efficient at this
                resolution. Price-derived features (RSI, MACD, breakouts) are already arbitraged by
                institutions and HFT systems.
              </p>
            </div>
            <div className="rounded-lg border border-profit/20 bg-profit/5 p-4">
              <p className="text-xs font-medium text-profit mb-1">Daily (5-day holding)</p>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                IC = +0.029 (t-stat = 5.0). Short-term reversal is a structural behavioral effect —
                stocks that fall hard attract value buyers, producing a statistically significant
                5-day bounce across 4 years of out-of-sample data.
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
                <p className="text-xs font-medium">Market Regime Gate</p>
              </div>
              <p className="text-[11px] text-muted-foreground">
                Blocks all entries when NIFTY falls &gt; 0.5%, breadth is weak, or 5-day decline exceeds 3%.
                Validated live — correctly blocked entries on bearish days.
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="px-4 py-3">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle className="h-4 w-4 text-warning" />
                <p className="text-xs font-medium">Kill Switch</p>
              </div>
              <p className="text-[11px] text-muted-foreground">
                Pauses trading when rolling 20-trade win rate drops below 50%.
                Reduces max drawdown from 27.6% to 17.6% — a 36% improvement.
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="px-4 py-3">
              <div className="flex items-center gap-2 mb-2">
                <Clock className="h-4 w-4 text-muted-foreground" />
                <p className="text-xs font-medium">Position Limits</p>
              </div>
              <p className="text-[11px] text-muted-foreground">
                Max 5% capital per stock. Max 10 stocks at a time. Weekly rebalance with fixed 5-day holding.
                Simple, rule-based, no discretion.
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
          No account needed. Simulated trading with ₹1,00,000 virtual capital using real market data.
        </p>
      </div>

      {/* Footer */}
      <div className="border-t border-border/50 pt-4 text-center">
        <p className="text-[11px] text-muted-foreground/40">
          Built with Python, FastAPI, XGBoost, LightGBM, Next.js, Zerodha Kite Connect
        </p>
      </div>
    </div>
  );
}
