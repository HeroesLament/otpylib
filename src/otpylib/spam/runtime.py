"""
SPAM Runtime

User-facing runtime orchestrator for Sypher's Abstract Python Machine.
Provides context manager and manual setup interfaces for SPAM scheduling.
"""

import os
import sys
import asyncio
import logging
from typing import Optional, Dict, Any, List
import anyio

from .data import (
    RuntimeConfig, OTPProcess, ProcessType, SPAMError, 
    GlobalSchedulerState, ProcessCharacteristics
)
from .scheduler import WorkStealingScheduler
from .core import CoreScheduler

logger = logging.getLogger(__name__)


class SPAMRuntime:
    """
    Main SPAM runtime orchestrator.
    
    Provides both context manager and manual setup/teardown interfaces
    for managing the SPAM process scheduler. Integrates with the otpylib
    runtime abstraction to provide transparent scheduling services.
    """
    
    # Global instance for fallback runtime detection
    _global_instance: Optional['SPAMRuntime'] = None
    
    def __init__(self, config: Optional[RuntimeConfig] = None):
        self.config = config or RuntimeConfig.auto_detect()
        self.scheduler: Optional[WorkStealingScheduler] = None
        self.initialized = False
        self._previous_backend = None
        
        # Runtime state tracking
        self._startup_time = 0.0
        self._shutdown_hooks = []
        
    async def initialize(self):
        """Initialize the SPAM runtime manually"""
        if self.initialized:
            logger.warning("SPAM runtime already initialized")
            return
            
        logger.info(f"Initializing SPAM runtime in {self.config.mode.value} mode")
        self._startup_time = asyncio.get_event_loop().time()
        
        try:
            # Initialize scheduler
            await self._setup_scheduler()
            
            # Install as runtime backend
            await self._install_as_runtime_backend()
            
            self.initialized = True
            SPAMRuntime._global_instance = self
            
            logger.info(f"SPAM runtime initialized successfully with {self.config.core_count} cores")
            
        except Exception as e:
            logger.error(f"Failed to initialize SPAM runtime: {e}")
            await self._cleanup_on_failure()
            raise SPAMError(f"SPAM runtime initialization failed: {e}") from e
            
    async def shutdown(self):
        """Shutdown the SPAM runtime manually"""
        if not self.initialized:
            return
            
        logger.info("Shutting down SPAM runtime")
        
        try:
            # Execute shutdown hooks
            for hook in reversed(self._shutdown_hooks):
                try:
                    await hook()
                except Exception as e:
                    logger.error(f"Shutdown hook error: {e}")
            
            # Shutdown scheduler
            if self.scheduler:
                await self.scheduler.shutdown()
                
            # Restore previous runtime backend
            await self._restore_previous_runtime_backend()
            
            self.initialized = False
            if SPAMRuntime._global_instance is self:
                SPAMRuntime._global_instance = None
                
            runtime_duration = asyncio.get_event_loop().time() - self._startup_time
            logger.info(f"SPAM runtime shutdown complete (ran for {runtime_duration:.2f}s)")
            
        except Exception as e:
            logger.error(f"Error during SPAM runtime shutdown: {e}")
            
    async def __aenter__(self):
        """Context manager entry"""
        await self.initialize()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        await self.shutdown()
        
    async def _setup_scheduler(self):
        """Initialize the work-stealing scheduler"""
        self.scheduler = WorkStealingScheduler(self.config)
        await self.scheduler.initialize()
            
    async def _install_as_runtime_backend(self):
        """Install SPAM as the global runtime backend"""
        try:
            # For now, just store that we're the active runtime
            # This will integrate with otpylib.runtime when that exists
            logger.debug("SPAM runtime backend ready (integration pending)")
        except Exception as e:
            logger.error(f"Failed to setup runtime backend: {e}")
            
    async def _restore_previous_runtime_backend(self):
        """Restore the previous runtime backend"""
        # Placeholder for when otpylib.runtime exists
        logger.debug("Runtime backend cleanup complete")
                
    async def _cleanup_on_failure(self):
        """Cleanup resources on initialization failure"""
        if self.scheduler:
            try:
                await self.scheduler.shutdown()
            except Exception:
                pass
                
    async def run_forever(self):
        """Run the SPAM runtime until shutdown is requested"""
        if not self.initialized:
            raise SPAMError("SPAM runtime not initialized")
            
        logger.info("Starting SPAM runtime main loop")
        
        try:
            await self.scheduler.run_forever()
        except KeyboardInterrupt:
            logger.info("Received interrupt signal, shutting down")
        except Exception as e:
            logger.error(f"SPAM runtime error: {e}")
            raise
            
    # Process management interface
    
    async def spawn_process(self, process: OTPProcess) -> str:
        """Spawn a new process on the scheduler"""
        if not self.initialized or not self.scheduler:
            raise SPAMError("SPAM runtime not initialized")
            
        return await self.scheduler.spawn_process(process)
        
    async def terminate_process(self, pid: str, reason: str = "manual_termination") -> bool:
        """Terminate a specific process"""
        if not self.initialized or not self.scheduler:
            raise SPAMError("SPAM runtime not initialized")
            
        return await self.scheduler.terminate_process(pid, reason)
        
    async def send_message(self, target, message) -> bool:
        """Send a message to a process"""
        if not self.initialized or not self.scheduler:
            raise SPAMError("SPAM runtime not initialized")
            
        return await self.scheduler.send_message(target, message)
        
    def get_process_info(self, pid: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific process"""
        if not self.initialized or not self.scheduler:
            return None
            
        return self.scheduler.get_process_info(pid)
        
    def list_processes(self, process_type: Optional[ProcessType] = None) -> List[Dict[str, Any]]:
        """List all processes with optional filtering"""
        if not self.initialized or not self.scheduler:
            return []
            
        return self.scheduler.list_processes(process_type)
        
    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive runtime statistics"""
        if not self.initialized or not self.scheduler:
            return {}
            
        stats = self.scheduler.get_scheduler_statistics()
        
        # Add runtime-specific statistics
        stats.update({
            'runtime_info': {
                'mode': self.config.mode.value,
                'core_count': self.config.core_count,
                'time_slice_ms': self.config.time_slice_ms,
                'work_stealing_enabled': self.config.work_stealing_enabled,
                'hot_reload_enabled': self.config.hot_reload_enabled
            }
        })
        
        return stats
        
    # Hot reload support
    
    async def hot_reload_module(self, module_name: str, new_module_binary: bytes) -> Dict[str, Any]:
        """Perform hot reload of a module across affected processes"""
        if not self.initialized:
            raise SPAMError("SPAM runtime not initialized")
            
        # This would integrate with hot reload implementation
        # For now, return placeholder
        return {
            'status': 'not_implemented',
            'message': 'Hot reload functionality not yet implemented'
        }
        
    # Utility methods
    
    def add_shutdown_hook(self, hook: callable):
        """Add a shutdown hook to be called during runtime shutdown"""
        if asyncio.iscoroutinefunction(hook):
            self._shutdown_hooks.append(hook)
        else:
            # Wrap sync function
            async def async_hook():
                hook()
            self._shutdown_hooks.append(async_hook)
            
    @classmethod
    def get_global_instance(cls) -> Optional['SPAMRuntime']:
        """Get the global SPAM runtime instance if available"""
        return cls._global_instance
        
    @classmethod
    def is_available(cls) -> bool:
        """Check if SPAM runtime is available and initialized"""
        return cls._global_instance is not None and cls._global_instance.initialized
        
    def __repr__(self) -> str:
        status = "initialized" if self.initialized else "uninitialized"
        return f"SPAMRuntime(mode={self.config.mode.value}, cores={self.config.core_count}, {status})"


# Convenience functions for common usage patterns

async def create_and_run_runtime(config: Optional[RuntimeConfig] = None) -> SPAMRuntime:
    """Create and initialize a SPAM runtime with auto-detected configuration"""
    runtime = SPAMRuntime(config)
    await runtime.initialize()
    return runtime
    
async def run_with_spam(coro, config: Optional[RuntimeConfig] = None):
    """Run a coroutine with SPAM runtime context manager"""
    async with SPAMRuntime(config):
        return await coro
        
def detect_spam_capability() -> Dict[str, Any]:
    """Detect system capabilities for SPAM runtime"""
    
    # Check for free-threading
    gil_disabled = False
    try:
        gil_disabled = hasattr(sys, '_is_gil_enabled') and not sys._is_gil_enabled()
    except:
        pass
        
    return {
        'free_threading_available': gil_disabled,
        'core_count': os.cpu_count() or 1,
        'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        'platform': sys.platform,
        'recommended_mode': 'work_stealing' if gil_disabled else 'cooperative'
    }
