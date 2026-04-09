"""
Ops agents — helper scripts invoked by Claude Code scheduled agents.

These modules do the actual work (HTTP calls, DB queries, file writes).
The Claude agents (registered via /schedule and /loop) call them via `make`
targets and decide what to do with the structured output.

Modules:
    health_check        Morning ops: verify session, data, bot
    post_market_report  Evening ops: analyze today's trades and write a report
    live_monitor        Mid-day ops: check risk/bot health
    report_writer       Shared util for writing reports to backend/data/ops_reports/
"""
