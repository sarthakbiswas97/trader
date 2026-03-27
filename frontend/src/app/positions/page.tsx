"use client";

import { RefreshCw, TrendingUp, ArrowUpRight, ArrowDownRight } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PnlText, formatCurrency } from "@/components/pnl-text";
import { StatCard } from "@/components/stat-card";
import { useApi } from "@/hooks/use-api";
import { api } from "@/lib/api";

export default function PositionsPage() {
  const { data: positions, loading, refresh } = useApi(api.positions, { pollInterval: 10000 });
  const { data: trades, refresh: refreshTrades } = useApi(() => api.trades(50));

  const summary = positions?.summary;

  return (
    <div className="px-6 py-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Positions</h1>
          <p className="text-xs text-muted-foreground">Open positions and trade history</p>
        </div>
        <button
          onClick={() => { refresh(); refreshTrades(); }}
          className="h-7 w-7 rounded-md flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          aria-label="Refresh"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard
            title="Invested Value"
            value={formatCurrency(summary.invested_value)}
          />
          <StatCard
            title="Current Value"
            value={formatCurrency(summary.current_value)}
          />
          <StatCard
            title="Unrealized P&L"
            value={formatCurrency(summary.unrealized_pnl)}
            trend={summary.unrealized_pnl > 0 ? "profit" : summary.unrealized_pnl < 0 ? "loss" : "neutral"}
          />
          <StatCard
            title="Realized P&L"
            value={formatCurrency(summary.realized_pnl)}
            trend={summary.realized_pnl > 0 ? "profit" : summary.realized_pnl < 0 ? "loss" : "neutral"}
          />
        </div>
      )}

      <Tabs defaultValue="positions">
        <TabsList>
          <TabsTrigger value="positions" className="text-xs">
            Open Positions ({positions?.positions.length ?? 0})
          </TabsTrigger>
          <TabsTrigger value="history" className="text-xs">
            Trade History ({trades?.total_count ?? 0})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="positions">
          <Card>
            <CardContent className="px-4 py-3">
              {!positions || positions.positions.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-muted-foreground/50">
                  <TrendingUp className="h-10 w-10 mb-3" />
                  <p className="text-sm font-medium">No open positions</p>
                  <p className="text-xs mt-1">Positions will appear here when the bot executes trades</p>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-xs">Symbol</TableHead>
                      <TableHead className="text-xs text-right">Qty</TableHead>
                      <TableHead className="text-xs text-right">Avg Price</TableHead>
                      <TableHead className="text-xs text-right">Current</TableHead>
                      <TableHead className="text-xs text-right">P&L</TableHead>
                      <TableHead className="text-xs text-right">P&L %</TableHead>
                      <TableHead className="text-xs">Entry Reason</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {positions.positions.map((p) => (
                      <TableRow key={p.symbol}>
                        <TableCell className="text-sm font-medium">
                          <div className="flex items-center gap-1.5">
                            {p.pnl >= 0 ? (
                              <ArrowUpRight className="h-3.5 w-3.5 text-profit" />
                            ) : (
                              <ArrowDownRight className="h-3.5 w-3.5 text-loss" />
                            )}
                            {p.symbol}
                          </div>
                        </TableCell>
                        <TableCell className="text-sm text-right">{p.quantity}</TableCell>
                        <TableCell className="text-sm text-right">{formatCurrency(p.avg_price)}</TableCell>
                        <TableCell className="text-sm text-right">{formatCurrency(p.current_price)}</TableCell>
                        <TableCell className="text-right">
                          <PnlText value={p.pnl} className="text-sm" />
                        </TableCell>
                        <TableCell className="text-right">
                          <PnlText value={p.pnl_percent} className="text-sm" prefix={p.pnl_percent > 0 ? "+" : ""} showSign={false} />
                          <span className="text-xs text-muted-foreground">%</span>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {p.entry_reason || "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="history">
          <Card>
            <CardContent className="px-4 py-3">
              {!trades || trades.trades.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-muted-foreground/50">
                  <TrendingUp className="h-10 w-10 mb-3" />
                  <p className="text-sm font-medium">No trade history</p>
                  <p className="text-xs mt-1">Completed trades will appear here</p>
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-3 mb-4">
                    <Badge variant="outline" className="text-xs">
                      Total: {trades.total_count}
                    </Badge>
                    <Badge variant="outline" className="text-xs text-profit border-profit/20">
                      Won: {trades.winning_trades}
                    </Badge>
                    <Badge variant="outline" className="text-xs text-loss border-loss/20">
                      Lost: {trades.losing_trades}
                    </Badge>
                    <Badge variant="outline" className="text-xs">
                      Win Rate: {trades.win_rate.toFixed(1)}%
                    </Badge>
                  </div>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="text-xs">Symbol</TableHead>
                        <TableHead className="text-xs">Side</TableHead>
                        <TableHead className="text-xs text-right">Qty</TableHead>
                        <TableHead className="text-xs text-right">Price</TableHead>
                        <TableHead className="text-xs">Time</TableHead>
                        <TableHead className="text-xs">Reason</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {trades.trades.map((t) => (
                        <TableRow key={t.id}>
                          <TableCell className="text-sm font-medium">{t.symbol}</TableCell>
                          <TableCell>
                            <Badge
                              variant="outline"
                              className={
                                t.side === "BUY"
                                  ? "text-profit border-profit/20 text-xs"
                                  : "text-loss border-loss/20 text-xs"
                              }
                            >
                              {t.side}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-sm text-right">{t.quantity}</TableCell>
                          <TableCell className="text-sm text-right">
                            {formatCurrency(t.entry_price)}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {new Date(t.entry_time).toLocaleString()}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {t.exit_reason || "—"}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
