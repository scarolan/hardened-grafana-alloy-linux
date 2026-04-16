# Path 1 — Direct Deployment (Linux)

Deploy the hardened `config.alloy` directly to each Linux host using your existing tooling (Ansible, Chef, Puppet, Salt, cloud-init, manual copy, etc.). The config file lives on the host; there is no remote configuration service.

> Looking for centrally-managed config pushes via Grafana Cloud? See **[Path 2 — Fleet Management](fleet-management.md)**.

## What You Need

### Create an Access Policy and Token

1. Visit `https://grafana.com/orgs/<your-org-slug>/access-policies` — replace `<your-org-slug>` with the slug from your Grafana Cloud org URL (the part after `/orgs/`)
2. Click **Create access policy**, give it a name (e.g. "Hardened Alloy"), and select your stack(s) under **Realms**
3. **Ignore the individual scope checkboxes.** Instead, use the **Add scope** dropdown at the bottom and pick `set:alloy-data-write` — this bundles the metrics, logs, traces, and profiles write scopes in one step
4. Click **Create** to save the policy
5. On the new policy, click **Add token**, give it a name, and pick an expiration (90 days is typical for a pilot)
6. **Copy the token value immediately** — it's shown exactly once. This is your `GCLOUD_RW_API_KEY`.

### Gather Your Endpoints

From grafana.com > My Account > your stack:

| Value | Example | Where to Find |
|-------|---------|---------------|
| Metrics URL | `https://prometheus-prod-13-prod-us-east-0.grafana.net/api/prom/push` | Prometheus > Details |
| Metrics Username | `000000` | Prometheus > Details |
| Logs URL | `https://logs-prod-006.grafana.net/loki/api/v1/push` | Loki > Details |
| Logs Username | `000000` | Loki > Details |

## Step 1: Install Alloy

**Debian / Ubuntu:**

```bash
apt-get install -y gpg wget
wget -qO- https://apt.grafana.com/gpg.key | gpg --dearmor -o /etc/apt/keyrings/grafana.gpg
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" \
  > /etc/apt/sources.list.d/grafana.list
apt-get update && apt-get install -y alloy
```

**RHEL / Rocky / CentOS:**

```bash
cat > /etc/yum.repos.d/grafana.repo <<'EOF'
[grafana]
name=grafana
baseurl=https://rpm.grafana.com
repo_gpgcheck=1
enabled=1
gpgcheck=1
gpgkey=https://rpm.grafana.com/gpg.key
sslverify=1
sslcacert=/etc/pki/tls/certs/ca-bundle.crt
EOF
dnf install -y alloy
```

## Step 2: Deploy the Config File

Grab the hardened config from this repo and drop it at `/etc/alloy/config.alloy`. Most users do this without cloning — pull the raw file, or copy-paste from the browser:

```bash
# Download directly from the repo
curl -fsSL https://raw.githubusercontent.com/scarolan/hardened-grafana-alloy-linux/main/config.alloy \
  -o /etc/alloy/config.alloy
```

Or open the [raw file on GitHub](https://raw.githubusercontent.com/scarolan/hardened-grafana-alloy-linux/main/config.alloy), copy the contents, and paste into `/etc/alloy/config.alloy` on the host.

For scale-out, stage the file on a repo/share/artifact store and distribute via your usual tooling:

| Tool | Method |
|------|--------|
| **Ansible** | `copy` or `template` module to `/etc/alloy/config.alloy` |
| **Chef / Puppet / Salt** | Standard file resource pointing to the hardened config |
| **cloud-init** | `write_files` entry in user-data |
| **Manual / small fleet** | `scp` from a jump host, or `rsync` from a central repo |

## Step 3: Set Environment Variables

Put credentials in the Alloy env file. The path depends on distro:

- **Debian / Ubuntu:** `/etc/default/alloy`
- **RHEL / Rocky / CentOS / SUSE:** `/etc/sysconfig/alloy`

```bash
sudo tee -a /etc/default/alloy >/dev/null <<'EOF'
GCLOUD_RW_API_KEY=glc_xxxxxxxxxxxxx
GRAFANA_METRICS_URL=https://prometheus-prod-13-prod-us-east-0.grafana.net/api/prom/push
GRAFANA_METRICS_USERNAME=000000
GRAFANA_LOGS_URL=https://logs-prod-006.grafana.net/loki/api/v1/push
GRAFANA_LOGS_USERNAME=000000
EOF
sudo chmod 600 /etc/default/alloy
```

For scale-out: Ansible `lineinfile`/`template`, Chef `file` resource, etc. Full reference including a portable `systemctl edit` approach and verification commands: see [env-vars.md](env-vars.md).

## Step 4: Start the Service

```bash
systemctl enable --now alloy
systemctl status alloy
```

## Step 5: Verify and Import the Dashboard

### Quick PromQL smoke test

Confirm data is flowing *before* importing the dashboard. Go to **Explore → Prometheus** in Grafana and run:

```promql
# 1. Is this host's Alloy alive and scraping?
up{instance="<your-hostname>"}
# Expected: 1

# 2. How many distinct series is this host shipping?
count(count by (__name__) ({instance="<your-hostname>"}))
# Expected: ~400-600 for a typical cloud VM on the hardened config

# 3. Any metrics missing required labels? (should be empty in production)
count({quality_warning="missing_required_labels", instance="<your-hostname>"})
```

If query 1 is `0` or empty, the host isn't pushing. Check `systemctl status alloy` and `journalctl -u alloy -n 50`.

### Import the dashboard

Once the smoke tests pass, import the [Node Exporter Full](https://grafana.com/grafana/dashboards/1860-node-exporter-full/) dashboard (ID 1860). All panels should populate.

### Troubleshooting from the host

```bash
systemctl status alloy
journalctl -u alloy -n 100 --no-pager
# Check what env vars the running process has (see docs/env-vars.md for details)
sudo tr '\0' '\n' < /proc/$(systemctl show -p MainPID --value alloy)/environ | grep -E '^(GCLOUD_|GRAFANA_)'
```

## Summary

| Step | What | How (at scale) |
|------|------|----------------|
| 1 | Install Alloy | Ansible / Chef / Puppet / cloud-init |
| 2 | Deploy config.alloy | File resource to `/etc/alloy/config.alloy` |
| 3 | Set env vars | Append to `/etc/default/alloy` or `/etc/sysconfig/alloy` |
| 4 | Enable & start service | `systemctl enable --now alloy` |
| 5 | Import dashboard | One-time, in Grafana Cloud UI |

All five steps use your existing Linux admin tooling. When a config change is needed, you redeploy the file — there is no centralized config push.
