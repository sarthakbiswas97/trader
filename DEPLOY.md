# Deployment Guide — AWS EC2

## Prerequisites

- AWS account with EC2 access
- Zerodha Kite Connect subscription
- GitHub repo pushed

## 1. Launch EC2 Instance

- **Instance type:** t3.small (2GB RAM)
- **AMI:** Ubuntu 24.04 LTS
- **Storage:** 20 GB
- **Security Group:** Open ports 3000, 8000, 22

```
Inbound Rules:
  SSH    (22)    → Your IP
  HTTP   (3000)  → 0.0.0.0/0  (frontend)
  Custom (8000)  → 0.0.0.0/0  (backend API)
```

## 2. Setup Server

SSH into instance:
```bash
ssh -i your-key.pem ubuntu@<EC2_PUBLIC_IP>
```

Install Docker:
```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker ubuntu
# Logout and login again for group change
exit
```

## 3. Clone and Configure

```bash
git clone https://github.com/sarthakbiswas97/trader.git
cd trader

# Create .env
cat > .env << EOF
KITE_API_KEY=your_api_key
KITE_API_SECRET=your_api_secret
EOF
```

## 4. Update Kite Redirect URL

In [Kite Developer Console](https://developers.kite.trade):

Change redirect URL from:
```
http://127.0.0.1:5000
```
To:
```
http://<EC2_PUBLIC_IP>:8000/api/v1/auth/callback
```

## 5. Build and Run

```bash
docker compose up -d --build
```

Wait 2-3 minutes for build. Check:
```bash
docker compose logs -f
```

## 6. Access

- **Frontend:** http://<EC2_PUBLIC_IP>:3000
- **Backend API:** http://<EC2_PUBLIC_IP>:8000
- **API Docs:** http://<EC2_PUBLIC_IP>:8000/docs
- **Research Page:** http://<EC2_PUBLIC_IP>:3000/research

## 7. Authenticate with Zerodha

1. Open http://<EC2_PUBLIC_IP>:3000/settings
2. Click "Login with Zerodha"
3. Login in browser → redirects to callback → token saved
4. Click "Connect" on dashboard

## 8. Daily Operations

The system runs inside Docker. To interact:

```bash
# Check status
docker compose exec trader python3 backend/scripts/run_reversal.py --status

# Run daily reversal
docker compose exec trader python3 backend/scripts/run_reversal.py

# View logs
docker compose logs -f --tail 50

# Restart
docker compose restart

# Stop
docker compose down
```

## 9. Monitoring

Health check endpoint:
```
http://<EC2_PUBLIC_IP>:8000/api/v1/health
```

## 10. Updates

```bash
cd trader
git pull
docker compose up -d --build
```

## Cost

- t3.small: ~$15/month (on-demand) or ~$6/month (reserved)
- EBS storage: ~$2/month
- Data transfer: minimal

**Total: ~$8-17/month**
