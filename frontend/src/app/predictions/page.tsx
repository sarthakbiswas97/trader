"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  BrainCircuit,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  Loader2,
  ChevronDown,
  ChevronRight,
  Clock,
  History,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { StatCard } from "@/components/stat-card";
import {
  type Prediction,
  type PredictionSession,
  PREDICTIONS_STREAM_URL,
  api,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { MarketStatusBanner } from "@/components/market-status";

function PredictionCard({ prediction }: { prediction: Prediction }) {
  const isUp = prediction.direction === "UP";
  const isDown = prediction.direction === "DOWN";

  return (
    <Card
      className={cn(
        "transition-all animate-in fade-in slide-in-from-bottom-2 duration-300",
        isUp && "border-profit/20",
        isDown && "border-loss/20",
      )}
    >
      <CardContent className="px-4 py-3">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            {isUp ? (
              <ArrowUpRight className="h-4 w-4 text-profit" />
            ) : isDown ? (
              <ArrowDownRight className="h-4 w-4 text-loss" />
            ) : (
              <Minus className="h-4 w-4 text-muted-foreground" />
            )}
            <span className="text-sm font-semibold">{prediction.symbol}</span>
          </div>
          <Badge
            variant="outline"
            className={cn(
              "text-xs",
              isUp && "text-profit border-profit/20",
              isDown && "text-loss border-loss/20",
              !isUp && !isDown && "text-muted-foreground border-border/60",
            )}
          >
            {prediction.direction}
          </Badge>
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">Probability</span>
            <span className="text-xs font-medium">
              {(prediction.probability * 100).toFixed(1)}%
            </span>
          </div>
          <div className="w-full h-1.5 rounded-full bg-muted overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all",
                isUp ? "bg-profit" : isDown ? "bg-loss" : "bg-muted-foreground/30",
              )}
              style={{ width: `${prediction.probability * 100}%` }}
            />
          </div>

          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">Confidence</span>
            <span className="text-xs font-medium">
              {(prediction.confidence * 100).toFixed(1)}%
            </span>
          </div>
          <div className="w-full h-1.5 rounded-full bg-muted overflow-hidden">
            <div
              className="h-full rounded-full bg-muted-foreground/30 transition-all"
              style={{ width: `${prediction.confidence * 100}%` }}
            />
          </div>
        </div>

        {prediction.top_features && prediction.top_features.length > 0 && (
          <div className="mt-3 pt-2 border-t border-border/50">
            <p className="text-[11px] text-muted-foreground/60 mb-1">
              Top Features
            </p>
            <div className="flex flex-wrap gap-1">
              {prediction.top_features.map(([name, weight]) => (
                <span
                  key={name}
                  className="text-[11px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground"
                >
                  {name}: {(weight as number).toFixed(2)}
                </span>
              ))}
            </div>
          </div>
        )}

        {(prediction.is_long_signal || prediction.is_short_signal) && (
          <div className="mt-2">
            <Badge
              className={cn(
                "text-[11px]",
                prediction.is_long_signal
                  ? "bg-profit/10 text-profit border-profit/20 hover:bg-profit/10"
                  : "bg-loss/10 text-loss border-loss/20 hover:bg-loss/10",
              )}
            >
              {prediction.is_long_signal ? "Long Signal" : "Short Signal"}
            </Badge>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function HistorySessionCard({ session }: { session: PredictionSession }) {
  const [expanded, setExpanded] = useState(false);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [loading, setLoading] = useState(false);

  const handleExpand = async () => {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (predictions.length > 0) return;

    setLoading(true);
    try {
      const data = await api.predictionSession(session.session_id);
      setPredictions(data.predictions);
    } catch {
      /* empty */
    }
    setLoading(false);
  };

  const date = new Date(session.generated_at);
  const dateStr = date.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
  const timeStr = date.toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
  });

  const upPredictions = predictions.filter((p) => p.direction === "UP");
  const downPredictions = predictions.filter((p) => p.direction === "DOWN");
  const neutralPredictions = predictions.filter((p) => p.direction === "NEUTRAL");

  return (
    <Card className="overflow-hidden">
      <button
        onClick={handleExpand}
        className="w-full px-4 py-3 flex items-center justify-between hover:bg-muted/30 transition-colors"
      >
        <div className="flex items-center gap-3">
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
          <div className="text-left">
            <p className="text-sm font-medium">{dateStr}</p>
            <p className="text-xs text-muted-foreground flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {timeStr}
              <span className="mx-1">·</span>
              {session.source === "manual" ? "Manual" : "Bot"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-[11px]">
            {session.total} stocks
          </Badge>
          <Badge
            variant="outline"
            className="text-[11px] text-profit border-profit/20"
          >
            {session.up_signals} UP
          </Badge>
          <Badge
            variant="outline"
            className="text-[11px] text-loss border-loss/20"
          >
            {session.down_signals} DOWN
          </Badge>
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t border-border/50">
          {loading ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground/50" />
            </div>
          ) : (
            <div className="space-y-4 pt-3">
              {upPredictions.length > 0 && (
                <div>
                  <h3 className="text-xs font-medium text-profit mb-2 flex items-center gap-1">
                    <ArrowUpRight className="h-3.5 w-3.5" />
                    UP ({upPredictions.length})
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                    {upPredictions.map((p) => (
                      <PredictionCard key={p.symbol} prediction={p} />
                    ))}
                  </div>
                </div>
              )}
              {downPredictions.length > 0 && (
                <div>
                  <h3 className="text-xs font-medium text-loss mb-2 flex items-center gap-1">
                    <ArrowDownRight className="h-3.5 w-3.5" />
                    DOWN ({downPredictions.length})
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                    {downPredictions.map((p) => (
                      <PredictionCard key={p.symbol} prediction={p} />
                    ))}
                  </div>
                </div>
              )}
              {neutralPredictions.length > 0 && (
                <div>
                  <h3 className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1">
                    <Minus className="h-3.5 w-3.5" />
                    NEUTRAL ({neutralPredictions.length})
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                    {neutralPredictions.map((p) => (
                      <PredictionCard key={p.symbol} prediction={p} />
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

export default function PredictionsPage() {
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [progress, setProgress] = useState({ current: 0, total: 0, symbol: "" });
  const [summary, setSummary] = useState<{
    up_signals: number;
    down_signals: number;
    neutral_signals: number;
    symbols_analyzed: number;
    generated_at: string;
  } | null>(null);
  const [sessions, setSessions] = useState<PredictionSession[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const eventSourceRef = useRef<EventSource | null>(null);

  // Load history on mount
  useEffect(() => {
    api
      .predictionHistory(10)
      .then((data) => setSessions(data.sessions))
      .catch(() => {})
      .finally(() => setLoadingHistory(false));
  }, []);

  const stopStream = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setStreaming(false);
  }, []);

  useEffect(() => {
    return () => stopStream();
  }, [stopStream]);

  const handleGenerate = () => {
    setPredictions([]);
    setSummary(null);
    setStreaming(true);
    setProgress({ current: 0, total: 0, symbol: "" });

    const es = new EventSource(PREDICTIONS_STREAM_URL);
    eventSourceRef.current = es;

    es.addEventListener("prediction", (e) => {
      const pred = JSON.parse(e.data) as Prediction;
      setPredictions((prev) => {
        const updated = [...prev, pred];
        updated.sort((a, b) => b.confidence - a.confidence);
        return updated;
      });
    });

    es.addEventListener("progress", (e) => {
      const data = JSON.parse(e.data);
      setProgress(data);
    });

    es.addEventListener("done", (e) => {
      const data = JSON.parse(e.data);
      setSummary(data);
      stopStream();
      // Refresh history to include the new session
      api
        .predictionHistory(10)
        .then((d) => setSessions(d.sessions))
        .catch(() => {});
    });

    es.addEventListener("error", () => {
      stopStream();
    });
  };

  const upSignals = predictions.filter((p) => p.direction === "UP");
  const downSignals = predictions.filter((p) => p.direction === "DOWN");
  const neutralSignals = predictions.filter((p) => p.direction === "NEUTRAL");

  return (
    <div className="px-6 py-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Predictions</h1>
          <p className="text-xs text-muted-foreground">
            ML-powered price direction predictions for NIFTY 100
          </p>
        </div>
        <button
          onClick={streaming ? stopStream : handleGenerate}
          className={cn(
            "flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-md transition-colors",
            streaming
              ? "border border-border/60 text-foreground hover:bg-muted/50"
              : "bg-foreground text-background hover:opacity-80",
          )}
        >
          {streaming ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Stop
            </>
          ) : (
            <>
              <BrainCircuit className="h-3.5 w-3.5" />
              Generate Predictions
            </>
          )}
        </button>
      </div>

      {/* Market Status */}
      <MarketStatusBanner />

      {/* Progress Bar */}
      {streaming && progress.total > 0 && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              Analyzing {progress.symbol}...
            </span>
            <span className="text-xs font-medium">
              {progress.current}/{progress.total}
            </span>
          </div>
          <div className="w-full h-1.5 rounded-full bg-muted overflow-hidden">
            <div
              className="h-full rounded-full bg-foreground/50 transition-all duration-300"
              style={{
                width: `${(progress.current / progress.total) * 100}%`,
              }}
            />
          </div>
        </div>
      )}

      {/* Summary Stats */}
      {(summary || predictions.length > 0) && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <StatCard
            title="Analyzed"
            value={String(summary?.symbols_analyzed ?? predictions.length)}
          />
          <StatCard
            title="UP Signals"
            value={String(summary?.up_signals ?? upSignals.length)}
            trend={upSignals.length > 0 ? "profit" : "neutral"}
          />
          <StatCard
            title="DOWN Signals"
            value={String(summary?.down_signals ?? downSignals.length)}
            trend={downSignals.length > 0 ? "loss" : "neutral"}
          />
          <StatCard
            title="NEUTRAL"
            value={String(summary?.neutral_signals ?? neutralSignals.length)}
          />
          <StatCard
            title="Generated"
            value={
              summary?.generated_at
                ? new Date(summary.generated_at).toLocaleTimeString()
                : streaming
                  ? "In progress..."
                  : "—"
            }
          />
        </div>
      )}

      {/* Empty State */}
      {!streaming && predictions.length === 0 && sessions.length === 0 && !loadingHistory && (
        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground/50">
          <BrainCircuit className="h-10 w-10 mb-3" />
          <p className="text-sm font-medium">No predictions generated</p>
          <p className="text-xs mt-1">
            Click &quot;Generate Predictions&quot; to stream-analyze all 100
            NIFTY 100 stocks
          </p>
        </div>
      )}

      {/* Current Prediction Cards — grouped by direction */}
      {predictions.length > 0 && (
        <div className="space-y-4">
          {upSignals.length > 0 && (
            <div>
              <h2 className="text-sm font-medium text-profit mb-3 flex items-center gap-1.5">
                <ArrowUpRight className="h-4 w-4" />
                UP Signals ({upSignals.length})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {upSignals.map((p) => (
                  <PredictionCard key={p.symbol} prediction={p} />
                ))}
              </div>
            </div>
          )}

          {downSignals.length > 0 && (
            <div>
              <h2 className="text-sm font-medium text-loss mb-3 flex items-center gap-1.5">
                <ArrowDownRight className="h-4 w-4" />
                DOWN Signals ({downSignals.length})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {downSignals.map((p) => (
                  <PredictionCard key={p.symbol} prediction={p} />
                ))}
              </div>
            </div>
          )}

          {neutralSignals.length > 0 && (
            <div>
              <h2 className="text-sm font-medium text-muted-foreground mb-3 flex items-center gap-1.5">
                <Minus className="h-4 w-4" />
                NEUTRAL ({neutralSignals.length})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {neutralSignals.map((p) => (
                  <PredictionCard key={p.symbol} prediction={p} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Loading spinner at bottom while streaming */}
      {streaming && predictions.length > 0 && (
        <div className="flex items-center justify-center py-4">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground/50" />
        </div>
      )}

      {/* History Section */}
      {sessions.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-medium flex items-center gap-1.5 text-muted-foreground">
            <History className="h-4 w-4" />
            Past Predictions
          </h2>
          <div className="space-y-2">
            {sessions.map((session) => (
              <HistorySessionCard key={session.session_id} session={session} />
            ))}
          </div>
        </div>
      )}

      {loadingHistory && !streaming && predictions.length === 0 && (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground/50" />
        </div>
      )}
    </div>
  );
}
