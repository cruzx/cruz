import Foundation
import Speech

struct AudioTranscriptionService {
    func transcribeAudio(at url: URL, locale: Locale) async throws -> [SubtitleSegment] {
        try await requestAuthorization()

        let recognizerLocale = Locale(identifier: locale.identifier)
        guard let recognizer = SFSpeechRecognizer(locale: recognizerLocale) else {
            throw SubtitleTranslatorError.unsupportedLocale
        }

        let request = SFSpeechURLRecognitionRequest(url: url)
        request.shouldReportPartialResults = false
        request.taskHint = .dictation

        let result = try await withCheckedThrowingContinuation { continuation in
            recognizer.recognitionTask(with: request) { transcriptionResult, error in
                if let error = error {
                    continuation.resume(throwing: error)
                    return
                }

                if let transcriptionResult = transcriptionResult, transcriptionResult.isFinal {
                    continuation.resume(returning: transcriptionResult)
                }
            }
        }

        let segments = SubtitleSegment.make(from: result.bestTranscription.segments)
        return segments
    }

    private func requestAuthorization() async throws {
        try await withCheckedThrowingContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                switch status {
                case .authorized:
                    continuation.resume()
                case .denied:
                    continuation.resume(throwing: SubtitleTranslatorError.permissionDenied)
                case .restricted, .notDetermined:
                    continuation.resume(throwing: SubtitleTranslatorError.permissionRestricted)
                @unknown default:
                    continuation.resume(throwing: SubtitleTranslatorError.permissionRestricted)
                }
            }
        }
    }
}

enum SubtitleTranslatorError: LocalizedError {
    case unsupportedLocale
    case permissionDenied
    case permissionRestricted
    case invalidEndpoint
    case emptyResponse

    var errorDescription: String? {
        switch self {
        case .unsupportedLocale:
            return "目前尚未支援該語言的語音辨識。"
        case .permissionDenied:
            return "請在系統偏好設定 > 安全性與隱私 > 語音識別允許本程式使用。"
        case .permissionRestricted:
            return "無法取得語音識別權限，請稍後再試。"
        case .invalidEndpoint:
            return "翻譯服務位址無效，請重新確認。"
        case .emptyResponse:
            return "翻譯服務沒有回傳結果。"
        }
    }
}
