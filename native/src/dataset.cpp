#include "aimassist/dataset.hpp"

#include <algorithm>
#include <chrono>
#include <filesystem>
#include <iomanip>
#include <sstream>
#include <system_error>

namespace
{
    double now_seconds()
    {
        using clock = std::chrono::steady_clock;
        return std::chrono::duration<double>(clock::now().time_since_epoch()).count();
    }

    // A binary PPM keeps the writer dependency-free: it is a few header bytes plus
    // the raw pixels, and every training framework can read it.
    bool write_ppm(std::string const &path, std::uint8_t const *bgra, int fov)
    {
        std::ofstream file(path, std::ios::binary);
        if (!file)
        {
            return false;
        }
        file << "P6\n"
             << fov << ' ' << fov << "\n255\n";

        // Convert BGRA to the RGB byte order PPM expects, one row at a time.
        std::vector<std::uint8_t> row(static_cast<std::size_t>(fov) * 3);
        for (int y = 0; y < fov; ++y)
        {
            auto const *source = bgra + static_cast<std::size_t>(y) * fov * 4;
            for (int x = 0; x < fov; ++x)
            {
                row[static_cast<std::size_t>(x) * 3 + 0] = source[static_cast<std::size_t>(x) * 4 + 2];
                row[static_cast<std::size_t>(x) * 3 + 1] = source[static_cast<std::size_t>(x) * 4 + 1];
                row[static_cast<std::size_t>(x) * 3 + 2] = source[static_cast<std::size_t>(x) * 4 + 0];
            }
            file.write(reinterpret_cast<char const *>(row.data()), static_cast<std::streamsize>(row.size()));
        }
        return static_cast<bool>(file);
    }

    // YOLO label format: "class cx cy w h", normalised to 0..1.
    std::string label_line(aimassist::Detection const &detection, int fov)
    {
        auto const clamp01 = [](float value)
        {
            return std::clamp(value, 0.0F, 1.0F);
        };
        auto const cx = clamp01(((detection.x1 + detection.x2) * 0.5F) / static_cast<float>(fov));
        auto const cy = clamp01(((detection.y1 + detection.y2) * 0.5F) / static_cast<float>(fov));
        auto const w = clamp01((detection.x2 - detection.x1) / static_cast<float>(fov));
        auto const h = clamp01((detection.y2 - detection.y1) / static_cast<float>(fov));

        std::ostringstream stream;
        stream << detection.class_id << ' '
               << std::fixed << std::setprecision(6)
               << cx << ' ' << cy << ' ' << w << ' ' << h << '\n';
        return stream.str();
    }
} // namespace

namespace aimassist
{
    DatasetCollector::DatasetCollector() = default;

    DatasetCollector::~DatasetCollector()
    {
        stop();
    }

    bool DatasetCollector::start(DatasetSettings const &settings, std::string &message)
    {
        if (active_.load())
        {
            message = "Dataset collection is already running";
            return true;
        }

        settings_ = settings;
        settings_.min_confidence = std::clamp(settings_.min_confidence, 0.0F, 1.0F);
        if (settings_.max_frames_per_second <= 0)
        {
            settings_.max_frames_per_second = 1;
        }

        std::error_code error;
        auto const root = std::filesystem::path(settings_.output_dir);
        std::filesystem::create_directories(root, error);
        if (error)
        {
            message = "Could not create the dataset folder: " + error.message();
            return false;
        }

        if (settings_.save_frames)
        {
            image_dir_ = (root / "images").string();
            label_dir_ = (root / "labels").string();
            std::filesystem::create_directories(image_dir_, error);
            if (error)
            {
                message = "Could not create the dataset image folder: " + error.message();
                return false;
            }
            std::filesystem::create_directories(label_dir_, error);
            if (error)
            {
                message = "Could not create the dataset label folder: " + error.message();
                return false;
            }
        }

        manifest_.open((root / "manifest.csv").string(), std::ios::out | std::ios::app);
        if (!manifest_)
        {
            message = "Could not open the dataset manifest for writing";
            return false;
        }
        // Record the class names so a future training run knows the label mapping.
        manifest_ << "# class_names=" << settings_.class_names << '\n';
        manifest_ << "# save_frames=" << (settings_.save_frames ? "true" : "false") << '\n';
        manifest_ << "sequence,image,label,detections\n";

        labels_csv_.open((root / "labels.csv").string(), std::ios::out | std::ios::app);
        if (!labels_csv_)
        {
            message = "Could not open the dataset label index for writing";
            return false;
        }
        labels_csv_ << "sequence,class_id,confidence,x1,y1,x2,y2\n";

        {
            std::lock_guard<std::mutex> lock(mutex_);
            queue_.clear();
            stopping_ = false;
        }
        frames_written_ = 0;
        labels_written_ = 0;
        frames_dropped_ = 0;
        writer_ = std::thread(&DatasetCollector::writer_loop, this);
        active_ = true;

        message = "Dataset collection active in " + settings_.output_dir + (settings_.save_frames ? " (frames + labels)" : " (labels only)");
        return true;
    }

    bool DatasetCollector::active() const noexcept
    {
        return active_.load();
    }

    void DatasetCollector::submit(
        std::uint8_t const *bgra,
        int fov,
        std::vector<Detection> const &detections,
        std::uint64_t sequence)
    {
        if (!active_.load() || fov <= 0)
        {
            return;
        }

        // Only keep detections that are confident enough to be trusted as labels.
        std::vector<Detection> accepted;
        accepted.reserve(detections.size());
        for (auto const &detection : detections)
        {
            if (detection.confidence >= settings_.min_confidence)
            {
                accepted.push_back(detection);
            }
        }

        // Rate limit so a long play session cannot saturate the disk. Time-based
        // limiting keeps the cost predictable regardless of frame rate.
        auto const now = now_seconds();
        auto const current_second = std::floor(now);
        if (current_second != last_saved_second_)
        {
            last_saved_second_ = current_second;
            saved_this_second_ = 0;
        }
        if (saved_this_second_ >= settings_.max_frames_per_second)
        {
            return;
        }
        ++saved_this_second_;
        last_saved_at_ = now;

        Job job;
        job.detections = std::move(accepted);
        job.fov = fov;
        job.sequence = sequence;
        if (settings_.save_frames && bgra != nullptr)
        {
            auto const bytes = static_cast<std::size_t>(fov) * static_cast<std::size_t>(fov) * 4;
            job.pixels.assign(bgra, bgra + bytes);
        }

        std::lock_guard<std::mutex> lock(mutex_);
        constexpr std::size_t max_pending = 32;
        if (queue_.size() >= max_pending)
        {
            // Drop the oldest job: recent frames matter more than a backlog, and
            // this bounds memory during a slow-disk episode.
            queue_.pop_front();
            frames_dropped_.fetch_add(1);
        }
        queue_.push_back(std::move(job));
        cv_.notify_one();
    }

    void DatasetCollector::writer_loop()
    {
        while (true)
        {
            Job job;
            {
                std::unique_lock<std::mutex> lock(mutex_);
                cv_.wait(lock, [this]
                         { return stopping_ || !queue_.empty(); });
                if (stopping_ && queue_.empty())
                {
                    break;
                }
                job = std::move(queue_.front());
                queue_.pop_front();
            }

            try
            {
                write_job(job);
            }
            catch (...)
            {
                // A failed write must never take down the engine; the frame is
                // simply counted as dropped.
                frames_dropped_.fetch_add(1);
            }
        }
    }

    bool DatasetCollector::write_job(Job const &job)
    {
        std::ostringstream name;
        name << std::setw(8) << std::setfill('0') << job.sequence;
        auto const stem = name.str();

        std::string image_path;
        std::string label_path;
        if (settings_.save_frames)
        {
            image_path = image_dir_ + "\\" + stem + ".ppm";
            label_path = label_dir_ + "\\" + stem + ".txt";
            if (!job.pixels.empty())
            {
                if (!write_ppm(image_path, job.pixels.data(), job.fov))
                {
                    frames_dropped_.fetch_add(1);
                    return false;
                }
            }
            std::ofstream label_file(label_path, std::ios::out | std::ios::trunc);
            if (label_file)
            {
                for (auto const &detection : job.detections)
                {
                    label_file << label_line(detection, job.fov);
                }
            }
            frames_written_.fetch_add(1);
        }
        else
        {
            frames_written_.fetch_add(1);
        }

        for (auto const &detection : job.detections)
        {
            labels_written_.fetch_add(1);
            if (labels_csv_)
            {
                labels_csv_ << job.sequence << ',' << detection.class_id << ','
                            << std::fixed << std::setprecision(4) << detection.confidence << ','
                            << detection.x1 << ',' << detection.y1 << ','
                            << detection.x2 << ',' << detection.y2 << '\n';
            }
        }

        if (manifest_)
        {
            manifest_ << job.sequence << ','
                      << (image_path.empty() ? "-" : image_path) << ','
                      << (label_path.empty() ? "-" : label_path) << ','
                      << job.detections.size() << '\n';
        }
        return true;
    }

    std::uint64_t DatasetCollector::frames_written() const noexcept
    {
        return frames_written_.load();
    }

    std::uint64_t DatasetCollector::labels_written() const noexcept
    {
        return labels_written_.load();
    }

    std::uint64_t DatasetCollector::frames_dropped() const noexcept
    {
        return frames_dropped_.load();
    }

    void DatasetCollector::stop()
    {
        if (!active_.load())
        {
            return;
        }
        {
            std::lock_guard<std::mutex> lock(mutex_);
            stopping_ = true;
        }
        cv_.notify_all();
        if (writer_.joinable())
        {
            writer_.join();
        }
        if (manifest_)
        {
            manifest_.flush();
            manifest_.close();
        }
        if (labels_csv_)
        {
            labels_csv_.flush();
            labels_csv_.close();
        }
        active_ = false;
    }
} // namespace aimassist
