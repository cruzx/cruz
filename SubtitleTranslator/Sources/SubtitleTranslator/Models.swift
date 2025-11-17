import Foundation
import Speech

struct SubtitleSegment: Identifiable {
    let id = UUID()
    let index: Int
    let startTime: TimeInterval
    let endTime: TimeInterval
    let text: String

    var displayIndex: Int { index + 1 }

    var displayTimeRange: String {
        "\(Self.timeFormatter.string(from: startTime)) --> \(Self.timeFormatter.string(from: endTime))"
    }

    private static let timeFormatter: DateComponentsFormatter = {
        let formatter = DateComponentsFormatter()
        formatter.allowedUnits = [.minute, .second]
        formatter.zeroFormattingBehavior = [.pad]
        formatter.unitsStyle = .positional
        formatter.includesTimeRemainingPhrase = false
        return formatter
    }()
}

struct TranslationResult {
    let text: String
    let target: TranslationTarget

    static let empty = TranslationResult(text: "", target: .traditionalChinese)
}

enum TranslationTarget: CaseIterable {
    case traditionalChinese
    case english
    case japanese

    var displayName: String {
        switch self {
        case .traditionalChinese: return "繁體中文"
        case .english: return "英文"
        case .japanese: return "日文"
        }
    }

    var remoteLanguageCode: String? {
        switch self {
        case .traditionalChinese:
            return nil
        case .english:
            return "en"
        case .japanese:
            return "ja"
        }
    }
}

extension SubtitleSegment {
    static func make(from segments: [SFTranscriptionSegment]) -> [SubtitleSegment] {
        segments.enumerated().map { index, segment in
            SubtitleSegment(
                index: index,
                startTime: segment.timestamp,
                endTime: segment.timestamp + segment.duration,
                text: segment.substring
            )
        }
    }
}
