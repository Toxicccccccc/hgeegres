"""Build one or more .onnx models into FP16 TensorRT engines.

Mirrors the output settings used by convert_pt_to_engine.py:
FP16 precision (quantize=16), GPU device 0, and a fixed square input whose size
comes from --imgsz (default 640). Pass the capture FOV rounded to a multiple of
32 to avoid a per-frame upscale and the wasted compute it implies.

Ultralytics cannot `export` from an .onnx file (it only accepts .pt), so the
TensorRT engine is built directly with TensorRT's ONNX parser instead.
"""

import argparse
import sys
import traceback
from pathlib import Path

try:
    import tensorrt as trt
except ImportError:  # Reported with a friendly message in convert_model().
    trt = None


# Default input size. The engine is compiled for ONE fixed shape, and the native
# runtime resizes whatever it captures to that shape. Building at 640 when the
# capture FOV is much smaller makes every frame upscale (no added detail) and run
# inference on 640^2 pixels -- roughly 50% wasted compute for a ~519 FOV. Export
# at the size the runtime actually feeds (see --imgsz).
DEFAULT_INPUT_SIZE = 640
INPUT_SIZE = DEFAULT_INPUT_SIZE
WORKSPACE_GIB = 4


def parse_args():
    parser = argparse.ArgumentParser(
        description="Convert .onnx models to FP16 TensorRT .engine files."
    )
    parser.add_argument(
        "models",
        nargs="+",
        type=Path,
        help="One or more .onnx model files (you can drag and drop them onto the .bat file).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing .engine file without prompting.",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=None,
        help="Fixed inference input size (square). Build at the size the engine "
             "feeds the model to avoid a per-frame upscale and wasted compute; "
             "use the FOV from the Capture page, rounded up to a multiple of 32 "
             "(e.g. a 519 FOV -> 544). Defaults to %d." % DEFAULT_INPUT_SIZE,
    )
    args = parser.parse_args()
    # A YOLO/TRT engine needs the input divisible by 32 (the stride of the
    # deepest feature map); round up rather than fail so a raw FOV can be passed.
    if args.imgsz is not None:
        if args.imgsz < 32:
            parser.error("--imgsz must be at least 32")
        global INPUT_SIZE
        INPUT_SIZE = ((args.imgsz + 31) // 32) * 32
        if INPUT_SIZE != args.imgsz:
            print(f"Rounding --imgsz {args.imgsz} up to {INPUT_SIZE} (multiple of 32).")
    return args


def patch_dynamic_shapes(network, logger, input_size):
    """Force a 640x640 dynamic input if the ONNX graph leaves it undefined."""
    for i in range(network.num_inputs):
        tensor = network.get_input(i)
        shape = list(tensor.shape)
        if any(dim < 0 for dim in shape):
            dims = [dim if dim > 0 else input_size for dim in shape]
            if len(dims) >= 4:
                dims = [1] + [input_size] * (len(dims) - 1)
            tensor.shape = dims
            logger.log(
                trt.Logger.INFO, f"Set input '{tensor.name}' shape to {dims}"
            )


def enable_fp16_on_onnx(onnx_path, logger):
    """Produce an FP16 copy of the ONNX model.

    TensorRT >= 11 removed the BuilderFlag.FP16 switch; precision is driven by
    the tensor types in the network, and TRT requires every operand of an
    operator to share a type. So the whole graph (weights included) is
    converted to FP16, matching the .pt converter's quantize=16 / half=True.

    Returns a path to a temporary FP16 ONNX file, or None on failure.
    """
    try:
        import onnx
        from onnxconverter_common import float16
    except ImportError:
        logger.log(
            trt.Logger.WARNING,
            "onnxconverter-common unavailable; building at default precision.",
        )
        return None

    try:
        model = onnx.load(str(onnx_path))
        model_fp16 = float16.convert_float_to_float16(
            model, keep_io_types=True, disable_shape_infer=False
        )
    except Exception as exc:  # Conversion is best-effort; fall back to FP32.
        logger.log(
            trt.Logger.WARNING, f"FP16 ONNX conversion failed ({exc}); using FP32."
        )
        return None

    temp_path = onnx_path.with_name(f"{onnx_path.stem}__fp16.onnx")
    onnx.save(model_fp16, str(temp_path))
    logger.log(trt.Logger.INFO, f"Wrote FP16 ONNX: {temp_path.name}")
    return temp_path


def build_engine(onnx_path, engine_path, logger):
    builder = trt.Builder(logger)
    # TensorRT 10+/11 uses explicit batch by default; EXPLICIT_BATCH was
    # removed from NetworkDefinitionCreationFlag in TRT 11.
    flags = 0
    if hasattr(trt.NetworkDefinitionCreationFlag, "EXPLICIT_BATCH"):
        flags = 1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)
    network = builder.create_network(flags)
    parser = trt.OnnxParser(network, logger)

    use_legacy_fp16_flag = hasattr(trt.BuilderFlag, "FP16")
    parse_path = onnx_path
    temp_onnx = None
    if not use_legacy_fp16_flag:
        # TRT >= 11: no FP16 builder flag, so request FP16 on the ONNX graph.
        temp_onnx = enable_fp16_on_onnx(onnx_path, logger)
        if temp_onnx is not None:
            parse_path = temp_onnx

    try:
        with open(parse_path, "rb") as handle:
            if not parser.parse(handle.read()):
                for index in range(parser.num_errors):
                    logger.log(
                        trt.Logger.ERROR, f"ONNX parse error: {parser.get_error(index)}"
                    )
                raise RuntimeError(f"Failed to parse ONNX file: {onnx_path}")

        patch_dynamic_shapes(network, logger, INPUT_SIZE)

        config = builder.create_builder_config()
        config.set_memory_pool_limit(
            trt.MemoryPoolType.WORKSPACE, WORKSPACE_GIB * (1 << 30)
        )
        config.set_flag(trt.BuilderFlag.TF32)
        if use_legacy_fp16_flag:
            # TensorRT <= 10 style: enable FP16 kernels globally.
            config.set_flag(trt.BuilderFlag.FP16)
            logger.log(trt.Logger.INFO, "FP16 requested via: builder-flag")
        else:
            logger.log(trt.Logger.INFO, "FP16 requested via: onnx conversion")
        if hasattr(builder, "platform_has_tf32") and not builder.platform_has_tf32:
            config.clear_flag(trt.BuilderFlag.TF32)
        if hasattr(builder, "platform_has_fast_fp16") and not builder.platform_has_fast_fp16:
            logger.log(
                trt.Logger.WARNING,
                "GPU does not report fast FP16 support; engine may run slower.",
            )

        serialized = builder.build_serialized_network(network, config)
        if serialized is None:
            raise RuntimeError(f"TensorRT failed to build an engine for {onnx_path}")
        with open(engine_path, "wb") as handle:
            handle.write(serialized)
    finally:
        if temp_onnx is not None and temp_onnx.exists():
            try:
                temp_onnx.unlink()
            except OSError as exc:
                logger.log(
                    trt.Logger.WARNING,
                    f"Could not remove temporary {temp_onnx}: {exc}",
                )


def convert_model(model_path, overwrite):
    engine_path = model_path.with_suffix(".engine")

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

    print(f"\nBuilding:   {model_path}")
    print(f"Output:     {engine_path}")
    try:
        import torch
    except ImportError as exc:
        print(f"Missing conversion dependency: {exc}")
        print(
            "Install CUDA-enabled PyTorch, TensorRT, and Ultralytics "
            "in the project's .venv, then run this script again."
        )
        return False

    if trt is None:
        print("TensorRT is not installed in the project's .venv.")
        print("Install TensorRT, then run this script again.")
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
        f"Precision:  FP16\n"
        f"Input size: {INPUT_SIZE}"
    )

    try:
        logger = trt.Logger(trt.Logger.INFO)
        build_engine(model_path, engine_path, logger)
    except Exception:
        print(f"Build failed for {model_path.name}:")
        traceback.print_exc()
        return False

    if not engine_path.is_file():
        print(f"Engine was not created: {engine_path}")
        return False
    print(f"Engine complete: {engine_path}")
    return True


def main():
    args = parse_args()
    model_paths = [path.expanduser().resolve() for path in args.models]
    valid_models = 0
    had_invalid_input = False

    for model_path in model_paths:
        if model_path.suffix.lower() != ".onnx":
            print(f"Unsupported file (expected .onnx): {model_path}")
            had_invalid_input = True
            continue
        if not model_path.is_file():
            print(f"Model file not found: {model_path}")
            had_invalid_input = True
            continue
        valid_models += 1

        if not convert_model(model_path, args.overwrite):
            return 1

    return 1 if had_invalid_input or valid_models == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
