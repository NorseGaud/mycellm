"""llama-cpp-python inference backend.

All sync llama-cpp-python calls are wrapped in asyncio.to_thread() to avoid
blocking the event loop (critical for QUIC/API handling during inference).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import AsyncIterator

from mycellm.inference.base import (
    InferenceBackend,
    InferenceChunk,
    InferenceRequest,
    InferenceResult,
)

logger = logging.getLogger("mycellm.inference")


def _detect_optimal_threads() -> int:
    """Detect optimal thread count based on platform.

    Apple Silicon: use performance cores only (not efficiency cores).
    Linux: use physical cores (not hyperthreaded logical cores).
    """
    import platform
    import subprocess

    try:
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            # Apple Silicon: p-core count via sysctl
            r = subprocess.run(
                ["sysctl", "-n", "hw.perflevel0.logicalcpu"],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode == 0 and r.stdout.strip():
                cores = int(r.stdout.strip())
                logger.info(f"Apple Silicon detected: {cores} p-cores")
                return cores

        if platform.system() == "Linux":
            import os
            # Physical cores (not hyperthreaded)
            try:
                with open("/proc/cpuinfo") as f:
                    cores = len(set(
                        line.split(":")[1].strip()
                        for line in f if line.startswith("physical id")
                    )) or 1
                logical = os.cpu_count() or 4
                physical = max(1, logical // 2)  # rough estimate
                return physical
            except Exception:
                return max(1, (os.cpu_count() or 4) // 2)
    except Exception:
        pass

    return 0  # let llama.cpp decide


class LlamaCppBackend(InferenceBackend):
    """Inference backend wrapping llama-cpp-python."""

    def __init__(self):
        self._models: dict[str, object] = {}  # name -> Llama instance

    async def load_model(self, model_path: str, **kwargs) -> None:
        """Load a GGUF model (runs in thread to avoid blocking)."""
        from llama_cpp import Llama
        import inspect

        model_name = kwargs.get("name", model_path.split("/")[-1])
        n_ctx = kwargs.get("n_ctx", 4096)
        n_gpu_layers = kwargs.get("n_gpu_layers", -1)  # -1 = auto
        progress_callback = kwargs.get("progress_callback")

        flash_attn = kwargs.get("flash_attn", True)
        kv_quant = kwargs.get("kv_cache_quant", "q8_0")
        kv_quant_k = kwargs.get("kv_cache_quant_k", "")
        kv_quant_v = kwargs.get("kv_cache_quant_v", "")
        prompt_lookup = kwargs.get("prompt_lookup", False)
        n_threads = kwargs.get("n_threads", 0)

        logger.info(f"Loading model {model_name} from {model_path}")

        extra_kwargs = {}
        if progress_callback:
            llama_params = inspect.signature(Llama.__init__).parameters
            if "progress_callback" in llama_params:
                def _on_progress(progress: float) -> bool:
                    progress_callback(progress)
                    return True
                extra_kwargs["progress_callback"] = _on_progress

        # Flash attention (Metal/CUDA optimized attention kernel)
        if flash_attn:
            extra_kwargs["flash_attn"] = True

        # Asymmetric KV cache quantization — keys need higher precision than values
        # Default: K=q8_0 (higher precision), V=q4_0 (lower OK) — 59% less KV memory
        try:
            from llama_cpp import GGML_TYPE_Q8_0, GGML_TYPE_Q4_0
            kv_types = {"q8_0": GGML_TYPE_Q8_0, "q4_0": GGML_TYPE_Q4_0}

            effective_k = kv_quant_k or kv_quant or "q8_0"
            effective_v = kv_quant_v or ("q4_0" if kv_quant_k or not kv_quant_v else kv_quant) or "q4_0"

            if effective_k in kv_types:
                extra_kwargs["type_k"] = kv_types[effective_k]
            if effective_v in kv_types:
                extra_kwargs["type_v"] = kv_types[effective_v]
            logger.info(f"KV cache: K={effective_k}, V={effective_v}")
        except ImportError:
            pass

        # Thread count — auto-detect p-cores on Apple Silicon
        if n_threads <= 0:
            n_threads = _detect_optimal_threads()
        if n_threads > 0:
            extra_kwargs["n_threads"] = n_threads
            extra_kwargs["n_threads_batch"] = n_threads
            logger.info(f"Threads: {n_threads}")

        # Prompt lookup decoding — speeds up repetitive output (code, JSON)
        if prompt_lookup:
            try:
                from llama_cpp.llama_speculative import LlamaPromptLookupDecoding
                extra_kwargs["draft_model"] = LlamaPromptLookupDecoding(num_pred_tokens=10)
                logger.info("Prompt lookup decoding enabled")
            except ImportError:
                logger.warning("LlamaPromptLookupDecoding not available in this llama-cpp-python version")

        try:
            llm = await asyncio.to_thread(
                Llama,
                model_path=model_path,
                n_ctx=n_ctx,
                n_gpu_layers=n_gpu_layers,
                verbose=False,
                **extra_kwargs,
            )
        except Exception as e:
            err_msg = str(e)
            # Detect model load failures — often caused by unsupported architecture
            if "failed to load model" in err_msg.lower():
                model_name_short = model_path.split("/")[-1]
                raise RuntimeError(
                    f"Failed to load {model_name_short}. This may be an unsupported model "
                    f"architecture. Try: pip install --upgrade llama-cpp-python"
                ) from e
            raise

        self._models[model_name] = llm
        logger.info(f"Model {model_name} loaded (flash_attn={flash_attn}, kv_quant={kv_quant})")

    async def unload_model(self, model_name: str) -> None:
        model = self._models.pop(model_name, None)
        if model:
            del model
            logger.info(f"Model {model_name} unloaded")

    async def generate(self, request: InferenceRequest) -> InferenceResult:
        model_name = request.model or next(iter(self._models), "")
        if not model_name or model_name not in self._models:
            raise RuntimeError(f"Model '{model_name}' not loaded")

        llm = self._models[model_name]
        extra_kwargs = {}
        if request.stop:
            extra_kwargs["stop"] = request.stop
        if request.frequency_penalty:
            extra_kwargs["frequency_penalty"] = request.frequency_penalty
        if request.presence_penalty:
            extra_kwargs["presence_penalty"] = request.presence_penalty
        if request.seed is not None:
            extra_kwargs["seed"] = request.seed
        if request.response_format:
            extra_kwargs["response_format"] = request.response_format
        if request.grammar:
            try:
                from llama_cpp import LlamaGrammar
                extra_kwargs["grammar"] = LlamaGrammar.from_string(request.grammar)
            except (ImportError, Exception) as e:
                logger.warning(f"Grammar constraint ignored: {e}")
        response = await asyncio.to_thread(
            llm.create_chat_completion,
            messages=request.messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            top_p=request.top_p,
            **extra_kwargs,
        )

        choice = response["choices"][0]
        usage = response.get("usage", {})

        return InferenceResult(
            text=choice["message"]["content"],
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            finish_reason=choice.get("finish_reason", "stop"),
        )

    async def generate_stream(
        self, request: InferenceRequest
    ) -> AsyncIterator[InferenceChunk]:
        model_name = request.model or next(iter(self._models), "")
        if not model_name or model_name not in self._models:
            raise RuntimeError(f"Model '{model_name}' not loaded")

        llm = self._models[model_name]

        # Use a thread + asyncio.Queue to bridge sync iterator to async generator
        loop = asyncio.get_running_loop()
        chunk_queue: asyncio.Queue = asyncio.Queue()
        _SENTINEL = object()

        extra_kwargs = {}
        if request.stop:
            extra_kwargs["stop"] = request.stop
        if request.frequency_penalty:
            extra_kwargs["frequency_penalty"] = request.frequency_penalty
        if request.presence_penalty:
            extra_kwargs["presence_penalty"] = request.presence_penalty
        if request.seed is not None:
            extra_kwargs["seed"] = request.seed
        if request.response_format:
            extra_kwargs["response_format"] = request.response_format
        if request.grammar:
            try:
                from llama_cpp import LlamaGrammar
                extra_kwargs["grammar"] = LlamaGrammar.from_string(request.grammar)
            except (ImportError, Exception) as e:
                logger.warning(f"Grammar constraint ignored: {e}")

        def _run_stream():
            try:
                stream = llm.create_chat_completion(
                    messages=request.messages,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    top_p=request.top_p,
                    stream=True,
                    **extra_kwargs,
                )
                for chunk in stream:
                    loop.call_soon_threadsafe(chunk_queue.put_nowait, chunk)
            except Exception as e:
                loop.call_soon_threadsafe(chunk_queue.put_nowait, e)
            finally:
                loop.call_soon_threadsafe(chunk_queue.put_nowait, _SENTINEL)

        thread = threading.Thread(target=_run_stream, daemon=True)
        thread.start()

        while True:
            item = await chunk_queue.get()
            if item is _SENTINEL:
                break
            if isinstance(item, Exception):
                raise item
            delta = item["choices"][0].get("delta", {})
            content = delta.get("content", "")
            finish = item["choices"][0].get("finish_reason")
            if content or finish:
                yield InferenceChunk(text=content, finish_reason=finish)

    async def embed(self, request):
        from mycellm.inference.base import EmbeddingResult
        model_name = request.model
        model = self._models.get(model_name)
        if not model:
            model = next(iter(self._models.values()), None)
        if not model:
            raise RuntimeError("No model loaded for embeddings")

        inputs = request.input if isinstance(request.input, list) else [request.input]
        result = await asyncio.to_thread(model.create_embedding, inputs)

        embeddings = [d["embedding"] for d in result["data"]]
        total_tokens = result.get("usage", {}).get("total_tokens", 0)
        return EmbeddingResult(embeddings=embeddings, total_tokens=total_tokens)

    def get_loaded_models(self) -> list[str]:
        return list(self._models.keys())

    def get_capabilities(self) -> dict:
        """Detect hardware capabilities."""
        try:
            from llama_cpp import llama_backend_info
            return {"backend": "llama.cpp", "info": str(llama_backend_info)}
        except Exception:
            return {"backend": "llama.cpp", "info": "unknown"}
