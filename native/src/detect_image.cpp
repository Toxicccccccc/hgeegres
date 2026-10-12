// Offline detection harness.
//
// Runs a single image through the exact preprocessing, TensorRT inference, and
// decoding path used by the live engine, then reports every detection and
// optionally writes an annotated copy. Because it needs no capture, no serial
// port, and no running game, it is the fastest way to check detection quality
// and to catch preprocessing defects (channel order, resize math, box scaling)
// that a live run would hide.
//
// Usage:
//   native_detect_image <model.engine> <image.ppm> [confidence 0-1] [--annotate out.ppm]
//
// The image must be a binary PPM (P6). Convert with the helper script in
// tools/ if needed; PPM keeps this tool free of any image-codec dependency.

#include "aimassist/tensorrt_yolo.hpp"

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <exception>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace
{
    struct Image
    {
        int width{};
        int height{};
        std::vector<std::uint8_t> rgb; // tightly packed, 3 bytes per pixel
    };

    // Minimal binary PPM (P6) reader: "P6 <w> <h> 255" followed by RGB bytes.
    bool load_ppm(std::string const &path, Image &image, std::string &error)
    {
        std::ifstream file(path, std::ios::binary);
        if (!file)
        {
            error = "Cannot open image: " + path;
            return false;
        }

        std::string magic;
        int width = 0;
        int height = 0;
        int max_value = 0;
        file >> magic >> width >> height >> max_value;
        if (magic != "P6" || width <= 0 || height <= 0 || max_value != 255)
        {
            error = "Expected a binary PPM (P6) with 8-bit channels.";
            return false;
        }
        file.get(); // consume the single whitespace byte after the header

        auto const bytes = static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * 3;
        image.rgb.resize(bytes);
        file.read(reinterpret_cast<char *>(image.rgb.data()), static_cast<std::streamsize>(bytes));
        if (!file)
        {
            error = "Image data is truncated.";
            return false;
        }
        image.width = width;
        image.height = height;
        return true;
    }

    // The engine's preprocessing expects BGRA, matching the desktop capture format.
    std::vector<std::uint8_t> to_bgra(Image const &image)
    {
        std::vector<std::uint8_t> bgra(
            static_cast<std::size_t>(image.width) * static_cast<std::size_t>(image.height) * 4);
        for (std::size_t pixel = 0; pixel < static_cast<std::size_t>(image.width) * image.height; ++pixel)
        {
            bgra[pixel * 4 + 0] = image.rgb[pixel * 3 + 2]; // B
            bgra[pixel * 4 + 1] = image.rgb[pixel * 3 + 1]; // G
            bgra[pixel * 4 + 2] = image.rgb[pixel * 3 + 0]; // R
            bgra[pixel * 4 + 3] = 255;                      // A
        }
        return bgra;
    }

    bool save_ppm(std::string const &path, Image const &image, std::string &error)
    {
        std::ofstream file(path, std::ios::binary);
        if (!file)
        {
            error = "Cannot write image: " + path;
            return false;
        }
        file << "P6\n"
             << image.width << ' ' << image.height << "\n255\n";
        file.write(
            reinterpret_cast<char const *>(image.rgb.data()),
            static_cast<std::streamsize>(image.rgb.size()));
        return static_cast<bool>(file);
    }

    void draw_box(Image &image, float x1, float y1, float x2, float y2, int thickness)
    {
        auto const clamp_x = [&](float value)
        {
            return std::clamp(static_cast<int>(value), 0, image.width - 1);
        };
        auto const clamp_y = [&](float value)
        {
            return std::clamp(static_cast<int>(value), 0, image.height - 1);
        };
        auto const left = clamp_x(x1);
        auto const right = clamp_x(x2);
        auto const top = clamp_y(y1);
        auto const bottom = clamp_y(y2);

        auto const plot = [&](int x, int y, std::uint8_t r, std::uint8_t g, std::uint8_t b)
        {
            if (x < 0 || y < 0 || x >= image.width || y >= image.height)
            {
                return;
            }
            auto const index = (static_cast<std::size_t>(y) * image.width + x) * 3;
            image.rgb[index + 0] = r;
            image.rgb[index + 1] = g;
            image.rgb[index + 2] = b;
        };

        for (int t = 0; t < thickness; ++t)
        {
            for (int x = left; x <= right; ++x)
            {
                plot(x, top + t, 255, 40, 40);
                plot(x, bottom - t, 255, 40, 40);
            }
            for (int y = top; y <= bottom; ++y)
            {
                plot(left + t, y, 255, 40, 40);
                plot(right - t, y, 255, 40, 40);
            }
        }
    }
} // namespace

int main(int argc, char **argv)
{
    try
    {
        if (argc < 3)
        {
            std::cerr << "Usage: native_detect_image <model.engine> <image.ppm> "
                         "[confidence 0-1] [--annotate out.ppm]\n";
            return 2;
        }

        auto const model_path = std::string(argv[1]);
        auto const image_path = std::string(argv[2]);
        auto confidence = 0.25F;
        std::string annotate_path;
        for (int index = 3; index < argc; ++index)
        {
            auto const argument = std::string(argv[index]);
            if (argument == "--annotate" && index + 1 < argc)
            {
                annotate_path = argv[++index];
            }
            else
            {
                confidence = std::stof(argument);
            }
        }

        Image image;
        std::string error;
        if (!load_ppm(image_path, image, error))
        {
            std::cerr << error << '\n';
            return 1;
        }
        std::cout << "Image: " << image_path << " (" << image.width << 'x' << image.height << ")\n";

        auto const bgra = to_bgra(image);
        aimassist::TensorRtYolo model(model_path);
        std::cout << "Model: " << model_path << " input=" << model.input_width() << 'x'
                  << model.input_height() << " classes=" << model.class_count() << '\n';

        auto const result = model.infer(
            bgra.data(),
            image.width,
            image.height,
            confidence,
            0.7F,
            100);

        std::cout << "Output layout: classes=" << model.decoded_class_count()
                  << " objectness=" << (model.output_uses_objectness() ? "yes" : "no")
                  << " xyxy=" << (model.output_is_xyxy() ? "yes" : "no") << '\n';
        std::cout << "Timings: preprocess=" << result.timings.upload_preprocess_ms
                  << "ms predict=" << result.timings.predict_ms
                  << "ms copy=" << result.timings.result_copy_ms << "ms\n";
        std::cout << "Detections above " << confidence << ": " << result.detections.size() << '\n';

        for (auto const &detection : result.detections)
        {
            std::printf(
                "  class=%d conf=%.3f box=[%.1f, %.1f, %.1f, %.1f] size=%.1fx%.1f\n",
                detection.class_id,
                static_cast<double>(detection.confidence),
                static_cast<double>(detection.x1),
                static_cast<double>(detection.y1),
                static_cast<double>(detection.x2),
                static_cast<double>(detection.y2),
                static_cast<double>(detection.x2 - detection.x1),
                static_cast<double>(detection.y2 - detection.y1));
        }

        if (!annotate_path.empty())
        {
            for (auto const &detection : result.detections)
            {
                draw_box(image, detection.x1, detection.y1, detection.x2, detection.y2, 3);
            }
            if (!save_ppm(annotate_path, image, error))
            {
                std::cerr << error << '\n';
                return 1;
            }
            std::cout << "Annotated image written: " << annotate_path << '\n';
        }
        return 0;
    }
    catch (std::exception const &error)
    {
        std::cerr << "Detection failed: " << error.what() << '\n';
        return 1;
    }
}
