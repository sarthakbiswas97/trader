"""
Post-market report agent — invoked by the scheduled Claude agent at ~3:35 PM IST.

Queries Neon Postgres directly via existing repositories and writes a markdown
summary to backend/data/ops_reports/{today}.md. Returns a structured summary
dict for the calling agent to extend with commentary.

Output sections:
  - Summary (capital, P&L, regime)
  - Trades opened today
  - Trades closed today
  - Kill switches / regime transitions
  - Stocks ranked highest but skipped (counterfactual)

Usage:
    python -m backend.agents.post_market_report [--for-date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import desc

from backend.agents.report_writer import write_report
from backend.db.database import get_session
from backend.db.models import (
    DailySnapshot,
    RegimeHistory,
    StockScore,
    Trade,
)


@dataclass
class PostMarketSummary:
    report_date: str
    report_path: str | None = None
    snapshot_present: bool = False
    capital: float = 0.0
    portfolio_value: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    regime: str | None = None
    rolling_ic: float | None = None
    kill_switch: bool = False
    entries_today: int = 0
    exits_today: int = 0
    realized_pnl_today: float = 0.0
    win_rate_today: float | None = None
    regime_transition: dict[str, Any] | None = None
    skipped_top_picks: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


def _format_trade_row(t: Trade) -> str:
    pnl = f"{t.net_pnl:+,.0f}" if t.net_pnl is not None else "—"
    pnl_pct = f"{t.pnl_pct*100:+.2f}%" if t.pnl_pct is not None else "—"
    reason = t.exit_reason or "—"
    return f"| {t.symbol} | {t.engine} | {t.quantity} | {t.entry_price:,.2f} | {t.exit_price or 0:,.2f} | {pnl} | {pnl_pct} | {reason} |"


def _format_entry_row(t: Trade) -> str:
    score = f"{t.entry_score:.3f}" if t.entry_score is not None else "—"
    ret_5d = f"{t.ret_5d_at_entry*100:+.2f}%" if t.ret_5d_at_entry is not None else "—"
    return f"| {t.symbol} | {t.engine} | {t.quantity} | {t.entry_price:,.2f} | {score} | {ret_5d} | {t.regime_at_entry or '—'} |"


def _build_markdown(summary: PostMarketSummary, opened: list[Trade], closed: list[Trade]) -> str:
    lines: list[str] = []
    lines.append(f"# Post-Market Report — {summary.report_date}")
    lines.append("")
    lines.append("## Snapshot")
    if not summary.snapshot_present:
        lines.append("_No daily snapshot for this date — bot may not have run._")
    else:
        lines.append(f"- **Regime**: {summary.regime}")
        lines.append(f"- **Capital**: ₹{summary.capital:,.0f}")
        lines.append(f"- **Portfolio Value**: ₹{summary.portfolio_value:,.0f}")
        lines.append(f"- **Total P&L**: ₹{summary.total_pnl:+,.0f} ({summary.total_pnl_pct*100:+.2f}%)")
        if summary.rolling_ic is not None:
            lines.append(f"- **Rolling IC**: {summary.rolling_ic:+.4f}")
        if summary.kill_switch:
            lines.append("- **KILL SWITCH ACTIVE**")
    lines.append("")

    lines.append("## Today's Activity")
    lines.append(f"- Entries: **{summary.entries_today}**")
    lines.append(f"- Exits: **{summary.exits_today}**")
    lines.append(f"- Realized P&L: **₹{summary.realized_pnl_today:+,.0f}**")
    if summary.win_rate_today is not None:
        lines.append(f"- Win rate (today): **{summary.win_rate_today*100:.1f}%**")
    lines.append("")

    if opened:
        lines.append("## Entries")
        lines.append("| Symbol | Engine | Qty | Entry | Score | Ret5d | Regime |")
        lines.append("|---|---|---|---|---|---|---|")
        for t in opened:
            lines.append(_format_entry_row(t))
        lines.append("")

    if closed:
        lines.append("## Exits")
        lines.append("| Symbol | Engine | Qty | Entry | Exit | Net P&L | % | Reason |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for t in closed:
            lines.append(_format_trade_row(t))
        lines.append("")

    if summary.regime_transition:
        rt = summary.regime_transition
        lines.append("## Regime Transition")
        lines.append(f"- {rt['old_regime']} → {rt['new_regime']} (trigger: {rt.get('trigger', 'n/a')})")
        lines.append("")

    if summary.skipped_top_picks:
        lines.append("## Skipped Top Picks (counterfactual)")
        lines.append("| Symbol | Engine | Rank | Score | Skip Reason |")
        lines.append("|---|---|---|---|---|")
        for s in summary.skipped_top_picks:
            lines.append(
                f"| {s['symbol']} | {s['engine']} | {s['rank']} | {s['score']:.3f} | {s['reason']} |"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_summary(target_day: date) -> tuple[PostMarketSummary, list[Trade], list[Trade]]:
    """Query the DB and return a summary plus the raw trade rows for rendering."""
    summary = PostMarketSummary(report_date=target_day.isoformat())

    with get_session() as session:
        snapshot = (
            session.query(DailySnapshot)
            .filter(DailySnapshot.date == target_day)
            .one_or_none()
        )
        if snapshot is not None:
            summary.snapshot_present = True
            summary.capital = float(snapshot.total_capital or 0)
            summary.portfolio_value = float(snapshot.portfolio_value or 0)
            summary.total_pnl = float(snapshot.total_pnl or 0)
            summary.total_pnl_pct = float(snapshot.total_pnl_pct or 0)
            summary.regime = snapshot.regime
            summary.rolling_ic = (
                float(snapshot.rolling_ic) if snapshot.rolling_ic is not None else None
            )
            summary.kill_switch = bool(snapshot.kill_switch)
            summary.entries_today = int(snapshot.entries_count or 0)
            summary.exits_today = int(snapshot.exits_count or 0)

        opened = (
            session.query(Trade)
            .filter(Trade.entry_date == target_day)
            .order_by(Trade.engine, desc(Trade.entry_score))
            .all()
        )
        closed = (
            session.query(Trade)
            .filter(Trade.exit_date == target_day)
            .order_by(desc(Trade.net_pnl))
            .all()
        )

        # Override snapshot counts if missing
        if not summary.snapshot_present:
            summary.entries_today = len(opened)
            summary.exits_today = len(closed)

        if closed:
            realized = sum((t.net_pnl or 0.0) for t in closed)
            wins = sum(1 for t in closed if (t.net_pnl or 0) > 0)
            summary.realized_pnl_today = float(realized)
            summary.win_rate_today = wins / len(closed) if closed else None

        transition = (
            session.query(RegimeHistory)
            .filter(RegimeHistory.date == target_day)
            .order_by(desc(RegimeHistory.id))
            .first()
        )
        if transition is not None:
            summary.regime_transition = {
                "old_regime": transition.old_regime,
                "new_regime": transition.new_regime,
                "trigger": transition.trigger,
            }

        # Top picks the system saw but skipped
        skipped = (
            session.query(StockScore)
            .filter(
                StockScore.date == target_day,
                StockScore.skipped.is_(True),
            )
            .order_by(StockScore.rank_in_universe.asc())
            .limit(10)
            .all()
        )
        summary.skipped_top_picks = [
            {
                "symbol": s.symbol,
                "engine": s.engine,
                "rank": int(s.rank_in_universe or 0),
                "score": float(s.reversal_score or 0.0),
                "reason": s.skip_reason or "—",
            }
            for s in skipped
        ]

        # Detach the ORM objects so we can use them after the session closes
        session.expunge_all()

    return summary, opened, closed


def run_post_market_report(target_day: date | None = None) -> PostMarketSummary:
    """Build and persist today's post-market report."""
    target_day = target_day or date.today()
    summary, opened, closed = build_summary(target_day)
    markdown = _build_markdown(summary, opened, closed)
    path = write_report(category="post_market", day=target_day, content=markdown)
    summary.report_path = str(path)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--for-date", help="YYYY-MM-DD (defaults to today)")
    args = parser.parse_args()

    target = date.today()
    if args.for_date:
        target = datetime.strptime(args.for_date, "%Y-%m-%d").date()

    try:
        summary = run_post_market_report(target)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "report_date": target.isoformat()}))
        return 2

    print(summary.to_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
