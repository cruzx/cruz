import SwiftUI
import UniformTypeIdentifiers
import AppKit

@MainActor
final class SubtitleTranslatorViewModel: ObservableObject {
    @Published var sourceText: String = ""
    @Published var translationResult: TranslationResult = .empty
    @Published var selectedTranslationTarget: TranslationTarget = .traditionalChinese
    @Published var translationEndpoint: String = "https://libretranslate.com"
    @Published var translationAPIToken: String = ""

    @Published var isTranscribing = false
    @Published var subtitleSegments: [SubtitleSegment] = []
    @Published var selectedLocale: Locale = Locale(identifier: "zh-CN")

    @Published var isTranslating = false

    @Published var errorMessage: IdentifiableString?

    let supportedAudioTypes: [UTType] = [
        .m4a, .mp3, .wav
    ].compactMap { $0 }

    let availableLocales: [Locale] = [
        Locale(identifier: "zh-CN"),
        Locale(identifier: "zh-TW"),
        Locale(identifier: "en-US"),
        Locale(identifier: "ja-JP"),
        Locale(identifier: "yue-Hant-HK")
    ]

    private let transcriptionService = AudioTranscriptionService()
    private let translationService = TranslationService()

    func handleFileSelection(result: Result<URL, Error>) {
        switch result {
        case .success(let url):
            Task {
                await transcribe(url: url)
            }
        case .failure(let error):
            errorMessage = IdentifiableString(error.localizedDescription)
        }
    }

    func transcribe(url: URL) async {
        isTranscribing = true
        defer { isTranscribing = false }

        do {
            subtitleSegments = try await transcriptionService.transcribeAudio(at: url, locale: selectedLocale)
        } catch {
            errorMessage = IdentifiableString(error.localizedDescription)
        }
    }

    func translateText() {
        guard !sourceText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }

        Task {
            await performTranslation()
        }
    }

    private func performTranslation() async {
        isTranslating = true
        defer { isTranslating = false }

        do {
            let result = try await translationService.translate(
                sourceText,
                target: selectedTranslationTarget,
                endpoint: translationEndpoint,
                token: translationAPIToken.isEmpty ? nil : translationAPIToken
            )
            translationResult = TranslationResult(text: result, target: selectedTranslationTarget)
        } catch {
            errorMessage = IdentifiableString(error.localizedDescription)
        }
    }

    func copySRTToClipboard() {
        let srtText = SubtitleFileExporter.makeSRT(from: subtitleSegments)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(srtText, forType: .string)
    }

    func exportSRTFile() {
        let savePanel = NSSavePanel()
        savePanel.allowedContentTypes = [.init(filenameExtension: "srt")!]
        savePanel.nameFieldStringValue = "subtitle.srt"
        savePanel.canCreateDirectories = true
        savePanel.begin { response in
            guard response == .OK, let url = savePanel.url else { return }
            do {
                let srtText = SubtitleFileExporter.makeSRT(from: self.subtitleSegments)
                try srtText.data(using: .utf8)?.write(to: url)
            } catch {
                self.errorMessage = IdentifiableString(error.localizedDescription)
            }
        }
    }
}

struct IdentifiableString: Identifiable {
    let id = UUID()
    let value: String

    init(_ value: String) {
        self.value = value
    }
}
