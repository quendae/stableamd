import json
import platform
import sys
import time


result = {
    "python_version": platform.python_version(),
    "torch_version": None,
    "hip_version": None,
    "gpu_available": False,
    "device_name": None,
    "device_index": None,
    "vram_bytes": None,
    "fp16_matmul_ok": False,
    "fp16_matmul_ms": None,
    "error_type": None,
    "error": None,
}

try:
    import torch

    result["torch_version"] = torch.__version__
    result["hip_version"] = getattr(torch.version, "hip", None)
    result["gpu_available"] = bool(torch.cuda.is_available())

    if not result["gpu_available"]:
        raise RuntimeError(
            "torch.cuda.is_available() returned False; ROCm PyTorch did not expose a usable GPU"
        )

    device_index = torch.cuda.current_device()
    props = torch.cuda.get_device_properties(device_index)
    result["device_index"] = int(device_index)
    result["device_name"] = torch.cuda.get_device_name(device_index)
    result["vram_bytes"] = int(props.total_memory)

    a = torch.randn((2048, 2048), device="cuda", dtype=torch.float16)
    b = torch.randn((2048, 2048), device="cuda", dtype=torch.float16)
    torch.cuda.synchronize()
    started = time.perf_counter()
    c = a @ b
    torch.cuda.synchronize()
    result["fp16_matmul_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    result["fp16_matmul_ok"] = bool(torch.isfinite(c).all().item())

    if not result["fp16_matmul_ok"]:
        raise RuntimeError(
            "FP16 matrix multiplication completed but produced non-finite values"
        )
except Exception as exc:
    result["error_type"] = type(exc).__name__
    result["error"] = str(exc)
    print(json.dumps(result, separators=(",", ":")))
    sys.exit(1)

print(json.dumps(result, separators=(",", ":")))
