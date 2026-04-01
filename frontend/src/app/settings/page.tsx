"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Settings,
  Power,
  PowerOff,
  ShieldAlert,
  User,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Download,
  BrainCircuit,
  BarChart3,
  Check,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { useApi } from "@/hooks/use-api";
import { api, type PipelineStatus } from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/components/pnl-text";

// =============================================================================
// Pipeline Progress Component
// =============================================================================

const PIPELINE_STEPS = [
  { key: "download", label: "Download Data", icon: Download, detail: "Fetching 60 days of candles from Zerodha" },
  { key: "features", label: "Generate Features", icon: BarChart3, detail: "Computing 17 technical indicators" },
  { key: "training", label: "Train Model", icon: BrainCircuit, detail: "Training XGBoost with decay weighting" },
];

function PipelineProgress({
  status,
  visible,
}: {
  status: PipelineStatus | null;
  visible: boolean;
}) {
  if (!visible || !status) return null;

  return (
    <div className="rounded-lg border border-border/60 bg-muted/30 p-4 space-y-3">
      <p className="text-xs font-medium text-muted-foreground">Preparing ML Pipeline</p>

      <div className="space-y-2">
        {PIPELINE_STEPS.map((step, i) => {
          const stepNum = i + 1;
          const isCurrent = status.current_step === step.key;
          const isDone =
            status.step_number > stepNum ||
            (status.completed && !status.error) ||
            (status.current_step === step.key && status.step_number > stepNum);
          const isSkipped =
            status.completed && status.step_number === 0 && !status.error;
          const isPast = status.step_number > stepNum;
          const Icon = step.icon;

          return (
            <div
              key={step.key}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-md transition-colors",
                isCurrent && "bg-muted",
              )}
            >
              {/* Step indicator */}
              <div className="flex-shrink-0">
                {isPast || (status.completed && !status.error) ? (
                  <div className="h-5 w-5 rounded-full bg-profit/10 flex items-center justify-center">
                    <Check className="h-3 w-3 text-profit" />
                  </div>
                ) : isCurrent ? (
                  <div className="h-5 w-5 rounded-full bg-foreground/10 flex items-center justify-center">
                    <Loader2 className="h-3 w-3 animate-spin" />
                  </div>
                ) : (
                  <div className="h-5 w-5 rounded-full border border-border/60 flex items-center justify-center">
                    <span className="text-[10px] text-muted-foreground">{stepNum}</span>
                  </div>
                )}
              </div>

              {/* Step info */}
              <div className="flex-1 min-w-0">
                <p className={cn(
                  "text-xs font-medium",
                  isCurrent ? "text-foreground" : isPast ? "text-muted-foreground" : "text-muted-foreground/60",
                )}>
                  {step.label}
                </p>
                {isCurrent && (
                  <p className="text-[11px] text-muted-foreground/60 mt-0.5">
                    {status.detail || step.detail}
                  </p>
                )}
              </div>

              {/* Status label */}
              {isPast && (
                <span className="text-[11px] text-profit">Done</span>
              )}
              {isCurrent && (
                <span className="text-[11px] text-muted-foreground">Running...</span>
              )}
            </div>
          );
        })}
      </div>

      {status.error && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-loss/5 border border-loss/20">
          <XCircle className="h-3.5 w-3.5 text-loss flex-shrink-0" />
          <p className="text-xs text-loss">{status.error}</p>
        </div>
      )}

      {status.completed && !status.error && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-profit/5 border border-profit/20">
          <CheckCircle2 className="h-3.5 w-3.5 text-profit flex-shrink-0" />
          <p className="text-xs text-profit">Pipeline complete — starting bot...</p>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// Settings Page
// =============================================================================

export default function SettingsPage() {
  const { data: health, refresh: refreshHealth } = useApi(api.health, { pollInterval: 10000 });
  const { data: auth, refresh: refreshAuth } = useApi(api.authStatus);
  const { data: botStatus, refresh: refreshBot } = useApi(api.botStatus, { pollInterval: 5000 });
  const { data: risk, refresh: refreshRisk } = useApi(api.botRisk, {
    immediate: false,
    pollInterval: botStatus?.status === "running" ? 10000 : 0,
  });

  const [connecting, setConnecting] = useState(false);
  const [botAction, setBotAction] = useState<string | null>(null);
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(null);
  const [showPipeline, setShowPipeline] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const connected = health?.components?.broker_authenticated;

  const handleConnect = async () => {
    setConnecting(true);
    try {
      await api.connect(true);
      await refreshHealth();
      await refreshAuth();
    } catch {
      // Error handled
    } finally {
      setConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    try {
      await api.disconnect();
      await refreshHealth();
      await refreshAuth();
    } catch {
      // Error handled
    }
  };

  // Stop polling pipeline status
  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // Start bot: prepare pipeline first, poll for progress, then start engine
  const handleStartBot = async () => {
    setBotAction("preparing");
    setShowPipeline(true);
    setPipelineStatus(null);

    try {
      // Trigger pipeline preparation
      await api.botPrepare();

      // Poll for pipeline progress
      pollRef.current = setInterval(async () => {
        try {
          const status = await api.botPrepareStatus();
          setPipelineStatus(status);

          if (!status.running && (status.completed || status.error)) {
            stopPolling();

            if (status.completed && !status.error) {
              // Pipeline done — now start the bot
              setBotAction("starting");
              await api.botStart();
              await refreshBot();
              await refreshRisk();
              setBotAction(null);
            } else {
              // Pipeline failed
              setBotAction(null);
            }
          }
        } catch {
          stopPolling();
          setBotAction(null);
        }
      }, 1000);
    } catch {
      setBotAction(null);
      setShowPipeline(false);
    }
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  const handleStopBot = async (squareOff = false) => {
    setBotAction("stopping");
    try {
      await api.botStop(squareOff);
      await refreshBot();
      setShowPipeline(false);
      setPipelineStatus(null);
    } catch {
      // Error handled
    } finally {
      setBotAction(null);
    }
  };

  const handleSquareOff = async () => {
    if (!confirm("Square off ALL open positions?")) return;
    setBotAction("squaring_off");
    try {
      await api.botSquareOff();
      await refreshBot();
    } catch {
      // Error handled
    } finally {
      setBotAction(null);
    }
  };

  return (
    <div className="px-6 py-6 space-y-6 max-w-3xl mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Settings</h1>
        <p className="text-xs text-muted-foreground">
          Bot control, authentication, and risk management
        </p>
      </div>

      {/* Authentication */}
      <Card>
        <CardHeader className="pb-2 px-4 pt-3">
          <CardTitle className="text-sm font-medium flex items-center gap-1.5">
            <User className="h-3.5 w-3.5" />
            Zerodha Authentication
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">
                {auth?.authenticated ? "Zerodha Broker" : "Not connected"}
              </p>
              <p className="text-xs text-muted-foreground">
                {auth?.authenticated ? "Authenticated via OAuth" : "Run 'make deploy-auth' to authenticate"}
              </p>
              {auth?.expires_at && (
                <p className="text-[11px] text-muted-foreground/60 mt-0.5">
                  Expires: {auth.expires_at}
                </p>
              )}
            </div>
            <div className="flex items-center gap-2">
              {connected ? (
                <Badge variant="outline" className="text-xs text-profit border-profit/20">
                  <CheckCircle2 className="h-3 w-3 mr-1" />
                  Connected
                </Badge>
              ) : (
                <Badge variant="outline" className="text-xs text-muted-foreground">
                  <XCircle className="h-3 w-3 mr-1" />
                  Disconnected
                </Badge>
              )}
            </div>
          </div>

          <Separator className="opacity-50" />

          <div className="flex gap-2">
            {!connected ? (
              <button
                onClick={handleConnect}
                disabled={connecting}
                className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-md bg-foreground text-background hover:opacity-80 transition-colors disabled:opacity-30"
              >
                {connecting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Power className="h-3.5 w-3.5" />
                )}
                {connecting ? "Connecting..." : "Connect (Paper Mode)"}
              </button>
            ) : (
              <button
                onClick={handleDisconnect}
                className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-md border border-border/60 text-foreground hover:bg-muted/50 transition-colors"
              >
                <PowerOff className="h-3.5 w-3.5" />
                Disconnect
              </button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Bot Control */}
      <Card>
        <CardHeader className="pb-2 px-4 pt-3">
          <CardTitle className="text-sm font-medium flex items-center gap-1.5">
            <Settings className="h-3.5 w-3.5" />
            Bot Control
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Trading Bot</p>
              <p className="text-xs text-muted-foreground">
                {botStatus?.status === "running"
                  ? `Running — ${botStatus.cycle_count} cycles completed`
                  : botAction === "preparing"
                    ? "Preparing ML pipeline..."
                    : botAction === "starting"
                      ? "Starting trading engine..."
                      : "Stopped"}
              </p>
              {botStatus?.symbols_count ? (
                <p className="text-[11px] text-muted-foreground/60 mt-0.5">
                  Tracking {botStatus.symbols_count} symbols
                </p>
              ) : null}
            </div>
            <Badge
              variant="outline"
              className={cn(
                "text-xs",
                botStatus?.status === "running"
                  ? "text-profit border-profit/20"
                  : botAction
                    ? "text-warning border-warning/20"
                    : "text-muted-foreground border-border/60"
              )}
            >
              {botStatus?.status === "running" && (
                <span className="h-1.5 w-1.5 rounded-full bg-profit mr-1.5 animate-pulse" />
              )}
              {botAction === "preparing" && (
                <Loader2 className="h-3 w-3 mr-1 animate-spin" />
              )}
              {botStatus?.status === "running"
                ? "Running"
                : botAction
                  ? "Preparing"
                  : "Stopped"}
            </Badge>
          </div>

          {/* Pipeline Progress */}
          <PipelineProgress status={pipelineStatus} visible={showPipeline && botAction === "preparing"} />

          <Separator className="opacity-50" />

          <div className="flex gap-2">
            {botStatus?.status !== "running" ? (
              <button
                onClick={handleStartBot}
                disabled={!connected || botAction !== null}
                className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-md bg-profit text-white hover:opacity-80 transition-colors disabled:opacity-30"
              >
                {botAction ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Power className="h-3.5 w-3.5" />
                )}
                {botAction === "preparing"
                  ? "Preparing..."
                  : botAction === "starting"
                    ? "Starting..."
                    : "Start Bot"}
              </button>
            ) : (
              <button
                onClick={() => handleStopBot(false)}
                disabled={botAction !== null}
                className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-md border border-border/60 text-foreground hover:bg-muted/50 transition-colors disabled:opacity-30"
              >
                {botAction === "stopping" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <PowerOff className="h-3.5 w-3.5" />
                )}
                Stop Bot
              </button>
            )}

            <button
              onClick={handleSquareOff}
              disabled={!connected || botAction !== null}
              className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-md border border-loss/30 text-loss hover:bg-loss/5 transition-colors disabled:opacity-30"
            >
              <AlertTriangle className="h-3.5 w-3.5" />
              Square Off All
            </button>
          </div>

          {!connected && (
            <p className="text-[11px] text-muted-foreground/60">
              Connect to Zerodha first to control the bot
            </p>
          )}
        </CardContent>
      </Card>

      {/* Risk Management */}
      <Card>
        <CardHeader className="pb-2 px-4 pt-3">
          <CardTitle className="text-sm font-medium flex items-center gap-1.5">
            <ShieldAlert className="h-3.5 w-3.5" />
            Risk Management
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          {/* Shorting Toggle */}
          <div className="flex items-center justify-between pb-3 border-b border-border/50">
            <div>
              <p className="text-sm font-medium">Short Selling</p>
              <p className="text-xs text-muted-foreground">
                Enable selling first to profit from price drops
              </p>
            </div>
            <Switch
              checked={risk?.shorting_enabled ?? true}
              onCheckedChange={async (checked) => {
                try {
                  await api.botShorting(checked);
                  refreshRisk();
                } catch { /* ignore */ }
              }}
              disabled={botStatus?.status !== "running"}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <RiskItem label="Long Position Max" value="5% of capital" />
            <RiskItem label="Short Position Max" value="3% of capital" />
            <RiskItem label="Long Exposure Max" value="20%" />
            <RiskItem label="Short Exposure Max" value="15%" />
            <RiskItem label="Combined Exposure Max" value="25%" />
            <RiskItem label="Max Daily Loss" value="3%" />
            <RiskItem label="Max Drawdown" value="10%" />
            <RiskItem label="Trade Cooldown" value="60 seconds" />
            <RiskItem label="Max Trades/Day" value="20" />
            <RiskItem label="Short Stop-Loss" value="1.5%" />
            <RiskItem label="Long Stop-Loss" value="2%" />
            <RiskItem label="Short Max Hold" value="90 min" />
          </div>

          {risk && (
            <>
              <Separator className="opacity-50 my-4" />
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">Circuit Breaker</span>
                  <Badge
                    variant="outline"
                    className={cn(
                      "text-xs",
                      risk.circuit_breaker_triggered
                        ? "text-loss border-loss/20"
                        : "text-profit border-profit/20"
                    )}
                  >
                    {risk.circuit_breaker_triggered ? "TRIGGERED" : "OK"}
                  </Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">Trades Today</span>
                  <span className="text-xs font-medium">{risk.trades_today} / {risk.max_trades}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">Daily P&L</span>
                  <span className={cn(
                    "text-xs font-medium",
                    risk.daily_pnl > 0 ? "text-profit" : risk.daily_pnl < 0 ? "text-loss" : ""
                  )}>
                    {formatCurrency(risk.daily_pnl)}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">Long Exposure</span>
                  <span className="text-xs font-medium">
                    {(risk.long_exposure * 100).toFixed(1)}% / {(risk.max_long_exposure * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">Short Exposure</span>
                  <span className="text-xs font-medium">
                    {(risk.short_exposure * 100).toFixed(1)}% / {(risk.max_short_exposure * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">Risk Score</span>
                  <span className="text-xs font-medium">
                    {(risk.risk_score * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function RiskItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-medium">{value}</p>
    </div>
  );
}
