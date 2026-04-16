# Environment Variables Reference

Single canonical reference for every environment variable either `config.alloy` or `fleet-config.alloy` reads. Both deployment paths point here.

## The Five Required Variables

| Variable | What it is | Where to find the value | Required by |
|----------|------------|-------------------------|-------------|
| `GCLOUD_RW_API_KEY` | Access policy token with `set:alloy-data-write` scope. Shared password for Prometheus, Loki, and Fleet Management. | Access Policies → your policy → Add token. Copy immediately — shown once. | Path 1, Path 2 |
| `GRAFANA_METRICS_URL` | Prometheus remote_write URL | My Account → stack → Prometheus → Details | Path 1, Path 2 |
| `GRAFANA_METRICS_USERNAME` | Prometheus stack ID (6-digit number) | My Account → stack → Prometheus → Details | Path 1, Path 2 |
| `GRAFANA_LOGS_URL` | Loki push URL | My Account → stack → Loki → Details | Path 1, Path 2 |
| `GRAFANA_LOGS_USERNAME` | Loki stack ID (6-digit number) | My Account → stack → Loki → Details | Path 1, Path 2 |

**Path 2 users:** you still need all five. The bootstrap `fleet-config.alloy` uses `GCLOUD_RW_API_KEY` directly, and every Fleet Management pipeline you push needs the other four (because FM pipelines live in sealed modules that can't share the bootstrap's endpoints). See [fleet-management.md](fleet-management.md) for the rationale.

## How to Set Them

### Debian / Ubuntu

Alloy's systemd unit sources `/etc/default/alloy`. Append your values:

```bash
sudo tee -a /etc/default/alloy >/dev/null <<'EOF'
GCLOUD_RW_API_KEY=glc_xxxxxxxxxxxxx
GRAFANA_METRICS_URL=https://prometheus-prod-13-prod-us-east-0.grafana.net/api/prom/push
GRAFANA_METRICS_USERNAME=000000
GRAFANA_LOGS_URL=https://logs-prod-006.grafana.net/loki/api/v1/push
GRAFANA_LOGS_USERNAME=000000
EOF
sudo chmod 600 /etc/default/alloy
sudo systemctl restart alloy
```

### RHEL / Rocky / CentOS / SUSE

Same idea, different path:

```bash
sudo tee -a /etc/sysconfig/alloy >/dev/null <<'EOF'
GCLOUD_RW_API_KEY=glc_xxxxxxxxxxxxx
GRAFANA_METRICS_URL=https://prometheus-prod-13-prod-us-east-0.grafana.net/api/prom/push
GRAFANA_METRICS_USERNAME=000000
GRAFANA_LOGS_URL=https://logs-prod-006.grafana.net/loki/api/v1/push
GRAFANA_LOGS_USERNAME=000000
EOF
sudo chmod 600 /etc/sysconfig/alloy
sudo systemctl restart alloy
```

### systemd drop-in (any distro, portable)

If you'd rather not touch distro-specific env files:

```bash
sudo systemctl edit alloy
```

Then in the editor that opens:

```ini
[Service]
Environment="GCLOUD_RW_API_KEY=glc_xxxxxxxxxxxxx"
Environment="GRAFANA_METRICS_URL=https://prometheus-prod-13-prod-us-east-0.grafana.net/api/prom/push"
Environment="GRAFANA_METRICS_USERNAME=000000"
Environment="GRAFANA_LOGS_URL=https://logs-prod-006.grafana.net/loki/api/v1/push"
Environment="GRAFANA_LOGS_USERNAME=000000"
```

Save, then `sudo systemctl restart alloy`.

## Verify the Service Sees Them

```bash
# Grab the Alloy PID
pid=$(systemctl show -p MainPID --value alloy)

# Read the env vars the process actually has (needs sudo; null-separated)
sudo tr '\0' '\n' < /proc/$pid/environ | grep -E '^(GCLOUD_|GRAFANA_)'
```

If your variables are missing, Alloy hasn't picked them up. Double-check the file, then `systemctl restart alloy`.

## Rotating Credentials

1. Create a new access policy token (don't delete the old one yet).
2. Update `GCLOUD_RW_API_KEY` in the env file on each host and restart Alloy.
3. Confirm data is still flowing (see the smoke tests in the deployment guides).
4. Delete the old token.

For URL / username changes (e.g. stack migration), update all four endpoint vars together and restart. Because the values live on the host, the change is atomic per host — no re-editing pipelines in the Fleet Management UI.

## Secret Hygiene

- The env file should be `chmod 600` and owned by root. The commands above do this.
- Don't commit `.env` (only `.env.example`). This repo's `.gitignore` already excludes it; confirm the same in any downstream fork.
- Don't paste the API key into Fleet Management pipeline YAML. Reference it via `sys.env("GCLOUD_RW_API_KEY")` so it stays on the host.
