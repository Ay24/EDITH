import os
import time
import logging
import threading
from typing import Dict, Any, Optional
from dataclasses import dataclass

try:
    import psutil
    import pynvml
except ImportError:
    psutil = None
    pynvml = None

try:
    from llama_cpp import Llama
except ImportError:
    Llama = None

logger = logging.getLogger(__name__)

@dataclass
class HardwareProfile:
    name: str
    max_vram_mb: int
    n_ctx: int
    n_batch: int
    n_threads_offset: int

PROFILES = {
    "ultra_stable": HardwareProfile("Ultra Stable", 1200, 1024, 128, -4),
    "balanced":     HardwareProfile("Balanced",     1600, 2048, 256, -2),
    "performance":  HardwareProfile("Performance",  2400, 4096, 512, -1),
}

class AdaptiveLlamaEngine:
    """
    Manages a native llama.cpp instance, dynamically scaling resources to prevent OS freezing.
    """
    def __init__(self, model_path: str, profile_name: str = "balanced"):
        self.model_path = model_path
        self._llm: Optional[Any] = None
        self._current_profile = PROFILES.get(profile_name, PROFILES["balanced"])
        self._monitor_thread = None
        self._running = False
        self._gpu_layers = 0
        
        # Hardware limits tracking
        self.total_ram = 0
        self.total_vram = 0
        self._init_hardware_monitoring()
        
    def _init_hardware_monitoring(self):
        if not psutil or not pynvml:
            logger.warning("Hardware monitoring disabled. Please install psutil and pynvml.")
            return
            
        try:
            pynvml.nvmlInit()
            self.gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(self.gpu_handle)
            self.total_vram = mem_info.total / (1024 * 1024)
            self.total_ram = psutil.virtual_memory().total / (1024 * 1024)
            logger.info(f"Hardware detected: {self.total_ram:.0f}MB RAM, {self.total_vram:.0f}MB VRAM")
        except Exception as e:
            logger.error(f"Failed to init NVML: {e}")

    def get_hardware_state(self) -> Dict[str, float]:
        if not psutil or not pynvml:
            return {"cpu": 0, "ram_free": 0, "vram_free": 0}
            
        try:
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(self.gpu_handle)
            vram_free = mem_info.free / (1024 * 1024)
        except Exception:
            vram_free = 0
            
        return {
            "cpu": psutil.cpu_percent(),
            "ram_free": psutil.virtual_memory().available / (1024 * 1024),
            "vram_free": vram_free
        }

    def _calculate_safe_layers(self, target_vram_mb: int) -> int:
        """
        Estimate how many layers can fit into target_vram_mb.
        This is a rough heuristic. llama.cpp calculates exactly per model, but we approximate.
        A 3B parameter model takes ~35MB per layer in 4-bit quantization.
        """
        if self.total_vram == 0:
            return 0
            
        # We assume Llama-3.2 3B or similar (~35MB/layer for weights + ~5MB for cache).
        mb_per_layer = 40 
        safe_layers = min(99, int(target_vram_mb / mb_per_layer))
        return safe_layers

    def _load_model(self):
        if not Llama:
            raise RuntimeError("llama-cpp-python not installed. Cannot load native model.")

        state = self.get_hardware_state()
        safe_vram = min(self._current_profile.max_vram_mb, max(0, state["vram_free"] - 500))
        self._gpu_layers = self._calculate_safe_layers(safe_vram)

        cpu_count = os.cpu_count() or 4
        n_threads = max(2, cpu_count + self._current_profile.n_threads_offset)

        logger.info(f"Loading model: {self.model_path}")
        logger.info(f"Profile={self._current_profile.name}, n_ctx={self._current_profile.n_ctx}, "
                    f"n_gpu_layers={self._gpu_layers}, n_threads={n_threads}")

        base_kwargs = dict(
            model_path=self.model_path,
            n_ctx=self._current_profile.n_ctx,
            n_batch=self._current_profile.n_batch,
            n_threads=n_threads,
            use_mmap=False,   # Safer on Windows — mmap can cause file-lock issues
            use_mlock=False,
            verbose=False,
        )

        # Try with GPU layers first, fall back to CPU-only if it fails
        for gpu_layers in [self._gpu_layers, 0]:
            failed_llm = None
            try:
                self._llm = Llama(**base_kwargs, n_gpu_layers=gpu_layers)
                logger.info(f"Model loaded successfully (n_gpu_layers={gpu_layers})")
                return
            except Exception as e:
                logger.warning(f"Model load failed with n_gpu_layers={gpu_layers}: {e}")
                # Capture the failed partial object and delete it explicitly
                # to avoid the 'LlamaModel has no attribute sampler' __del__ error
                failed_llm = self._llm
                self._llm = None
            finally:
                if failed_llm is not None:
                    try:
                        del failed_llm
                    except Exception:
                        pass

        raise RuntimeError(f"Failed to load native model from {self.model_path} (tried GPU and CPU).")


    def generate(self, prompt: str, max_tokens: int = 512, stop=None, stream: bool = False):
        if not self._llm:
            self._load_model()  # raises on failure — no silent None return

        return self._llm(
            prompt,
            max_tokens=max_tokens,
            stop=stop or ["<|eot_id|>", "User:", "\n\nUser"],
            stream=stream,
        )

    def chat_generate(self, messages: list[dict], max_tokens: int = 512, stream: bool = False):
        if not self._llm:
            self._load_model()

        return self._llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            stream=stream,
        )

    def set_profile(self, profile_name: str):
        if profile_name in PROFILES and profile_name != self._current_profile.name.lower().replace(" ", "_"):
            self._current_profile = PROFILES[profile_name]
            logger.info(f"Switching to profile: {profile_name}. Unloading current model.")
            self._llm = None # Force reload on next generation
            
    def shutdown(self):
        """Release the model and free GPU VRAM."""
        self._running = False
        llm = self._llm
        self._llm = None
        # Explicitly delete the Llama object so Python drops the ref count
        # and the CUDA context is released before the next load attempt.
        if llm is not None:
            try:
                del llm
            except Exception:
                pass
        import gc
        gc.collect()
        if pynvml:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
