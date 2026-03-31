# Deployment Guide

## Architecture

```
┌─────────────┐     ┌──────────────────────────────────┐     ┌──────────────┐
│   Browser   │────▶│  EC2 (Docker)                     │────▶│ Neon Postgres│
│  :3000      │     │  ├─ Next.js frontend  (:3000)     │     │  (cloud DB)  │
│             │     │  └─ FastAPI backend   (:8000)     │     └──────────────┘
└─────────────┘     └──────────────────────────────────┘
                         │
                    ┌────┴────┐
                    │ Zerodha │ (market data, optional)
                    │ Kite API│
                    └─────────┘
```

**Key:** The system works without Zerodha authentication. Visitors see the dashboard in paper-only mode with persisted data from Postgres.

---

## Option A: AWS EC2 (Recommended)

### 1. Launch Instance

- **Type:** t3.small (2 vCPU, 2GB RAM) — ~$8-17/month
- **AMI:** Ubuntu 24.04 LTS
- **Storage:** 20 GB
- **Security Group:**

```
Inbound Rules:
  SSH    (22)    → Your IP only
  HTTP   (3000)  → 0.0.0.0/0  (frontend)
  Custom (8000)  → 0.0.0.0/0  (backend API)
```

### 2. Install Docker

```bash
ssh -i your-key.pem ubuntu@<EC2_IP>

sudo apt update && sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker ubuntu
exit  # Logout and re-login for group change
```

### 3. Clone & Configure

```bash
ssh -i your-key.pem ubuntu@<EC2_IP>

git clone https://github.com/YOUR_USERNAME/trader.git
cd trader

# Create .env
cat > .env << 'EOF'
KITE_API_KEY=your_api_key
KITE_API_SECRET=your_api_secret

TRADING_MODE=paper
PAPER_TRADING_CAPITAL=100000

DATABASE_URL=postgresql://user:pass@ep-xxx.region.aws.neon.tech/dbname?sslmode=require

ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=INFO
EOF
```

**Important:** Set `DEBUG=false` in production — this disables Swagger docs at `/docs`.

### 4. Update Kite Redirect URL

In [Kite Developer Console](https://developers.kite.trade), change redirect URL to:

```
http://<EC2_IP>:8000/api/v1/auth/callback
```

### 5. Build & Launch

```bash
docker compose up -d --build
```

First build takes 3-5 minutes. Monitor:

```bash
docker compose logs -f
```

### 6. Verify

```bash
# Health check
curl http://localhost:8000/api/v1/health

# Frontend
curl -s http://localhost:3000 | head -5
```

**Access:**
- Frontend: `http://<EC2_IP>:3000`
- API: `http://<EC2_IP>:8000`
- Multi-engine status: `http://<EC2_IP>:8000/api/v1/bot/multi-engine`

---

## Option B: Any VPS / Local Docker

Same steps as above, just replace EC2 with your server. Minimum requirements:
- 2GB RAM, 1 vCPU, 10GB disk
- Docker + Docker Compose
- Ports 3000 and 8000 open

---

## Post-Deploy Setup

### Authenticate with Zerodha (optional)

The system works without Kite auth — visitors see paper trading with saved data. To enable live market data:

1. Open `http://<EC2_IP>:3000/settings`
2. Click "Login with Zerodha"
3. Complete Zerodha login → redirected back → token saved
4. Dashboard switches from "paper_only" to "live_data" mode

**Note:** Kite tokens expire at 6 AM daily. The system auto-falls back to paper-only mode for visitors.

### Run Multi-Engine (Daily)

After authenticating each morning:

```bash
# Run from inside the container
docker compose exec trader python3 -m backend.scripts.run_multi_engine

# Or check status
docker compose exec trader python3 -m backend.scripts.run_multi_engine --status
```

This enters new reversal positions and exits mature ones. Results persist to Neon Postgres.

### Set Up Daily Cron (Optional)

To run the multi-engine automatically at 9:45 AM IST:

```bash
crontab -e
```

Add:
```
15 4 * * 1-5 cd /home/ubuntu/trader && docker compose exec -T trader python3 -m backend.scripts.run_multi_engine >> /var/log/trader.log 2>&1
```

(9:45 AM IST = 4:15 AM UTC)

---

## Database (Neon Postgres)

The system persists trades, snapshots, and scores to Neon Postgres. Setup:

1. Create free account at [neon.tech](https://neon.tech)
2. Create a database
3. Copy connection string to `DATABASE_URL` in `.env`
4. Tables are created automatically on first run

If Neon is down, the system continues with JSON file storage — no data loss.

### Create Tables Manually (if needed)

```bash
docker compose exec trader python3 -m backend.scripts.setup_db
```

---

## Updating

```bash
cd trader
git pull
docker compose up -d --build
```

Build caches layers — rebuilds take ~1 minute unless dependencies changed.

---

## Monitoring

### Health Endpoint

```
GET http://<EC2_IP>:8000/api/v1/health
```

Returns:
```json
{
  "status": "healthy",
  "components": {
    "api": true,
    "broker_authenticated": true,
    "broker_mode": "paper_only",
    "bot_running": false,
    "model_available": true,
    "session_valid": false
  }
}
```

### Docker Logs

```bash
docker compose logs -f --tail 100
docker compose logs -f trader  # Just the app
```

### Restart

```bash
docker compose restart
docker compose down && docker compose up -d  # Full restart
```

---

## Troubleshooting

### "Connection refused" on port 3000 or 8000

```bash
docker compose ps          # Check if container is running
docker compose logs --tail 50  # Check for errors
```

### Frontend shows "Connecting..."

Normal on first load — auto paper-connect takes 1-2 seconds. If it stays stuck:
- Check backend is running: `curl http://localhost:8000/api/v1/health`
- Check CORS: `.env` should have the right `ENVIRONMENT` setting

### Database connection fails

- Check `DATABASE_URL` in `.env` includes `?sslmode=require` for Neon
- System continues with JSON storage — not critical

### Docker build fails on ARM (Apple Silicon Mac)

Add platform to docker-compose.yml:
```yaml
services:
  trader:
    platform: linux/amd64
    build: .
```

---

## Cost Estimate

| Component | Cost |
|-----------|------|
| EC2 t3.small (on-demand) | ~$15/month |
| EC2 t3.small (reserved 1yr) | ~$6/month |
| EBS storage (20GB) | ~$2/month |
| Neon Postgres (free tier) | $0 |
| Data transfer | ~$1/month |
| **Total** | **$8-18/month** |
