const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

// =============================================================================
// Types
// =============================================================================

export interface HealthResponse {
  status: string;
  timestamp: string;
  version: string;
  components: Record<string, boolean | string>;
}

export interface AuthStatus {
  authenticated: boolean;
  connected: boolean;
  session_valid: boolean;
  expires_at: string | null;
}

export interface BotStatus {
  status: "stopped" | "running" | "paused" | "error";
  running_since: string | null;
  cycle_count: number;
  last_cycle: string | null;
  symbols_count: number;
  error_message: string | null;
}

export interface PortfolioSummary {
  total_capital: number;
  available_cash: number;
  invested_value: number;
  current_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
  total_pnl: number;
  total_pnl_percent: number;
  open_positions: number;
}

export interface Position {
  symbol: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  pnl: number;
  pnl_percent: number;
  entry_time: string | null;
  entry_reason: string | null;
}

export interface PositionsResponse {
  positions: Position[];
  summary: PortfolioSummary;
}

export interface Trade {
  id: string;
  symbol: string;
  side: "BUY" | "SELL";
  quantity: number;
  entry_price: number;
  exit_price: number | null;
  entry_time: string;
  exit_time: string | null;
  pnl: number | null;
  pnl_percent: number | null;
  status: "open" | "closed";
  exit_reason: string | null;
}

export interface TradesResponse {
  trades: Trade[];
  total_count: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
}

export interface Prediction {
  symbol: string;
  direction: "UP" | "DOWN" | "NEUTRAL";
  probability: number;
  confidence: number;
  prob_up?: number;
  prob_down?: number;
  prob_neutral?: number;
  should_trade: boolean;
  is_long_signal?: boolean;
  is_short_signal?: boolean;
  timestamp: string;
  top_features: [string, number][];
}

export interface PredictionsResponse {
  predictions: Prediction[];
  generated_at: string;
  symbols_analyzed: number;
  up_signals: number;
  down_signals: number;
}

export interface PredictionSession {
  session_id: string;
  generated_at: string;
  source: string;
  total: number;
  up_signals: number;
  down_signals: number;
  neutral_signals: number;
}

export interface PredictionSessionDetail {
  session_id: string;
  predictions: Prediction[];
  total: number;
  generated_at: string;
}

export interface ReversalStock {
  symbol: string;
  universe: "largecap" | "midcap";
  score: number;
  ret_5d: number;
  ret_10d: number;
  ret_21d: number;
  price: number;
  rank: number;
  action: "BUY" | "WATCH" | "SKIP" | "BLOCKED" | "HELD";
  reason: string;
  today_return: number;
}

export interface ReversalResponse {
  stocks: ReversalStock[];
  regime: {
    current: string;
    pending: string | null;
    pending_days: number;
    total_exposure: number;
  };
  kill_switch: {
    ic_killed: boolean;
    rolling_ic: number | null;
  };
  summary: {
    total_stocks: number;
    buy_signals: number;
    held_positions: number;
    blocked: number;
    generated_at: string;
  };
}

export interface RiskStatus {
  circuit_breaker_triggered: boolean;
  circuit_breaker_reason: string | null;
  trades_today: number;
  max_trades: number;
  daily_pnl: number;
  daily_loss_limit: number;
  long_exposure: number;
  max_long_exposure: number;
  short_exposure: number;
  max_short_exposure: number;
  total_exposure: number;
  max_total_exposure: number;
  risk_score: number;
  shorting_enabled: boolean;
}

export interface PipelineStatus {
  running: boolean;
  current_step: string;
  step_number: number;
  total_steps: number;
  detail: string;
  error: string;
  completed: boolean;
}

export interface PipelineInfo {
  historical_data: boolean;
  features: boolean;
  model_exists: boolean;
  model_age_days: number | null;
  model_stale: boolean;
  needs_training: boolean;
}

export interface MultiEngineStatus {
  regime: "BULL" | "NEUTRAL" | "WEAK";
  regime_detail: {
    regime: string;
    pending: string | null;
    pending_days: number;
  };
  allocation: Record<string, number>;
  total_capital: number;
  cash: number;
  portfolio_value: number;
  total_pnl: number;
  total_pnl_pct: number;
  total_trades: number;
  win_rate: number;
  rolling_ic: number | null;
  capital_utilization: number;
  engines: Record<
    string,
    {
      active: boolean;
      capital: number;
      pnl: number;
      open_positions: number;
      total_trades: number;
      win_rate: number;
      positions: Array<{
        entry_date: string;
        stocks: Array<{
          symbol: string;
          quantity: number;
          entry_price: number;
          score: number;
          ret_5d: number;
        }>;
      }>;
      recent_trades: Array<{
        symbol: string;
        engine: string;
        entry_date: string;
        exit_date: string;
        net_pnl: number;
        win: boolean;
      }>;
    }
  >;
}

export interface CycleResult {
  timestamp: string;
  market_open: boolean;
  predictions_generated: number;
  signals_found: number;
  entries_executed: number;
  exits_executed: number;
  errors: string[];
}

// =============================================================================
// Fetch Wrapper
// =============================================================================

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || res.statusText);
  }

  return res.json();
}

// =============================================================================
// API Functions
// =============================================================================

export const api = {
  // Health
  health: () => request<HealthResponse>("/api/v1/health"),

  // Auth
  authStatus: () => request<AuthStatus>("/api/v1/auth/status"),
  connect: (paperMode = true) =>
    request<{ success: boolean; message: string }>(
      `/api/v1/auth/connect?paper_mode=${paperMode}`,
      { method: "POST" },
    ),
  disconnect: () =>
    request<{ success: boolean; message: string }>("/api/v1/auth/disconnect", {
      method: "POST",
    }),

  // Bot
  botStatus: () => request<BotStatus>("/api/v1/bot/status"),
  botPrepare: () =>
    request<{ success: boolean; message: string }>("/api/v1/bot/prepare", {
      method: "POST",
    }),
  botPrepareStatus: () =>
    request<PipelineStatus>("/api/v1/bot/prepare/status"),
  botPipeline: () => request<PipelineInfo>("/api/v1/bot/pipeline"),
  botStart: (symbols?: string[], capital = 100000) =>
    request<{ success: boolean; message: string; status: string }>(
      "/api/v1/bot/start",
      {
        method: "POST",
        body: JSON.stringify({
          symbols,
          paper_mode: true,
          capital,
        }),
      },
    ),
  botStop: (squareOff = false) =>
    request<{ success: boolean; message: string; positions_closed: number }>(
      `/api/v1/bot/stop?square_off=${squareOff}`,
      { method: "POST" },
    ),
  botCycles: (limit = 10) =>
    request<{ cycles: CycleResult[]; total: number }>(
      `/api/v1/bot/cycles?limit=${limit}`,
    ),
  botRisk: () => request<RiskStatus>("/api/v1/bot/risk"),
  botSquareOff: () =>
    request<{ success: boolean; positions_closed: number }>(
      "/api/v1/bot/square-off",
      { method: "POST" },
    ),

  // Portfolio
  portfolioSummary: () =>
    request<PortfolioSummary>("/api/v1/portfolio/summary"),
  positions: () => request<PositionsResponse>("/api/v1/portfolio/positions"),
  trades: (limit = 50) =>
    request<TradesResponse>(`/api/v1/portfolio/trades?limit=${limit}`),
  margin: () =>
    request<{
      available_cash: number;
      used_margin: number;
      total_balance: number;
    }>("/api/v1/portfolio/margin"),

  // Predictions
  reversalScores: () =>
    request<ReversalResponse>("/api/v1/predictions/reversal"),
  generatePredictions: (symbols?: string[], limit = 10) =>
    request<PredictionsResponse>("/api/v1/predictions/generate", {
      method: "POST",
      body: JSON.stringify({ symbols, limit }),
    }),
  latestPredictions: () =>
    request<PredictionsResponse>("/api/v1/predictions/latest"),
  predictionHistory: (limit = 10) =>
    request<{ sessions: PredictionSession[] }>(
      `/api/v1/predictions/history?limit=${limit}`,
    ),
  predictionSession: (sessionId: string) =>
    request<PredictionSessionDetail>(
      `/api/v1/predictions/history/${sessionId}`,
    ),
  symbols: () =>
    request<{ symbols: string[]; count: number; index: string }>(
      "/api/v1/predictions/symbols",
    ),

  // Bot extras
  botWatchlist: () =>
    request<{
      watchlist: Array<{
        symbol: string;
        tier: number;
        direction: string;
        confidence: number;
        has_position: boolean;
        promoted_at: string | null;
      }>;
      tier1_count: number;
      total_symbols: number;
    }>("/api/v1/bot/watchlist"),

  botShorting: (enabled: boolean) =>
    request<{ success: boolean; shorting_enabled: boolean; message: string }>(
      `/api/v1/bot/shorting?enabled=${enabled}`,
      { method: "POST" },
    ),

  // Multi-Engine
  multiEngineStatus: () =>
    request<MultiEngineStatus>("/api/v1/bot/multi-engine"),
  multiEngineRun: () =>
    request<Record<string, unknown>>("/api/v1/bot/multi-engine/run", {
      method: "POST",
    }),
  multiEngineReset: () =>
    request<{ success: boolean; message: string }>(
      "/api/v1/bot/multi-engine/reset",
      { method: "POST" },
    ),
};

// SSE stream URL for predictions
export const PREDICTIONS_STREAM_URL = `${API_BASE}/api/v1/predictions/stream`;
