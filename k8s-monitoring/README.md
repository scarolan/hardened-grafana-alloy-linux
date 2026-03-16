# Hardened Values for k8s-monitoring-helm

Defensive `values.yaml` for the [Grafana k8s-monitoring-helm](https://github.com/grafana/k8s-monitoring-helm) chart. Designed for cost-conscious teams who want full Kubernetes observability without surprise cardinality bills.

## The problem

The k8s-monitoring-helm chart has excellent built-in cardinality controls, but many of them are off by default or require you to know they exist. Meanwhile, any application pushing OTLP metrics to your cluster can send whatever it wants — unbounded metric names, high-cardinality labels, Go runtime noise. One misbehaving app can double your series count overnight.

This values file turns on every protection the chart offers and adds OTLP-specific filters on top.

## What it enables

| Feature | Collector | Status |
|---------|-----------|--------|
| Kubelet metrics | alloy-metrics | Allow-list ON (36 metrics) |
| cAdvisor metrics | alloy-metrics | Allow-list ON (19 metrics) |
| kube-state-metrics | alloy-metrics | Allow-list ON (~50 patterns) |
| Node exporter | alloy-metrics | Allow-list ON (10 patterns) |
| Cluster events | alloy-singleton | Enabled |
| Pod logs | alloy-logs | Enabled |
| OTLP gRPC (4317) | alloy-receiver | Enabled + filtered |
| OTLP HTTP (4318) | alloy-receiver | Enabled + filtered |
| Annotation autodiscovery | alloy-metrics | Enabled + filtered |
| Jaeger / Zipkin receivers | alloy-receiver | Disabled |
| Profiling | alloy-profiles | Disabled |

## Cardinality protection layers

### Layer 1: Prometheus allow-lists

Every Prometheus metric source uses `useDefaultAllowList: true`. Only the curated set of metrics needed for Kubernetes monitoring dashboards passes through. Everything else is dropped at scrape time.

### Layer 2: OTLP resource attribute stripping

High-churn resource attributes are removed before export:
- `process.pid`, `process.parent_pid`, `process.command_line`
- `host.ip`, `host.mac`
- `k8s.pod.uid`, `k8s.pod.start_time`
- `container.image.id`, `container.image.repo_digests`
- `os.description`, `os.build_id`
- Plus telemetry distro noise (`telemetry.distro.*`, `process.runtime.name`)

### Layer 3: OTLP metric name filtering

The filter processor drops entire metric families before they enter the pipeline:

```yaml
metrics:
  filters:
    metric:
      - 'IsMatch(metric.name, "^go_.*")'        # Go runtime metrics
      - 'IsMatch(metric.name, "^process\\..*")'  # Process metrics
      - 'IsMatch(metric.name, "^rpc\\..*")'      # gRPC internals
```

To add your own deny patterns:

```yaml
      - 'IsMatch(metric.name, "^my_noisy_library\\..*")'
```

### Layer 4: Annotation autodiscovery filtering

Pods scraped via `k8s.grafana.com/scrape: "true"` annotations also have Go/process metrics excluded:

```yaml
annotationAutodiscovery:
  metricsTuning:
    excludeMetrics:
      - go_gc_.*
      - go_memstats_.*
      - promhttp_.*
      - process_.*
```

### Layer 5: Trace filtering

Health check spans are dropped to reduce trace volume:

```yaml
traces:
  filters:
    span:
      - 'IsMatch(attributes["http.target"], "^/(healthz|readyz|livez|health|ready|ping)$")'
      - 'IsMatch(attributes["url.path"], "^/(healthz|readyz|livez|health|ready|ping)$")'
```

### Layer 6: Value truncation

Attribute values are truncated to prevent runaway label cardinality:
- Metric attributes: 200 characters
- Span attributes: 500 characters
- Log attributes: 500 characters

### Layer 7: Memory limiter

All collectors have memory limits to prevent OOM under load. The destination-level memory limiter provides back-pressure when the export queue fills up.

## Quick start

### 1. Install

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

helm install k8s-monitoring grafana/k8s-monitoring \
  -n monitoring --create-namespace \
  -f values-hardened.yaml \
  --set cluster.name="my-cluster" \
  --set "destinations[0].auth.username=YOUR_INSTANCE_ID" \
  --set "destinations[0].auth.password=YOUR_API_KEY"
```

### 2. Point your apps at the OTLP receivers

```
# gRPC
OTEL_EXPORTER_OTLP_ENDPOINT=http://k8s-monitoring-alloy-receiver.monitoring.svc:4317

# HTTP
OTEL_EXPORTER_OTLP_ENDPOINT=http://k8s-monitoring-alloy-receiver.monitoring.svc:4318
```

### 3. Verify

```bash
# Check all collectors are running
kubectl -n monitoring get pods

# Port-forward Alloy UI to inspect the pipeline
kubectl -n monitoring port-forward svc/k8s-monitoring-alloy-receiver 12345:12345
# Open http://localhost:12345
```

## Series budget

Tested on a 2-node k3d cluster with all features enabled:

| Component | Series | Metric names |
|-----------|--------|-------------|
| Total (infra only) | ~1,600 | ~175 |

For a production 10-node cluster, expect ~5,000-8,000 infra series. Application OTLP metrics add on top of that, controlled by your filter rules.

## Customizing

### Adding OTLP metric deny rules

Edit the `applicationObservability.metrics.filters.metric` list in `values-hardened.yaml`:

```yaml
- 'IsMatch(metric.name, "^my_noisy_prefix\\..*")'
```

### Allowing Go/process metrics for specific apps

If a specific app's Go metrics are useful, scrape them via annotation autodiscovery and add them to `includeMetrics`:

```yaml
annotationAutodiscovery:
  metricsTuning:
    includeMetrics:
      - go_goroutines   # just this one, not the whole go_* family
```

### Enabling traces and logs

The hardened values enable traces and logs by default. If using a Prometheus-only destination, set:

```yaml
applicationObservability:
  logs:
    enabled: false
  traces:
    enabled: false
```

### Enabling span metrics

To generate RED metrics (rate, errors, duration) from traces without separate app instrumentation:

```yaml
applicationObservability:
  connectors:
    spanMetrics:
      enabled: true
      aggregationCardinalityLimit: 1000  # cap unique dimension combos
```

## Testing locally

```bash
# Create a k3d cluster
k3d cluster create test --agents 1

# Deploy with test overrides (local Prometheus, no auth)
helm install k8s-monitoring grafana/k8s-monitoring \
  -n monitoring --create-namespace \
  -f values-hardened.yaml -f values-test.yaml

# Verify
kubectl -n monitoring get pods
kubectl -n monitoring port-forward svc/prometheus 9090:9090
# Query: count({__name__=~".+"})

# Clean up
k3d cluster delete test
```

## Files

| File | Purpose |
|------|---------|
| `values-hardened.yaml` | Production values — the main deliverable |
| `values-test.yaml` | Test overrides for local k3d validation (Prometheus-only destination, reduced resources) |
