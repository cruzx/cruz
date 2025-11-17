import Foundation

struct SubtitleFileExporter {
    static func makeSRT(from segments: [SubtitleSegment]) -> String {
        segments.enumerated().map { index, segment in
            "\(index + 1)\n\(formatTime(segment.startTime)) --> \(formatTime(segment.endTime))\n\(segment.text)\n"
        }
        .joined(separator: "\n")
    }

    private static func formatTime(_ interval: TimeInterval) -> String {
        let hours = Int(interval) / 3600
        let minutes = (Int(interval) % 3600) / 60
        let seconds = Int(interval) % 60
        let milliseconds = Int((interval - floor(interval)) * 1000)
        return String(format: "%02d:%02d:%02d,%03d", hours, minutes, seconds, milliseconds)
    }
}
