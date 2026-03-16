# Grafana Alloy vs Vanilla OpenTelemetry Collector

This repo ships two hardened configs for Linux host monitoring. Both follow the same cardinality protection philosophy. This doc explains when to use which.

## The two configs

| | `config.alloy` (Alloy) | `config-otel.yaml` (OTEL Collector) |
|---|---|---|
| **Binary** | `grafana/alloy` | `otel/opentelemetry-collector-contrib` |
| **Config language** | River (Alloy-native) | YAML (standard OTEL) |
| **Host metrics** | `prometheus.exporter.unix` (node_exporter built-in) | `hostmetrics` receiver |
| **Metric names** | `node_*` (Prometheus/node_exporter conventions) | `system.*` (OTel semantic conventions) |
| **Dashboard** | Node Exporter Full (ID 1860) — works out of the box | Needs an OTel-native dashboard (e.g., ID 15983) |
| **Systemd monitoring** | Yes — filtered to ~15 essential services | No — no systemd scraper exists in OTel |
| **Journal logs** | Yes — native `loki.source.journal` | No — use `filelog` on /var/log/syslog as substitute |
| **Series budget** | 400-600 per VM | 100-300 per VM |
| **Test results** | 33 Docker + 55 VM tests passing | 12 Docker + 55 VM tests passing |

## When to use Alloy (`config.alloy`)

- You need **Dashboard 1860** (Node Exporter Full) compatibility
- You need **systemd unit state** monitoring (which services are running/failed)
- You need **journal log** collection (not just syslog files)
- You need metrics that only node_exporter provides: conntrack, entropy, ARP, PSI, schedstat, softnet, hwmon, timex, TCP connection states
- You want the **Alloy UI** (port 12345) for debugging pipelines
- You plan to use **Grafana Fleet Management** (remotecfg) for centralized config
- Your team already knows the **River config language**

## When to use vanilla OTEL Collector (`config-otel.yaml`)

- You want **zero vendor lock-in** — this config runs on any otelcol-contrib distribution
- You're already standardized on **OpenTelemetry** and want YAML configs
- You want the **smallest possible binary** and footprint
- You don't need systemd, journal, conntrack, PSI, or the other Linux-specific collectors
- You're building toward an **OTLP-native pipeline** (traces + metrics + logs all in one collector)
- You want to use OTel-native features like the **memory_limiter** processor for back-pressure
- Your dashboards already use **OTel semantic conventions** (`system.cpu.time` instead of `node_cpu_seconds_total`)

## What Alloy adds over vanilla OTEL Collector

Alloy is a superset of otelcol-contrib. Everything in `config-otel.yaml` works in both. But Alloy adds:

| Feature | Available in Alloy | Available in otelcol-contrib |
|---|---|---|
| `prometheus.exporter.unix` (node_exporter) | Yes | No |
| Systemd unit/socket metrics | Yes | No |
| Journal log reader | Yes | No |
| Conntrack, entropy, ARP, PSI, schedstat, softnet, hwmon, timex | Yes | No |
| TCP connection state metrics | Yes | No |
| River config language | Yes | No |
| Web UI (pipeline visualization) | Yes | No |
| Fleet management (remotecfg) | Yes | No |
| systemd service installer | Yes | No (manual unit file) |

## What vanilla OTEL Collector does better

| Feature | otelcol-contrib | Alloy |
|---|---|---|
| No vendor dependency | Yes — pure upstream OSS | Grafana-maintained fork |
| YAML config | Native | Experimental (OTEL engine) |
| Memory limiter processor | Yes — proper back-pressure | Not available in River mode |
| Resource detection | Auto-tags host.name, os.type, cloud.* | Manual via constants.hostname |
| Config providers (env, http, file) | Built-in | env only via sys.env() |
| Connector components (spanmetrics, servicegraph) | Yes | Yes (wrapped) |

## The honest take

If you need comprehensive Linux monitoring and Dashboard 1860, use Alloy. The node_exporter integration, systemd scraper, and journal reader are genuinely useful and have no OTEL equivalent.

If you're building an OTLP pipeline and just need basic host metrics alongside your app telemetry, use the vanilla OTEL collector. You get fewer metrics, but you get zero vendor dependency and a config that runs anywhere.

The cardinality protection patterns (allow-list, pattern blocking, label tagging, value truncation) work identically in both. That's the part that matters most for cost control.

## Test matrix

Both configs are tested across the same 5 Linux distributions:

| Distro | Alloy (config.alloy) | OTEL (config-otel.yaml) |
|---|---|---|
| Ubuntu 22.04 | 55 passed | 55 passed |
| Debian 12 | 55 passed | 55 passed |
| Rocky 9 | 55 passed | 55 passed |
| CentOS Stream 9 | 55 passed | 55 passed |
| SUSE 15 | 55 passed | 55 passed |

Alloy additionally has 8 expected failures (xfail) for PSI on Rocky/CentOS/SUSE and hwmon on all cloud VMs — these are hardware-dependent metrics that the OTEL config doesn't test because the hostmetrics receiver doesn't collect them.
