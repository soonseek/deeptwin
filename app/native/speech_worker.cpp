// App-owned persistent worker: bounded PCM frames in, bounded UTF-8 JSON out.
// No microphone, HTTP listener, file outputs, or remote inference path.
#include <whisper.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

static void silent_log(enum ggml_log_level, const char *, void *) {}

static std::string json_string(const std::string &text) {
    std::string out = "\"";
    constexpr char hex[] = "0123456789abcdef";
    for (unsigned char ch : text) {
        if (ch == '"' || ch == '\\') { out += '\\'; out += ch; }
        else if (ch < 32) { out += "\\u00"; out += hex[ch >> 4]; out += hex[ch & 15]; }
        else out += ch;
    }
    return out + '"';
}

static bool reply(const std::string &text) {
    if (text.empty() || text.size() > 65536) return false;
    uint32_t size = static_cast<uint32_t>(text.size());
    unsigned char header[] = {static_cast<unsigned char>(size), static_cast<unsigned char>(size >> 8),
                              static_cast<unsigned char>(size >> 16), static_cast<unsigned char>(size >> 24)};
    return fwrite(header, 1, 4, stdout) == 4 && fwrite(text.data(), 1, size, stdout) == size && fflush(stdout) == 0;
}

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    whisper_log_set(silent_log, nullptr);
    auto context_params = whisper_context_default_params();
    // CPU/Accelerate is the initial bounded target; no runtime shader/compiler or CoreML download.
    context_params.use_gpu = false;
    whisper_context *context = whisper_init_from_file_with_params(argv[1], context_params);
    if (!context) return 3;
    if (!reply("{\"ready\":true,\"version\":" + json_string(whisper_version()) + "}")) {
        whisper_free(context); return 4;
    }
    auto params = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    params.n_threads = 4;
    params.language = "ko";
    params.translate = false;
    params.no_context = true;
    params.print_realtime = false;
    params.print_progress = false;
    params.print_timestamps = false;
    params.print_special = false;
    params.temperature_inc = 0.0f;
    int status = 0;
    while (true) {
        unsigned char header[4];
        size_t got = fread(header, 1, 4, stdin);
        if (got == 0 && feof(stdin)) break;
        if (got != 4) { status = 5; break; }
        uint32_t size = uint32_t(header[0]) | (uint32_t(header[1]) << 8) |
                        (uint32_t(header[2]) << 16) | (uint32_t(header[3]) << 24);
        if (size < 8000 || size > 256000 || size % 2) { status = 5; break; }
        std::vector<unsigned char> pcm(size);
        if (fread(pcm.data(), 1, size, stdin) != size) { status = 5; break; }
        std::vector<float> samples(size / 2);
        for (size_t i = 0; i < samples.size(); ++i) {
            uint16_t raw = uint16_t(pcm[i * 2]) | (uint16_t(pcm[i * 2 + 1]) << 8);
            samples[i] = static_cast<int16_t>(raw) / 32768.0f;
        }
        if (whisper_full(context, params, samples.data(), static_cast<int>(samples.size())) != 0) {
            status = 6; break;
        }
        std::string text;
        for (int i = 0; i < whisper_full_n_segments(context); ++i) {
            text += whisper_full_get_segment_text(context, i);
            if (text.size() > 16000) { status = 6; break; }
        }
        if (status || !reply("{\"text\":" + json_string(text) + "}")) { status = 6; break; }
    }
    whisper_free(context);
    return status;
}
