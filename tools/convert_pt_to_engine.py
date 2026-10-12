"""Export one or more YOLO .pt weights as FP16 TensorRT engines."""

import argparse
import sys
import traceback
from pathlib import Path

# The engine is compiled for one fixed square input, and the native runtime
# resizes its capture to that shape. Exporting at 640 when the capture FOV is
# much smaller upscales every frame (adding no detail) and runs inference on
# 640^2 pixels, roughly 50% wasted compute for a ~519 FOV. Pass --imgsz equal to
# the capture FOV rounded up to a multiple of 32 to match the runtime exactly.
DEFAULT_INPUT_SIZE = 640


def parse_args():
    parser = argparse.ArgumentParser(
        description="Convert YOLO .pt weights to FP16 TensorRT .engine files."
    )
    parser.add_argument(
        "models",
        nargs="+",
        type=Path,
        help="One or more .pt model files (you can drag and drop them onto the .bat file).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing .engine file without prompting.",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=DEFAULT_INPUT_SIZE,
        help="Fixed inference input size (square). Use the capture FOV rounded up "
             "to a multiple of 32 (e.g. 519 -> 544) so the engine matches what it "
             "is fed and no per-frame upscale is paid. Defaults to %d."
             % DEFAULT_INPUT_SIZE,
    )
    args = parser.parse_args()
    if args.imgsz < 32:
        parser.error("--imgsz must be at least 32")
    # YOLO/TRT require the input divisible by 32 (deepest feature-map stride).
    rounded = ((args.imgsz + 31) // 32) * 32
    if rounded != args.imgsz:
        print(f"Rounding --imgsz {args.imgsz} up to {rounded} (multiple of 32).")
    args.imgsz = rounded
    return args


def convert_model(model_path, overwrite, imgsz):
    engine_path = model_path.with_suffix(".engine")
    success = False
    cleanup_succeeded = True

    try:
        if engine_path.exists() and not overwrite:
            try:
                answer = input(
                    f"{engine_path.name} already exists. Replace it? [y/N] "
                )
            except EOFError:
                answer = ""
            if answer.strip().lower() not in {"y", "yes"}:
                print(f"Keeping existing engine: {engine_path}")
                return True

        print(f"\nConverting: {model_path}")
        print(f"Output:     {engine_path}")
        try:
            import torch
            import tensorrt as trt
            from ultralytics import YOLO
        except ImportError as exc:
            print(f"Missing conversion dependency: {exc}")
            print(
                "Install CUDA-enabled PyTorch, TensorRT, ModelOpt, and Ultralytics "
                "in the project's .venv, then run this script again."
            )
            return False

        if not torch.cuda.is_available():
            print("CUDA is not available to this Python environment.")
            print(
                "Install a CUDA-enabled PyTorch build in the project's .venv "
                "and confirm torch.cuda.is_available() is True."
            )
            return False

        print(
            f"GPU:        {torch.cuda.get_device_name(0)}\n"
            f"TensorRT:   {trt.__version__}\n"
            f"Input size: {imgsz} (FP16)"
        )
        try:
            model = YOLO(str(model_path))
            result = model.export(
                format="engine",
                imgsz=imgsz,
                quantize=16,
                device=0,
            )
        except Exception:
            print(f"Export failed for {model_path.name}:")
            traceback.print_exc()
            return False

        exported_path = Path(result) if result else engine_path
        if not exported_path.is_file():
            print(
                "Export returned without creating the expected engine file. "
                f"Expected: {engine_path}"
            )
            return False
        print(f"Export complete: {exported_path}")
        success = True
    finally:
        for onnx_path in model_path.parent.glob(f"{model_path.stem}*.onnx"):
            try:
                onnx_path.unlink()
                print(f"Removed intermediate: {onnx_path}")
            except OSError as exc:
                print(f"Could not remove intermediate {onnx_path}: {exc}")
                cleanup_succeeded = False

    return success and cleanup_succeeded


def main():
    args = parse_args()
    model_paths = [path.expanduser().resolve() for path in args.models]
    valid_models = 0
    had_invalid_input = False

    for model_path in model_paths:
        if model_path.suffix.lower() != ".pt":
            print(f"Unsupported file (expected .pt): {model_path}")
            had_invalid_input = True
            continue
        if not model_path.is_file():
            print(f"Model file not found: {model_path}")
            had_invalid_input = True
            continue
        valid_models += 1

        if not convert_model(model_path, args.overwrite, args.imgsz):
            return 1

    return 1 if had_invalid_input or valid_models == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
