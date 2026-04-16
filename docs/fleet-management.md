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

Grab the bootstrap config from this repo and drop it at `/etc/alloy/config.alloy`. Most users do this without cloning — pull the raw file, or copy-paste from the browser:

```bash
# Download directly from the repo
curl -fsSL https://raw.githubusercontent.com/scarolan/hardened-grafana-alloy-linux/main/fleet-config.alloy \
  -o /etc/alloy/config.alloy

# Edit the remotecfg URL and username to match your stack
${EDITOR:-vi} /etc/alloy/config.alloy
```

Or open the [raw file on GitHub](https://raw.githubusercontent.com/scarolan/hardened-grafana-alloy-linux/main/fleet-config.alloy), copy the contents, and paste into `/etc/alloy/config.alloy` on the host.

This config is deliberately tiny — it only connects to Fleet Management. The real pipelines come down over the wire.

## Step 3: Set Environment Variables

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

Path differs by distro (`/etc/default/alloy` on Debian/Ubuntu, `/etc/sysconfig/alloy` on RHEL family). Full reference, including a distro-neutral `systemctl edit` approach and verification commands: see [env-vars.md](env-vars.md).

**Why all five, not just the API key?** See [Why env vars instead of hardcoding values into pipelines?](#why-env-vars-instead-of-hardcoding-values-into-pipelines) below.

## Step 4: Start the Service

```bash
systemctl enable --now alloy
systemctl status alloy
```

Check that Alloy connected to Fleet Management — in the FM UI the collector should appear under Collectors within 60 seconds.

## Step 5: Prove the Plumbing Works with a Minimal Pipeline

Before deploying the hardened config via FM, send a tiny test pipeline to confirm the whole loop works: **host → FM → pipeline pulled → data landing in your stack.**

In Grafana Cloud → Fleet Management → Pipelines:

1. Click **Add pipeline**
2. Name it something like `fm-smoke-test`
3. Under **Matchers**, target this collector. The safest match for a POV is the collector's own ID (`collector.ID == <hostname>`) — or a broader attribute like `env=pov` if you set one in `fleet-config.alloy`
4. Paste the pipeline below in the config editor
5. **Save** and **Apply**

```alloy
// Smoke-test pipeline — proves FM can push config to the host and that
// remote_write credentials work. Replace this with the hardened config
// after you confirm data arrives.

prometheus.remote_write "smoke_test" {
  endpoint {
    url = sys.env("GRAFANA_METRICS_URL")
    basic_auth {
      username = sys.env("GRAFANA_METRICS_USERNAME")
      password = sys.env("GCLOUD_RW_API_KEY")
    }
  }
}

prometheus.exporter.self "alloy_self" { }

discovery.relabel "alloy_self" {
  targets = prometheus.exporter.self.alloy_self.targets

  rule {
    target_label = "instance"
    replacement  = constants.hostname
  }

  rule {
    target_label = "job"
    replacement  = "fm_smoke_test"
  }
}

prometheus.scrape "alloy_self" {
  targets         = discovery.relabel.alloy_self.output
  forward_to      = [prometheus.remote_write.smoke_test.receiver]
  scrape_interval = "30s"
}
```

Within ~60 seconds Alloy polls FM, pulls this pipeline, and starts scraping its own internal metrics. Verify in **Explore → Prometheus**:

```promql
# Should return one series per collector running the smoke-test pipeline
alloy_build_info{job="fm_smoke_test"}
```

If that returns nothing after two minutes:

- Check the host: `journalctl -u alloy -n 50` — look for auth errors or parse errors
- In FM UI, open the collector and confirm the pipeline shows up as "Applied"
- Verify env vars are set: see [env-vars.md](env-vars.md) for the `/proc/<pid>/environ` trick

> **⚠️ Critical gotcha: remote_write endpoints are not shared**
>
> The `prometheus.remote_write` and `loki.write` blocks in `fleet-config.alloy` are **not reachable** from pipelines you push via Fleet Management. Each FM pipeline is wrapped in a sealed `declare` module — components inside can't reference components in the parent scope.
>
> **Every FM pipeline that ships metrics or logs must include its own `prometheus.remote_write` and/or `loki.write` block.** Use `sys.env()` for credentials so you don't duplicate secrets across pipelines.

## Step 6: Deploy the Hardened Pipeline

Once the smoke test works, edit the pipeline in FM and replace its contents with your real collection config. For Linux host monitoring, start from the hardened [`config.alloy`](https://raw.githubusercontent.com/scarolan/hardened-grafana-alloy-linux/main/config.alloy) in this repo. For custom collection (blackbox probes, app scrapes), see [`examples/blackbox.alloy`](../examples/blackbox.alloy) as a template.

Any pipeline you paste must include its own `prometheus.remote_write` / `loki.write` block (see the gotcha above).

Save and apply. Within ~60 seconds the host swaps the smoke-test pipeline for the real one.

## Step 7: Verify and Import the Dashboard

### Quick PromQL smoke test

Confirm data is flowing *before* importing the dashboard. Go to **Explore → Prometheus** and run:

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
# Check what env vars the running process has (see docs/env-vars.md for the full command)
sudo tr '\0' '\n' < /proc/$(systemctl show -p MainPID --value alloy)/environ | grep -E '^(GCLOUD_|GRAFANA_)'
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
| 5 | Smoke-test pipeline in FM | Validates host → FM → stack loop |
| 6 | Deploy hardened pipeline in FM | Replace smoke-test with real config |
| 7 | Verify + import dashboard | PromQL checks, then dashboard 1860 |

Config changes after Step 6 happen entirely in the FM UI — no touching hosts.
