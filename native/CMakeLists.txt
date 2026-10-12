cmake_minimum_required(VERSION 3.24)

project(DisabledAssistanceNative LANGUAGES CXX CUDA)
include(CTest)

# Emit compile_commands.json so editors (VS Code C++/CMake Tools, clangd, CLion)
# can resolve the CUDA, TensorRT, and Windows SDK headers. Without it the editor
# cannot find those includes and marks working code as erroneous.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

set(TENSORRT_ROOT "" CACHE PATH "TensorRT SDK root containing include, lib, bin, and cmake")
if(NOT TENSORRT_ROOT)
    if(DEFINED ENV{TENSORRT_ROOT})
        set(TENSORRT_ROOT "$ENV{TENSORRT_ROOT}")
    else()
        message(FATAL_ERROR "Set TENSORRT_ROOT to the extracted TensorRT SDK root.")
    endif()
endif()

find_package(CUDAToolkit REQUIRED)

set(TENSORRT_INCLUDE_DIR "${TENSORRT_ROOT}/include")
set(TENSORRT_IMPORT_LIBRARY "${TENSORRT_ROOT}/lib/nvinfer_11.lib")
set(TENSORRT_RUNTIME_DLL "${TENSORRT_ROOT}/bin/nvinfer_11.dll")
foreach(required_path IN ITEMS
    "${TENSORRT_INCLUDE_DIR}/NvInfer.h"
    "${TENSORRT_IMPORT_LIBRARY}"
    "${TENSORRT_RUNTIME_DLL}"
)
    if(NOT EXISTS "${required_path}")
        message(FATAL_ERROR "Required TensorRT SDK file not found: ${required_path}")
    endif()
endforeach()

add_library(TensorRT::Runtime SHARED IMPORTED GLOBAL)
set_target_properties(TensorRT::Runtime PROPERTIES
    IMPORTED_IMPLIB "${TENSORRT_IMPORT_LIBRARY}"
    IMPORTED_LOCATION "${TENSORRT_RUNTIME_DLL}"
    INTERFACE_INCLUDE_DIRECTORIES "${TENSORRT_INCLUDE_DIR}"
)

add_executable(native_engine_probe
    src/model_probe.cpp
)

target_compile_features(native_engine_probe PRIVATE cxx_std_20)
target_compile_definitions(native_engine_probe PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(native_engine_probe PRIVATE TensorRT::Runtime CUDA::cudart)

add_library(native_engine_core STATIC
    src/cuda_preprocess.cu
    src/tensorrt_yolo.cpp
)
target_include_directories(native_engine_core PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_compile_features(native_engine_core PUBLIC cxx_std_20)
set_target_properties(native_engine_core PROPERTIES
    CUDA_ARCHITECTURES 120
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
)
target_compile_definitions(native_engine_core PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(native_engine_core PUBLIC TensorRT::Runtime CUDA::cudart)

add_library(native_aimassist STATIC
    src/settings.cpp
    src/capture.cpp
    src/capture_backend.cpp
    src/dxgi_capture.cpp
    src/targeting.cpp
    src/input.cpp
    src/input_provider.cpp
    src/serial_bridge.cpp
    src/telemetry.cpp
    src/dataset.cpp
    src/engine.cpp
)
target_include_directories(native_aimassist PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_compile_features(native_aimassist PUBLIC cxx_std_20)
target_compile_definitions(native_aimassist PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(native_aimassist PUBLIC native_engine_core user32 gdi32 d3d11 dxgi)

add_executable(native_engine_infer_probe
    src/inference_probe.cpp
)
target_compile_features(native_engine_infer_probe PRIVATE cxx_std_20)
target_compile_definitions(native_engine_infer_probe PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(native_engine_infer_probe PRIVATE native_engine_core)

# Offline detection harness: run one image through the real inference path and
# optionally write an annotated copy. Needs no capture, serial port, or game.
add_executable(native_detect_image
    src/detect_image.cpp
)
target_compile_features(native_detect_image PRIVATE cxx_std_20)
target_compile_definitions(native_detect_image PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(native_detect_image PRIVATE native_engine_core)

add_executable(native_targeting_test
    src/targeting_test.cpp
)
target_compile_features(native_targeting_test PRIVATE cxx_std_20)
target_compile_definitions(native_targeting_test PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(native_targeting_test PRIVATE native_aimassist)

add_executable(native_movement_test
    src/movement_test.cpp
)
target_compile_features(native_movement_test PRIVATE cxx_std_20)
target_compile_definitions(native_movement_test PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(native_movement_test PRIVATE native_aimassist)

# Input binding resolution and lock-key toggle behaviour. Guards the two ways a
# lock key has silently done nothing: an unresolved binding, and a toggle that
# never latches.
add_executable(native_input_test
    src/input_test.cpp
)
target_compile_features(native_input_test PRIVATE cxx_std_20)
target_compile_definitions(native_input_test PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(native_input_test PRIVATE native_aimassist)

# SigmaDrift convergence and snappiness. Guards the regression where the stroke
# stalled or crawled for hundreds of milliseconds and looked like it did nothing.
add_executable(native_sigma_drift_test
    src/sigma_drift_test.cpp
)
target_compile_features(native_sigma_drift_test PRIVATE cxx_std_20)
target_compile_definitions(native_sigma_drift_test PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(native_sigma_drift_test PRIVATE native_aimassist)

# Simulated tracking lag. Drives process_detections against a moving target and
# asserts the hard lock holds it rather than trailing behind.
add_executable(native_tracking_test
    src/tracking_test.cpp
)
target_compile_features(native_tracking_test PRIVATE cxx_std_20)
target_compile_definitions(native_tracking_test PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(native_tracking_test PRIVATE native_aimassist)

if(BUILD_TESTING)
    foreach(test_target IN ITEMS
        native_targeting_test
        native_movement_test
        native_input_test
        native_sigma_drift_test
        native_tracking_test
    )
        add_test(NAME ${test_target} COMMAND ${test_target})
    endforeach()
endif()

add_executable(native_engine
    src/engine_main.cpp
)
target_compile_features(native_engine PRIVATE cxx_std_20)
target_compile_definitions(native_engine PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(native_engine PRIVATE native_aimassist)

if(MSVC)
    foreach(target IN ITEMS
        native_engine_probe
        native_engine_core
        native_aimassist
        native_engine_infer_probe
        native_detect_image
        native_targeting_test
        native_movement_test
        native_input_test
        native_sigma_drift_test
        native_tracking_test
        native_engine
    )
        target_compile_options(${target} PRIVATE
            $<$<COMPILE_LANGUAGE:CXX>:/W4>
            $<$<COMPILE_LANGUAGE:CXX>:/permissive->
            $<$<COMPILE_LANGUAGE:CXX>:/EHsc>
        )
    endforeach()
endif()

foreach(executable IN ITEMS
    native_engine_probe
    native_engine_infer_probe
    native_detect_image
    native_targeting_test
    native_movement_test
    native_input_test
    native_sigma_drift_test
    native_tracking_test
    native_engine
)
    add_custom_command(TARGET ${executable} POST_BUILD
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${TENSORRT_RUNTIME_DLL}"
            "$<TARGET_FILE_DIR:${executable}>"
        VERBATIM
    )
endforeach()
