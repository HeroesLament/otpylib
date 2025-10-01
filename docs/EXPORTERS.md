# Telemetry Exporters

## Overview

Telemetry exporters are GenServer processes that subscribe to telemetry events and export them to external observability systems. This document describes the patterns for building configurable, runtime-reconfigurable exporters that integrate with otpylib-config.

## Exporter Architecture

### Core Pattern

All exporters follow the same architectural pattern:

1. **Initialize with configuration** from multiple sources
2. **Subscribe to telemetry events** using pattern matching
3. **Handle configuration changes** at runtime via message passing
4. **Export metrics/traces** to external systems

```python
# Basic exporter structure
from otpylib import gen_server
from otpylib_telemetry import attach_many
from otpylib_config import Config
import types

exporter_callbacks = types.SimpleNamespace()

async def init(initial_config):
    """Initialize exporter with configuration."""
    # Load configuration from multiple sources
    config = await _load_configuration(initial_config)
    
    # Set up external system client
    client = await _setup_client(config)
    
    # Subscribe to telemetry events
    await attach_many("exporter_id", config["event_patterns"], _handle_telemetry_event)
    
    # Subscribe to configuration changes
    await Config.subscribe("telemetry.exporter.*", _handle_config_change)
    
    return {
        "config": config,
        "client": client,
        "stats": {"events_processed": 0, "events_failed": 0}
    }
```

## Configuration Integration

### Multi-Source Configuration Loading

Exporters should read configuration from multiple sources with proper precedence:

```python
async def _load_configuration(initial_config=None):
    """Load configuration from multiple sources with precedence."""
    from otpylib_config import Config
    import os
    
    # Base configuration with defaults
    config = {
        "enabled": True,
        "event_patterns": ["*"],
        "batch_size": 100,
        "flush_interval": 5.0,
        "retry_attempts": 3
    }
    
    # Environment variables (low precedence)
    env_config = {
        "enabled": os.getenv("TELEMETRY_ENABLED", "true").lower() == "true",
        "endpoint": os.getenv("TELEMETRY_ENDPOINT"),
        "api_key": os.getenv("TELEMETRY_API_KEY"),
        "batch_size": int(os.getenv("TELEMETRY_BATCH_SIZE", "100"))
    }
    config.update({k: v for k, v in env_config.items() if v is not None})
    
    # otpylib-config (medium precedence)
    config_file_settings = await Config.get("telemetry.otel", default={})
    config.update(config_file_settings)
    
    # Explicit initialization config (highest precedence)
    if initial_config:
        config.update(initial_config)
    
    return config
```

### Configuration Change Handling

The key pattern is using a **callback function** that sends messages to the exporter's own mailbox:

```python
async def _handle_config_change(path, old_value, new_value):
    """Handle configuration changes by messaging the exporter."""
    # This callback runs in the config manager's context
    # Send a message to our own GenServer to handle the change
    await gen_server.cast("otel_exporter", ("config_changed", path, old_value, new_value))

async def handle_cast(message, state):
    """Handle messages including configuration changes."""
    match message:
        case ("telemetry", event_name, measurements, metadata):
            # Handle telemetry events
            await _process_telemetry_event(state, event_name, measurements, metadata)
            state["stats"]["events_processed"] += 1
            
        case ("config_changed", path, old_value, new_value):
            # Handle configuration changes
            await _apply_config_change(state, path, old_value, new_value)
            
        case ("flush_batch",):
            # Handle periodic batch flushing
            await _flush_pending_events(state)
    
    return (gen_server.NoReply(), state)

async def _apply_config_change(state, path, old_value, new_value):
    """Apply a configuration change to the running exporter."""
    if path == "telemetry.otel.endpoint":
        # Recreate client with new endpoint
        await _teardown_client(state["client"])
        state["config"]["endpoint"] = new_value
        state["client"] = await _setup_client(state["config"])
        print(f"Updated OTEL endpoint: {old_value} -> {new_value}")
        
    elif path == "telemetry.otel.batch_size":
        state["config"]["batch_size"] = new_value
        print(f"Updated batch size: {old_value} -> {new_value}")
        
    elif path == "telemetry.otel.enabled":
        state["config"]["enabled"] = new_value
        if new_value:
            print("Telemetry export enabled")
        else:
            print("Telemetry export disabled")
```

## Concrete Exporter Examples

### OpenTelemetry Exporter

```python
# otpylib_telemetry_otel/exporter.py
from otpylib import gen_server
from otpylib_telemetry import attach_many
from otpylib_config import Config
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
import types

otel_callbacks = types.SimpleNamespace()

async def _handle_config_change(path, old_value, new_value):
    """Configuration change callback - sends message to self."""
    await gen_server.cast("otel_exporter", ("config_changed", path, old_value, new_value))

async def _handle_telemetry_event(event_name, measurements, metadata):
    """Telemetry event callback - sends message to self."""
    await gen_server.cast("otel_exporter", ("telemetry", event_name, measurements, metadata))

async def init(initial_config=None):
    """Initialize OpenTelemetry exporter."""
    config = await _load_otel_configuration(initial_config)
    
    if not config["enabled"]:
        return {"config": config, "tracer": None, "active_spans": {}}
    
    # Set up OpenTelemetry tracer
    tracer_provider = TracerProvider()
    
    if config.get("endpoint"):
        exporter = OTLPSpanExporter(endpoint=config["endpoint"])
        span_processor = BatchSpanProcessor(exporter)
        tracer_provider.add_span_processor(span_processor)
    
    tracer = tracer_provider.get_tracer(config["service_name"])
    
    # Subscribe to events
    await attach_many("otel_exporter", config["event_patterns"], _handle_telemetry_event)
    
    # Subscribe to config changes
    await Config.subscribe("telemetry.otel.*", _handle_config_change)
    
    return {
        "config": config,
        "tracer": tracer,
        "tracer_provider": tracer_provider,
        "active_spans": {},
        "stats": {"spans_created": 0, "spans_exported": 0}
    }

async def handle_cast(message, state):
    """Handle telemetry events and configuration changes."""
    match message:
        case ("telemetry", event_name, measurements, metadata):
            if state["config"]["enabled"] and state["tracer"]:
                await _create_span(state, event_name, measurements, metadata)
        
        case ("config_changed", path, old_value, new_value):
            await _handle_otel_config_change(state, path, old_value, new_value)
    
    return (gen_server.NoReply(), state)

async def _handle_otel_config_change(state, path, old_value, new_value):
    """Apply OpenTelemetry configuration changes."""
    if path == "telemetry.otel.enabled":
        if new_value and not state["config"]["enabled"]:
            # Re-enable: recreate tracer
            state["config"]["enabled"] = True
            # Reinitialize tracer components...
        elif not new_value and state["config"]["enabled"]:
            # Disable: clean shutdown
            state["config"]["enabled"] = False
            if state["tracer_provider"]:
                state["tracer_provider"].shutdown()
    
    elif path == "telemetry.otel.endpoint":
        # Recreate exporter with new endpoint
        state["config"]["endpoint"] = new_value
        # Reinitialize with new endpoint...

async def _create_span(state, event_name, measurements, metadata):
    """Create OpenTelemetry span from telemetry event."""
    if event_name.endswith(".start"):
        span_name = event_name.replace(".start", "")
        span = state["tracer"].start_span(span_name)
        
        # Store span for later completion
        correlation_id = metadata.get("correlation_id") or metadata.get("request_id")
        if correlation_id:
            state["active_spans"][correlation_id] = span
        
        state["stats"]["spans_created"] += 1
    
    elif event_name.endswith(".success") or event_name.endswith(".error"):
        correlation_id = metadata.get("correlation_id") or metadata.get("request_id") 
        if correlation_id in state["active_spans"]:
            span = state["active_spans"].pop(correlation_id)
            
            if event_name.endswith(".error"):
                span.set_status(trace.Status(trace.StatusCode.ERROR))
            
            if "duration_ms" in measurements:
                span.set_attribute("duration_ms", measurements["duration_ms"])
            
            span.end()
            state["stats"]["spans_exported"] += 1

otel_callbacks.init = init
otel_callbacks.handle_cast = handle_cast
```

### Prometheus Exporter

```python
# otpylib_telemetry_prometheus/exporter.py
from otpylib import gen_server
from otpylib_telemetry import attach_many
from otpylib_config import Config
from prometheus_client import Counter, Histogram, Gauge, start_http_server
import types

prometheus_callbacks = types.SimpleNamespace()

async def _handle_config_change(path, old_value, new_value):
    """Configuration change callback."""
    await gen_server.cast("prometheus_exporter", ("config_changed", path, old_value, new_value))

async def _handle_telemetry_event(event_name, measurements, metadata):
    """Telemetry event callback."""
    await gen_server.cast("prometheus_exporter", ("telemetry", event_name, measurements, metadata))

async def init(initial_config=None):
    """Initialize Prometheus exporter."""
    config = await _load_prometheus_configuration(initial_config)
    
    metrics = {}
    http_server = None
    
    if config["enabled"]:
        # Create Prometheus metrics
        metrics = {
            "counters": {},
            "histograms": {},
            "gauges": {}
        }
        
        # Start HTTP server for metrics endpoint
        if config.get("port"):
            http_server = start_http_server(config["port"])
    
    # Subscribe to events and config changes
    await attach_many("prometheus_exporter", config["event_patterns"], _handle_telemetry_event)
    await Config.subscribe("telemetry.prometheus.*", _handle_config_change)
    
    return {
        "config": config,
        "metrics": metrics,
        "http_server": http_server,
        "stats": {"metrics_updated": 0}
    }

async def handle_cast(message, state):
    """Handle telemetry events and configuration changes."""
    match message:
        case ("telemetry", event_name, measurements, metadata):
            if state["config"]["enabled"]:
                await _update_prometheus_metrics(state, event_name, measurements, metadata)
        
        case ("config_changed", path, old_value, new_value):
            await _handle_prometheus_config_change(state, path, old_value, new_value)
    
    return (gen_server.NoReply(), state)

async def _update_prometheus_metrics(state, event_name, measurements, metadata):
    """Update Prometheus metrics from telemetry event."""
    # Create metric labels from metadata
    labels = {k: str(v) for k, v in metadata.items() if isinstance(v, (str, int, float))}
    
    if "count" in measurements:
        # Counter metric
        metric_name = f"{event_name}_total".replace(".", "_")
        if metric_name not in state["metrics"]["counters"]:
            state["metrics"]["counters"][metric_name] = Counter(
                metric_name, f"Total {event_name} events", list(labels.keys())
            )
        
        counter = state["metrics"]["counters"][metric_name]
        counter.labels(**labels).inc(measurements["count"])
        state["stats"]["metrics_updated"] += 1
    
    if "duration_ms" in measurements:
        # Histogram metric
        metric_name = f"{event_name}_duration_seconds".replace(".", "_")
        if metric_name not in state["metrics"]["histograms"]:
            state["metrics"]["histograms"][metric_name] = Histogram(
                metric_name, f"Duration of {event_name} in seconds"
            )
        
        histogram = state["metrics"]["histograms"][metric_name]
        histogram.observe(measurements["duration_ms"] / 1000)
        state["stats"]["metrics_updated"] += 1

async def _handle_prometheus_config_change(state, path, old_value, new_value):
    """Handle Prometheus configuration changes."""
    if path == "telemetry.prometheus.enabled":
        state["config"]["enabled"] = new_value
        if new_value:
            print("Prometheus export enabled")
        else:
            print("Prometheus export disabled")
    
    elif path == "telemetry.prometheus.port":
        # Restart HTTP server on new port
        if state["http_server"]:
            state["http_server"].shutdown()
        
        if new_value and state["config"]["enabled"]:
            state["http_server"] = start_http_server(new_value)
            state["config"]["port"] = new_value

prometheus_callbacks.init = init
prometheus_callbacks.handle_cast = handle_cast
```

## Configuration Schema

### Standardized Configuration Structure

All exporters should follow a consistent configuration schema:

```toml
# config.toml
[telemetry.otel]
enabled = true
service_name = "queuemizer"
endpoint = "http://jaeger:14268/api/traces"
event_patterns = ["queuemizer.*", "*.error"]
batch_size = 100
sampling_rate = 0.1

[telemetry.prometheus]
enabled = true
port = 9090
path = "/metrics"
event_patterns = ["*"]

[telemetry.datadog]
enabled = false
api_key = "${DATADOG_API_KEY}"
site = "datadoghq.com"
```

### Runtime Configuration API

Exporters can expose configuration management endpoints:

```python
# In your HTTP API
async def update_telemetry_config(request):
    """Update telemetry configuration via HTTP API."""
    from otpylib_config import Config
    
    config_updates = await request.json()
    
    for path, value in config_updates.items():
        await Config.put(f"telemetry.{path}", value)
    
    return {"status": "updated", "changes": config_updates}

async def get_telemetry_status(request):
    """Get current telemetry exporter status."""
    otel_stats = await gen_server.call("otel_exporter", ("get_stats",))
    prometheus_stats = await gen_server.call("prometheus_exporter", ("get_stats",))
    
    return {
        "otel": otel_stats,
        "prometheus": prometheus_stats
    }
```

## Error Handling and Resilience

### Graceful Degradation

Exporters should handle failures gracefully without affecting the application:

```python
async def _process_telemetry_event(state, event_name, measurements, metadata):
    """Process telemetry event with error handling."""
    try:
        await _export_to_backend(state, event_name, measurements, metadata)
        state["stats"]["events_exported"] += 1
    except Exception as e:
        state["stats"]["events_failed"] += 1
        
        # Log error but don't crash
        print(f"Telemetry export failed: {e}")
        
        # Optionally emit internal telemetry about failures
        await gen_server.cast("telemetry_manager", (
            "emit", "telemetry.export.failed", 
            {"count": 1}, 
            {"exporter": "otel", "error": str(e)}
        ))
```

### Circuit Breaker Pattern

```python
class ExporterCircuitBreaker:
    def __init__(self, failure_threshold=5, reset_timeout=60):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "closed"  # closed, open, half_open
    
    async def call(self, func, *args, **kwargs):
        if self.state == "open":
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.state = "half_open"
            else:
                return None  # Skip export
        
        try:
            result = await func(*args, **kwargs)
            if self.state == "half_open":
                self.state = "closed"
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = "open"
            
            raise
```

## Testing Exporters

### Mock Exporter for Testing

```python
# otpylib_telemetry_mock/exporter.py
class MockExporter:
    """Test exporter that captures events for verification."""
    
    def __init__(self):
        self.events = []
        self.config_changes = []
    
    async def handle_telemetry_event(self, event_name, measurements, metadata):
        self.events.append({
            "event_name": event_name,
            "measurements": measurements,
            "metadata": metadata,
            "timestamp": time.time()
        })
    
    async def handle_config_change(self, path, old_value, new_value):
        self.config_changes.append({
            "path": path,
            "old_value": old_value,
            "new_value": new_value,
            "timestamp": time.time()
        })
    
    def get_events_matching(self, pattern):
        import fnmatch
        return [e for e in self.events if fnmatch.fnmatch(e["event_name"], pattern)]
```

This pattern enables building robust, configurable telemetry exporters that integrate seamlessly with otpylib applications while maintaining the ability to reconfigure at runtime without restarts.
