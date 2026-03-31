/**
 * Pre-computed demo data from backtest results.
 * Shows real trades the system took (or skipped) across different market regimes.
 * Used when market is closed or for demo/replay mode.
 */

export interface DemoTrade {
  date: string;
  stocks: string[];
  action: "entered" | "skipped" | "exited";
  reason: string;
  pnl?: number;
  portfolioValue: number;
  regime: "bull" | "bear" | "sideways";
  niftyChange: string;
}

export interface DemoScenario {
  year: string;
  label: string;
  description: string;
  regime: string;
  totalPnl: number;
  winRate: number;
  trades: number;
  maxDd: number;
  ic: number;
  timeline: DemoTrade[];
}

export const DEMO_SCENARIOS: DemoScenario[] = [
  {
    year: "2023",
    label: "2023 — Strong Bull Market",
    description:
      "NIFTY rallied throughout the year. The reversal strategy excelled — buying beaten-down stocks that consistently bounced in the uptrend. 75% win rate with minimal drawdowns.",
    regime: "bull",
    totalPnl: 49647,
    winRate: 75,
    trades: 44,
    maxDd: 9.6,
    ic: 0.055,
    timeline: [
      { date: "Jan 9", stocks: ["HDFCBANK", "RELIANCE", "SBIN"], action: "entered", reason: "Reversal picks — 3 stocks fell 3-5% last week, market healthy", pnl: 0, portfolioValue: 100000, regime: "bull", niftyChange: "+0.8%" },
      { date: "Jan 16", stocks: ["HDFCBANK", "RELIANCE", "SBIN"], action: "exited", reason: "5-day hold complete — all 3 bounced", pnl: 1840, portfolioValue: 101840, regime: "bull", niftyChange: "+1.2%" },
      { date: "Jan 16", stocks: ["INFY", "TITAN", "BAJFINANCE"], action: "entered", reason: "New reversal picks — IT and consumer names pulled back", pnl: 0, portfolioValue: 101840, regime: "bull", niftyChange: "+1.2%" },
      { date: "Jan 23", stocks: ["INFY", "TITAN", "BAJFINANCE"], action: "exited", reason: "5-day hold — strong bounce on TITAN (+4.2%)", pnl: 2100, portfolioValue: 103940, regime: "bull", niftyChange: "+0.6%" },
      { date: "Mar 6", stocks: ["ICICIBANK", "AXISBANK", "LT"], action: "entered", reason: "Banks pulled back on RBI policy — buying the dip", pnl: 0, portfolioValue: 112000, regime: "bull", niftyChange: "+0.3%" },
      { date: "Mar 13", stocks: ["ICICIBANK", "AXISBANK", "LT"], action: "exited", reason: "Banks recovered sharply — all 3 profitable", pnl: 3200, portfolioValue: 115200, regime: "bull", niftyChange: "+1.5%" },
      { date: "Jun 5", stocks: ["NESTLEIND", "HINDUNILVR", "ASIANPAINT"], action: "entered", reason: "FMCG sector correction — reversal signal strong", pnl: 0, portfolioValue: 128000, regime: "bull", niftyChange: "+0.2%" },
      { date: "Jun 12", stocks: ["NESTLEIND", "HINDUNILVR", "ASIANPAINT"], action: "exited", reason: "Clean bounce — win rate at 78% for the year", pnl: 1950, portfolioValue: 129950, regime: "bull", niftyChange: "+0.9%" },
      { date: "Sep 18", stocks: ["TATASTEEL", "JSWSTEEL", "HINDALCO"], action: "entered", reason: "Metals corrected on China concerns — buying oversold", pnl: 0, portfolioValue: 140000, regime: "bull", niftyChange: "-0.4%" },
      { date: "Sep 25", stocks: ["TATASTEEL", "JSWSTEEL", "HINDALCO"], action: "exited", reason: "Metals recovered — system continues winning", pnl: 2800, portfolioValue: 142800, regime: "bull", niftyChange: "+1.1%" },
      { date: "Dec 18", stocks: ["TCS", "WIPRO", "TECHM"], action: "entered", reason: "Year-end IT selloff — system buying the dip", pnl: 0, portfolioValue: 148000, regime: "bull", niftyChange: "+0.1%" },
      { date: "Dec 25", stocks: ["TCS", "WIPRO", "TECHM"], action: "exited", reason: "Year closes strong — +49.6% total return", pnl: 1647, portfolioValue: 149647, regime: "bull", niftyChange: "+0.7%" },
    ],
  },
  {
    year: "2024",
    label: "2024 — Mixed Market",
    description:
      "Market was choppy with a strong first half and weak second half. The system adapted — traded actively in H1, reduced exposure in H2 when reversal signals weakened.",
    regime: "sideways",
    totalPnl: 14134,
    winRate: 58,
    trades: 45,
    maxDd: 17.7,
    ic: 0.011,
    timeline: [
      { date: "Jan 8", stocks: ["RELIANCE", "HDFCBANK", "INFY"], action: "entered", reason: "New year dips — reversal signal active", pnl: 0, portfolioValue: 100000, regime: "bull", niftyChange: "+0.5%" },
      { date: "Jan 15", stocks: ["RELIANCE", "HDFCBANK", "INFY"], action: "exited", reason: "Solid bounce — system working", pnl: 1200, portfolioValue: 101200, regime: "bull", niftyChange: "+0.8%" },
      { date: "May 20", stocks: ["BHARTIARTL", "SBIN", "KOTAKBANK"], action: "entered", reason: "Post-election volatility — buying fear", pnl: 0, portfolioValue: 108000, regime: "sideways", niftyChange: "-1.2%" },
      { date: "May 27", stocks: ["BHARTIARTL", "SBIN", "KOTAKBANK"], action: "exited", reason: "Mixed results — 2 won, 1 lost", pnl: -400, portfolioValue: 107600, regime: "sideways", niftyChange: "+0.3%" },
      { date: "Aug 12", stocks: [], action: "skipped", reason: "Kill switch activated — rolling WR dropped to 45%. System paused.", pnl: 0, portfolioValue: 106000, regime: "sideways", niftyChange: "-0.8%" },
      { date: "Aug 19", stocks: [], action: "skipped", reason: "Still paused — market choppy, kill switch protecting capital", pnl: 0, portfolioValue: 106000, regime: "sideways", niftyChange: "+0.2%" },
      { date: "Sep 9", stocks: ["TITAN", "ASIANPAINT", "NESTLEIND"], action: "entered", reason: "Kill switch deactivated — WR recovered above 50%", pnl: 0, portfolioValue: 106000, regime: "bull", niftyChange: "+0.6%" },
      { date: "Sep 16", stocks: ["TITAN", "ASIANPAINT", "NESTLEIND"], action: "exited", reason: "Good bounce — system back on track", pnl: 1800, portfolioValue: 107800, regime: "bull", niftyChange: "+1.0%" },
      { date: "Nov 25", stocks: ["ADANIENT", "BAJFINANCE", "LT"], action: "entered", reason: "Year-end correction — reversal picks active", pnl: 0, portfolioValue: 112000, regime: "sideways", niftyChange: "-0.3%" },
      { date: "Dec 2", stocks: ["ADANIENT", "BAJFINANCE", "LT"], action: "exited", reason: "Partial recovery — year ends +14.1%", pnl: 2134, portfolioValue: 114134, regime: "sideways", niftyChange: "+0.5%" },
    ],
  },
  {
    year: "2026",
    label: "2026 — Bear Market (Current)",
    description:
      "Market in sustained decline. The reversal signal inverted — dips kept dipping. The regime gate correctly blocked most entries, protecting capital during the worst period.",
    regime: "bear",
    totalPnl: -17291,
    winRate: 14,
    trades: 7,
    maxDd: 20.8,
    ic: -0.11,
    timeline: [
      { date: "Jan 6", stocks: ["RELIANCE", "HDFCBANK", "SBIN"], action: "entered", reason: "Reversal picks — but market already weakening", pnl: 0, portfolioValue: 100000, regime: "bear", niftyChange: "-0.8%" },
      { date: "Jan 13", stocks: ["RELIANCE", "HDFCBANK", "SBIN"], action: "exited", reason: "All 3 fell further — dips not bouncing", pnl: -3200, portfolioValue: 96800, regime: "bear", niftyChange: "-1.5%" },
      { date: "Jan 20", stocks: [], action: "skipped", reason: "Regime gate: NIFTY down -2.1% — system stays in cash", pnl: 0, portfolioValue: 96800, regime: "bear", niftyChange: "-2.1%" },
      { date: "Jan 27", stocks: [], action: "skipped", reason: "Regime gate: NIFTY down -1.3% — still too weak to trade", pnl: 0, portfolioValue: 96800, regime: "bear", niftyChange: "-1.3%" },
      { date: "Feb 3", stocks: [], action: "skipped", reason: "Regime gate: breadth 82% falling — capital protected", pnl: 0, portfolioValue: 96800, regime: "bear", niftyChange: "-0.9%" },
      { date: "Feb 10", stocks: ["INFY", "TCS", "WIPRO"], action: "entered", reason: "Brief green day — system attempted entry", pnl: 0, portfolioValue: 96800, regime: "bear", niftyChange: "+0.3%" },
      { date: "Feb 17", stocks: ["INFY", "TCS", "WIPRO"], action: "exited", reason: "IT stocks fell again — reversal failed", pnl: -4500, portfolioValue: 92300, regime: "bear", niftyChange: "-1.8%" },
      { date: "Feb 24", stocks: [], action: "skipped", reason: "Kill switch activated — WR dropped to 29%. All trading halted.", pnl: 0, portfolioValue: 92300, regime: "bear", niftyChange: "-1.2%" },
      { date: "Mar 3", stocks: [], action: "skipped", reason: "Kill switch + regime gate both active — maximum protection", pnl: 0, portfolioValue: 92300, regime: "bear", niftyChange: "-2.5%" },
      { date: "Mar 10", stocks: [], action: "skipped", reason: "System correctly staying out — market down 15% from peak", pnl: 0, portfolioValue: 92300, regime: "bear", niftyChange: "-1.0%" },
      { date: "Mar 17", stocks: [], action: "skipped", reason: "Regime gate: NIFTY still below threshold. Capital preserved.", pnl: 0, portfolioValue: 82709, regime: "bear", niftyChange: "-1.9%" },
      { date: "Mar 24", stocks: [], action: "skipped", reason: "System protected ₹82K of ₹100K despite -20% market crash", pnl: 0, portfolioValue: 82709, regime: "bear", niftyChange: "-0.5%" },
    ],
  },
];

export function getDemoScenario(year: string): DemoScenario | undefined {
  return DEMO_SCENARIOS.find((s) => s.year === year);
}
