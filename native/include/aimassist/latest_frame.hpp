#pragma once

// Single-slot "latest frame" handoff between a producer (capture) and a consumer
// (inference), holding CUDA device memory.
//
// This is the drop-old-frames model used by the reference capture/detector
// split: the producer overwrites the slot rather than appending to a queue, so
// if the consumer falls behind it always works on the freshest frame instead of
// draining a backlog. For an aim assistant that matters more than raw
// throughput: a stale queued frame produces a stale aim correction.
//
// Double buffering lets the producer fill the spare device buffer while the
// consumer reads the published one. All copies between the two are device-to-
// device, so the frame never visits system memory.

#include <cstdint>
#include <mutex>

#include <cuda_runtime_api.h>

namespace aimassist
{
    class LatestFrameSlot
    {
    public:
        ~LatestFrameSlot()
        {
            release();
        }

        LatestFrameSlot() = default;
        LatestFrameSlot(LatestFrameSlot const &) = delete;
        LatestFrameSlot &operator=(LatestFrameSlot const &) = delete;

        // Allocate or grow both device buffers to `bytes` each.
        bool reserve(std::size_t bytes)
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (capacity_ >= bytes && buffers_[0] != nullptr && buffers_[1] != nullptr)
            {
                return true;
            }
            release_locked();
            if (cudaMalloc(&buffers_[0], bytes) != cudaSuccess)
            {
                buffers_[0] = nullptr;
                return false;
            }
            if (cudaMalloc(&buffers_[1], bytes) != cudaSuccess)
            {
                cudaFree(buffers_[0]);
                buffers_[0] = nullptr;
                return false;
            }
            capacity_ = bytes;
            return true;
        }

        std::size_t capacity() const
        {
            std::lock_guard<std::mutex> lock(mutex_);
            return capacity_;
        }

        // Device buffer the producer writes into (not the published one).
        std::uint8_t *write_buffer()
        {
            std::lock_guard<std::mutex> lock(mutex_);
            return static_cast<std::uint8_t *>(buffers_[write_index_]);
        }

        // Publish the write buffer as newest and swap roles.
        void publish(std::size_t bytes)
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (buffers_[write_index_] == nullptr)
            {
                return;
            }
            published_index_ = write_index_;
            published_bytes_ = bytes;
            write_index_ = 1 - write_index_;
            ++version_;
        }

        // Copy the newest published frame into `destination` (device memory).
        bool copy_latest_into(void *destination, std::size_t bytes, cudaStream_t stream = nullptr)
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (published_bytes_ == 0 || version_ == 0 || destination == nullptr)
            {
                return false;
            }
            auto const copy_bytes = bytes < published_bytes_ ? bytes : published_bytes_;
            auto const status = cudaMemcpyAsync(
                destination,
                buffers_[published_index_],
                copy_bytes,
                cudaMemcpyDeviceToDevice,
                stream);
            if (status != cudaSuccess)
            {
                return false;
            }
            last_consumed_version_ = version_;
            return true;
        }

        std::uint64_t version() const
        {
            std::lock_guard<std::mutex> lock(mutex_);
            return version_;
        }

        bool has_frame() const
        {
            std::lock_guard<std::mutex> lock(mutex_);
            return version_ != 0 && published_bytes_ != 0;
        }

        // A frame was published since the last copy_latest_into().
        bool has_newer() const
        {
            std::lock_guard<std::mutex> lock(mutex_);
            return version_ != 0 && version_ != last_consumed_version_;
        }

        void release()
        {
            std::lock_guard<std::mutex> lock(mutex_);
            release_locked();
        }

    private:
        void release_locked()
        {
            for (auto &buffer : buffers_)
            {
                if (buffer != nullptr)
                {
                    cudaFree(buffer);
                    buffer = nullptr;
                }
            }
            capacity_ = 0;
            published_bytes_ = 0;
            version_ = 0;
            last_consumed_version_ = 0;
            write_index_ = 0;
            published_index_ = 0;
        }

        mutable std::mutex mutex_;
        void *buffers_[2]{};
        std::size_t capacity_{};
        int write_index_{0};
        int published_index_{0};
        std::size_t published_bytes_{};
        std::uint64_t version_{};
        std::uint64_t last_consumed_version_{};
    };
} // namespace aimassist
