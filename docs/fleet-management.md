# Path 2 — Grafana Fleet Management (Linux)

Each Linux host runs a minimal bootstrap config (`fleet-config.alloy`) that connects to Grafana Cloud Fleet Management and polls for pipeline updates. You build and push the actual collection pipelines from the Fleet Management UI, so config changes don't require touching hosts.

> Prefer having the full config on each host? See **[Path 1 — Direct Deployment](direct-deployment.md)**.

## What You Need

### Create an Access Policy and Token

1. Visit `https://grafana.com/orgs/YOURORG/access-policies`
2. Click **Create access policy**, give it a name, select your stack(s) under Realms
3. Use **Add scope** and pick **set:alloy-data-write**
4. Click **Create**, then **Add token** on the new policy, name it, set an expiration
5. Copy the token immediately — this is your `GCLOUD_RW_API_KEY`

### Gather Your Endpoints

From grafana.com > My Account > your stack:

| Value | Example | Where to Find |
|-------|---------|---------------|
| Metrics URL | `https://prometheus-prod-13-prod-us-east-0.grafana.net/api/prom/push` | Prometheus > Details |
| Metrics Username | `000000` | Prometheus > Details |
| Logs URL | `https://logs-prod-006.grafana.net/loki/api/v1/push` | Loki > Details |
| Logs Username | `000000` | Loki > Details |
| Fleet Management URL | `https://fleet-management-prod-008.grafana.net` | Fleet Management > Collector configuration |
| Fleet Management Username | `654321` | Fleet Management > Collector configuration |

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

## Step 2: Deploy `fleet-config.alloy`

Edit the Fleet Management URL and username in `fleet-config.alloy` to match your stack, then deploy to `/etc/alloy/config.alloy`:

```bash
cp fleet-config.alloy /etc/alloy/config.alloy
```

This config is deliberately tiny — it only connects to Fleet Management. The real pipelines come down over the wire.

## Step 3: Set Environment Variables

```bash
cat >> /etc/default/alloy <<'EOF'
GCLOUD_RW_API_KEY=glc_xxxxxxxxxxxxx
GRAFANA_METRICS_URL=https://prometheus-prod-13-prod-us-east-0.grafana.net/api/prom/push
GRAFANA_METRICS_USERNAME=000000
GRAFANA_LOGS_URL=https://logs-prod-006.grafana.net/loki/api/v1/push
GRAFANA_LOGS_USERNAME=000000
EOF
chmod 600 /etc/default/alloy
```

Path differs by distro (`/etc/default/alloy` on Debian/Ubuntu, `/etc/sysconfig/alloy` on RHEL family).

**Why all five, not just the API key?** See [Why env vars instead of hardcoding values into pipelines?](#why-env-vars-instead-of-hardcoding-values-into-pipelines) below.

## Step 4: Start the Service

```bash
systemctl enable --now alloy
systemctl status alloy
```

Check that Alloy connected to Fleet Management — in the FM UI the collector should appear under Collectors within 60 seconds.

## Step 5: Build Your First Pipeline

In Grafana Cloud > Fleet Management > Pipelines:

1. Click **Add pipeline**
2. Give it a name and set matchers (e.g. `env=prod`) so it targets this collector
3. Paste your pipeline config — **must include its own `prometheus.remote_write` and/or `loki.write` block**. See [`examples/blackbox.alloy`](../examples/blackbox.alloy) for a complete self-contained pattern. Copy the hardened `config.alloy` from this repo as a starting point for Linux host monitoring.
4. Save and apply

Within ~60 seconds, Alloy on the host polls Fleet Management, pulls the new pipeline, and starts collecting.

> **⚠️ Critical gotcha: remote_write endpoints are not shared**
>
> The `prometheus.remote_write` and `loki.write` blocks in `fleet-config.alloy` are **not reachable** from pipelines you push via Fleet Management. Each FM pipeline is wrapped in a sealed `declare` module — components inside can't reference components in the parent scope.
>
> **Every FM pipeline that ships metrics or logs must include its own `prometheus.remote_write` and/or `loki.write` block.** Use `sys.env()` for credentials so you don't duplicate secrets across pipelines.

## Step 6: Verify and Import the Dashboard

After the pipeline is applied, import the [Node Exporter Full](https://grafana.com/grafana/dashboards/1860-node-exporter-full/) dashboard (ID 1860). All panels should populate.

Check for data-quality issues:

```promql
{quality_warning=~".+"}
```

Troubleshooting from the host:

```bash
systemctl status alloy
journalctl -u alloy -n 50
```

## Why env vars instead of hardcoding values into pipelines?

Two reasons, neither adds meaningful operational burden:

1. **Secrets don't belong in the Fleet Management UI.** Pipelines pushed via FM are stored in Grafana Cloud's config store and visible to anyone with FM access. Hardcoding the API key there means it lives in every pipeline export, backup, and screenshot. Keeping it in `sys.env()` means the secret lives on the host — rotated through your existing secret management, never echoed back in the UI.

2. **You already have to set `GCLOUD_RW_API_KEY` on the host.** Alloy can't connect to Fleet Management without it. Since you're already setting one env var, adding four more (URLs + usernames) is seconds of extra work via the same systemd unit override or `/etc/default/alloy` file. It's not "yet another file to manage" — it's four more lines in the mechanism you already use.

URLs and usernames aren't secret, but keeping them next to the password means rotations and stack migrations are atomic: change host env, restart Alloy, done. No re-editing N pipelines in the FM UI.

## Summary

| Step | What | How (at scale) |
|------|------|----------------|
| 1 | Install Alloy | Ansible / Chef / Puppet / cloud-init |
| 2 | Deploy fleet-config.alloy | File resource to `/etc/alloy/config.alloy` |
| 3 | Set env vars (all 5) | Append to `/etc/default/alloy` or `/etc/sysconfig/alloy` |
| 4 | Enable & start service | `systemctl enable --now alloy` |
| 5 | Build pipelines | One-time, in Fleet Management UI |
| 6 | Import dashboard | One-time, in Grafana Cloud UI |

Config changes after Step 5 happen entirely in the FM UI — no touching hosts.
