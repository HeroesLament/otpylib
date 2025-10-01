# Configuration Client Usage

## Overview

The `Config` module provides the client API for interacting with the otpylib-config system. This document covers how applications use the configuration system for reading values, updating configuration, and responding to changes.

## Basic Operations

### Reading Configuration

```python
from otpylib_config import Config

# Get configuration values with optional defaults
database_url = await Config.get("database.url")
max_connections = await Config.get("database.max_connections", default=10)
debug_mode = await Config.get("app.debug", default=False)

# Nested configuration access
tc_rules = await Config.get("queuemizer.tc_rules.enp4s0")
rate_limits = await Config.get("queuemizer.rate_limits.api", default={"requests": 1000, "window": 60})
```

### Setting Configuration

```python
# Update individual values
await Config.put("feature_flags.new_ui", True)
await Config.put("rate_limits.api.requests", 2000)

# Update complex nested structures
await Config.put("queuemizer.interfaces", ["enp4s0", "enp5s0", "enp6s0"])
await Config.put("database.pool", {
    "min_connections": 5,
    "max_connections": 20,
    "timeout": 30
})
```

### Configuration Reloading

```python
# Force reload from all configured sources
await Config.reload()

# Useful for picking up file changes or external updates
```

## Configuration Subscription

### Basic Subscription

Subscribe to configuration changes for reactive programming:

```python
from otpylib_config import Config

async def handle_database_config_change(path, old_value, new_value):
    """React to database configuration changes."""
    if path == "database.max_connections":
        await database_pool.resize(new_value)
    elif path == "database.timeout":
        await database_pool.set_timeout(new_value)

# Subscribe to specific configuration paths
await Config.subscribe("database.*", handle_database_config_change)
```

### Pattern-Based Subscription

Use wildcards to subscribe to multiple related configuration keys:

```python
async def handle_tc_config_change(path, old_value, new_value):
    """Handle traffic control configuration changes."""
    if path.startswith("queuemizer.tc_rules"):
        # Extract interface from path: queuemizer.tc_rules.enp4s0
        interface = path.split('.')[-1]
        await tc_manager.update_rules(interface, new_value)
    
    elif path.startswith("queuemizer.interfaces"):
        await tc_manager.reconfigure_interfaces(new_value)

# Subscribe to all TC-related configuration
await Config.subscribe("queuemizer.tc_rules.*", handle_tc_config_change)
await Config.subscribe("queuemizer.interfaces", handle_tc_config_change)
```

### Multiple Subscriptions

Different parts of your application can subscribe to the same configuration:

```python
# TC Manager subscription
async def tc_config_handler(path, old_value, new_value):
    await tc_manager.handle_config_change(path, new_value)

# Metrics subscription  
async def metrics_config_handler(path, old_value, new_value):
    await metrics_collector.update_config(path, new_value)

# Both subscribe to rate limits
await Config.subscribe("rate_limits.*", tc_config_handler)
await Config.subscribe("rate_limits.*", metrics_config_handler)
```

## Integration Patterns

### GenServer Configuration

GenServers can use configuration for initialization and runtime updates:

```python
# In a GenServer
from otpylib import gen_server
from otpylib_config import Config
import types

worker_callbacks = types.SimpleNamespace()

async def init(config):
    """Initialize GenServer with configuration."""
    # Load initial configuration
    worker_count = await Config.get("worker_pool.size", default=4)
    batch_size = await Config.get("worker_pool.batch_size", default=100)
    
    # Subscribe to configuration changes
    await Config.subscribe("worker_pool.*", _handle_config_change)
    
    return {
        "worker_count": worker_count,
        "batch_size": batch_size,
        "workers": []
    }

async def _handle_config_change(path, old_value, new_value):
    """Handle configuration changes by messaging the GenServer."""
    await gen_server.cast("worker_pool", ("config_changed", path, old_value, new_value))

async def handle_cast(message, state):
    """Handle messages including configuration updates."""
    match message:
        case ("config_changed", "worker_pool.size", old_value, new_value):
            # Resize worker pool
            await _resize_worker_pool(state, new_value)
            state["worker_count"] = new_value
            
        case ("config_changed", "worker_pool.batch_size", old_value, new_value):
            # Update batch processing
            state["batch_size"] = new_value
            await _update_batch_processors(state, new_value)
    
    return (gen_server.NoReply(), state)

worker_callbacks.init = init
worker_callbacks.handle_cast = handle_cast
```

### HTTP API Integration

Expose configuration management through HTTP endpoints:

```python
from otpylib_config import Config

async def get_config_handler(request):
    """Get current configuration values."""
    # Get specific configuration section
    section = request.query.get("section", "")
    
    if section:
        config = await Config.get(section, default={})
    else:
        # Return commonly accessed config
        config = {
            "database": await Config.get("database", default={}),
            "rate_limits": await Config.get("rate_limits", default={}),
            "feature_flags": await Config.get("feature_flags", default={})
        }
    
    return {"config": config}

async def update_config_handler(request):
    """Update configuration via HTTP API."""
    updates = await request.json()
    
    results = {}
    for path, value in updates.items():
        try:
            await Config.put(path, value)
            results[path] = {"status": "updated", "value": value}
        except Exception as e:
            results[path] = {"status": "error", "error": str(e)}
    
    return {"results": results}

async def reload_config_handler(request):
    """Force configuration reload."""
    await Config.reload()
    return {"status": "reloaded"}
```

## Configuration Validation

### Type Validation

Validate configuration values when they're updated:

```python
from typing import Union, List, Dict
import re

class ConfigValidator:
    @staticmethod
    def validate_database_config(config: Dict) -> bool:
        """Validate database configuration structure."""
        required_fields = ["url", "max_connections"]
        
        for field in required_fields:
            if field not in config:
                raise ValueError(f"Missing required field: {field}")
        
        if not isinstance(config["max_connections"], int) or config["max_connections"] <= 0:
            raise ValueError("max_connections must be a positive integer")
        
        return True
    
    @staticmethod  
    def validate_interface_list(interfaces: List[str]) -> bool:
        """Validate network interface list."""
        if not isinstance(interfaces, list):
            raise ValueError("interfaces must be a list")
        
        interface_pattern = re.compile(r'^[a-zA-Z0-9]+$')
        for interface in interfaces:
            if not interface_pattern.match(interface):
                raise ValueError(f"Invalid interface name: {interface}")
        
        return True

# Use validation in configuration change handlers
async def handle_validated_config_change(path, old_value, new_value):
    """Handle configuration changes with validation."""
    try:
        if path == "database":
            ConfigValidator.validate_database_config(new_value)
        elif path == "queuemizer.interfaces":
            ConfigValidator.validate_interface_list(new_value)
        
        # Apply the configuration change
        await apply_config_change(path, new_value)
        
    except ValueError as e:
        print(f"Configuration validation failed for {path}: {e}")
        # Optionally revert to old value
        await Config.put(path, old_value)
```

### Schema-Based Validation

Use structured schemas for complex configuration validation:

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class RateLimitConfig:
    requests: int
    window: int
    burst: Optional[int] = None
    
    def __post_init__(self):
        if self.requests <= 0:
            raise ValueError("requests must be positive")
        if self.window <= 0:
            raise ValueError("window must be positive")

@dataclass
class TCRuleConfig:
    download_mbps: int
    upload_mbps: int
    interface: str
    priority: int = 1
    
    def __post_init__(self):
        if self.download_mbps <= 0 or self.upload_mbps <= 0:
            raise ValueError("bandwidth must be positive")
        if self.priority < 1 or self.priority > 10:
            raise ValueError("priority must be between 1 and 10")

# Validation helper
async def set_validated_config(path: str, value: dict, config_class):
    """Set configuration with dataclass validation."""
    try:
        # Validate using dataclass
        validated_config = config_class(**value)
        
        # Convert back to dict for storage
        await Config.put(path, value)
        
        return True
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid configuration for {path}: {e}")

# Usage
await set_validated_config("rate_limits.api", {
    "requests": 1000,
    "window": 60,
    "burst": 100
}, RateLimitConfig)
```

## Error Handling

### Graceful Defaults

Handle missing or invalid configuration gracefully:

```python
async def get_config_with_fallback(path: str, default=None, fallback_paths: List[str] = None):
    """Get configuration with multiple fallback options."""
    try:
        value = await Config.get(path)
        if value is not None:
            return value
    except Exception:
        pass
    
    # Try fallback paths
    if fallback_paths:
        for fallback_path in fallback_paths:
            try:
                value = await Config.get(fallback_path)
                if value is not None:
                    return value
            except Exception:
                continue
    
    return default

# Usage
database_url = await get_config_with_fallback(
    "database.url",
    default="sqlite:///default.db",
    fallback_paths=["DATABASE_URL", "db.connection_string"]
)
```

### Configuration Health Checks

Monitor configuration system health:

```python
async def check_config_health():
    """Check if configuration system is responsive."""
    try:
        # Test basic operations
        test_value = f"health_check_{time.time()}"
        await Config.put("_health_check", test_value)
        
        retrieved_value = await Config.get("_health_check")
        if retrieved_value != test_value:
            return {"status": "error", "message": "Configuration round-trip failed"}
        
        # Clean up test value
        await Config.put("_health_check", None)
        
        return {"status": "healthy"}
        
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

## Performance Considerations

### Caching Frequently Accessed Values

For hot paths, consider caching configuration values:

```python
class ConfigCache:
    def __init__(self):
        self._cache = {}
        self._subscriptions = {}
    
    async def get_cached(self, path: str, default=None):
        """Get configuration value with local caching."""
        if path not in self._cache:
            # Initial load
            value = await Config.get(path, default=default)
            self._cache[path] = value
            
            # Subscribe to changes if not already subscribed
            if path not in self._subscriptions:
                await Config.subscribe(path, self._handle_change)
                self._subscriptions[path] = True
        
        return self._cache[path]
    
    async def _handle_change(self, path, old_value, new_value):
        """Update cache when configuration changes."""
        self._cache[path] = new_value

# Usage in hot paths
config_cache = ConfigCache()

async def process_request():
    """Hot path with cached config access."""
    rate_limit = await config_cache.get_cached("rate_limits.api.requests", default=1000)
    
    # Use rate_limit value...
```

### Batch Configuration Operations

For multiple related configuration updates:

```python
async def update_tc_configuration(interface: str, rules: dict):
    """Update multiple TC-related configuration values."""
    updates = {
        f"queuemizer.tc_rules.{interface}.download": rules["download"],
        f"queuemizer.tc_rules.{interface}.upload": rules["upload"],
        f"queuemizer.tc_rules.{interface}.priority": rules.get("priority", 1)
    }
    
    # Apply all updates
    for path, value in updates.items():
        await Config.put(path, value)
    
    # Force reload to ensure consistency
    await Config.reload()
```

## Testing Configuration

### Mock Configuration for Tests

```python
class MockConfig:
    """Mock configuration for testing."""
    
    def __init__(self, initial_config=None):
        self._config = initial_config or {}
        self._subscribers = {}
    
    async def get(self, path, default=None):
        return self._config.get(path, default)
    
    async def put(self, path, value):
        old_value = self._config.get(path)
        self._config[path] = value
        
        # Notify subscribers
        for pattern, callback in self._subscribers.items():
            if self._path_matches_pattern(path, pattern):
                await callback(path, old_value, value)
    
    async def subscribe(self, pattern, callback):
        self._subscribers[pattern] = callback
    
    def _path_matches_pattern(self, path, pattern):
        import fnmatch
        return fnmatch.fnmatch(path, pattern)

# Use in tests
async def test_config_driven_behavior():
    """Test that components respond to configuration changes."""
    mock_config = MockConfig({"rate_limits.api": 1000})
    
    # Inject mock config
    original_config = Config
    Config.get = mock_config.get
    Config.put = mock_config.put
    Config.subscribe = mock_config.subscribe
    
    try:
        # Test configuration-driven behavior
        component = MyConfigurableComponent()
        await component.initialize()
        
        # Change configuration
        await mock_config.put("rate_limits.api", 2000)
        
        # Verify component adapted to change
        assert component.current_rate_limit == 2000
        
    finally:
        # Restore original Config
        Config = original_config
```

This client API enables applications to leverage the full power of otpylib-config while maintaining clean separation between configuration management and business logic.
