#pragma once

// Dataset collector for retraining the detector.
//
// While the engine runs, this optionally saves captured frames together with
// the detections the model produced. The result is a labelled dataset in the
// YOLO text format, which can be used to fine-tune the model.
//
// Two modes are supported:
//   * save_frames = true  -> writes the image and a matching .txt label file.
//     This builds a fresh dataset but costs disk bandwidth and I/O time on the
//     capture thread.
//   * save_frames = false -> writes only the label rows and a manifest, so the
//     run can be reviewed for quality without storing screenshots.
//
// Design notes:
//   * This does NOT train anything at runtime. Real training needs a separate
//     pass with a training framework; doing it inside the real-time loop would
//     wreck the frame budget. The collector produces the missing ingredient:
//     accurately labelled data from actual play.
//   * Disk work happens on a background thread through a bounded queue, so a
//     slow disk can never stall capture or inference. Frames are dropped rather
//     than queued without limit.
//   * Only the FOV crop is stored, never the full desktop, and nothing is
//     uploaded anywhere.

#include "aimassist/detection.hpp"

#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <fstream>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace aimassist
{
    struct DatasetSettings
    {
        bool enabled{false};
        // When false, only label rows and a manifest are written (no images).
        bool save_frames{true};
        // Minimum confidence for a detection to be written as a training label.
        // Labels are ground truth, so a higher bar keeps noise out of the dataset.
        float min_confidence{0.55F};
        // Maximum frames stored per second, to bound disk use during long sessions.
        int max_frames_per_second{5};
        std::string output_dir{"dataset"};
        std::string class_names;
    };

    class DatasetCollector
    {
    public:
        DatasetCollector();
        ~DatasetCollector();

        DatasetCollector(DatasetCollector const &) = delete;
        DatasetCollector &operator=(DatasetCollector const &) = delete;

        // Prepare the output directory and start the writer thread. Returns false
        // with a reason when the directory cannot be created.
        bool start(DatasetSettings const &settings, std::string &message);

        bool active() const noexcept;

        // Offer one frame and its detections. Cheap and non-blocking: it only
        // enqueues a bounded job and returns. `bgra` is FOV x FOV x 4.
        void submit(
            std::uint8_t const *bgra,
            int fov,
            std::vector<Detection> const &detections,
            std::uint64_t sequence);

        // Frame and label counts actually written, for the GUI.
        std::uint64_t frames_written() const noexcept;
        std::uint64_t labels_written() const noexcept;
        std::uint64_t frames_dropped() const noexcept;

        void stop();

    private:
        struct Job
        {
            std::vector<std::uint8_t> pixels;
            std::vector<Detection> detections;
            int fov{};
            std::uint64_t sequence{};
        };

        void writer_loop();
        bool write_job(Job const &job);

        DatasetSettings settings_;
        std::string image_dir_;
        std::string label_dir_;

        mutable std::mutex mutex_;
        std::condition_variable cv_;
        std::deque<Job> queue_;
        std::thread writer_;
        bool stopping_{};

        std::ofstream manifest_;
        std::ofstream labels_csv_;

        std::atomic<std::uint64_t> frames_written_{};
        std::atomic<std::uint64_t> labels_written_{};
        std::atomic<std::uint64_t> frames_dropped_{};
        std::atomic<bool> active_{false};

        // Rate limiting, so a long session cannot fill the disk.
        double last_saved_at_{};
        double last_saved_second_{};
        int saved_this_second_{};
    };
} // namespace aimassist
