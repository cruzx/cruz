import Foundation

struct TranslationService {
    private let converter = ChineseConverter()
    private let session: URLSession = {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 30
        configuration.waitsForConnectivity = true
        return URLSession(configuration: configuration)
    }()

    func translate(_ text: String, target: TranslationTarget, endpoint: String, token: String?) async throws -> String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return "" }

        if target == .traditionalChinese {
            return converter.convertToTraditional(trimmed)
        }

        guard let remoteCode = target.remoteLanguageCode else {
            return trimmed
        }

        guard var baseURL = URL(string: endpoint) else {
            throw SubtitleTranslatorError.invalidEndpoint
        }

        if baseURL.lastPathComponent != "translate" {
            baseURL.appendPathComponent("translate")
        }

        var request = URLRequest(url: baseURL)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token = token { request.setValue(token, forHTTPHeaderField: "Authorization") }

        let payload = TranslationPayload(
            q: trimmed,
            source: "zh",
            target: remoteCode,
            format: "text"
        )

        request.httpBody = try JSONEncoder().encode(payload)

        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse, (200..<300).contains(httpResponse.statusCode) else {
            throw URLError(.badServerResponse)
        }

        guard let translatedResponse = try? JSONDecoder().decode(TranslationResponse.self, from: data) else {
            throw SubtitleTranslatorError.emptyResponse
        }

        return translatedResponse.translatedText
    }
}

private struct TranslationPayload: Encodable {
    let q: String
    let source: String
    let target: String
    let format: String
}

private struct TranslationResponse: Decodable {
    let translatedText: String
}

final class ChineseConverter {
    func convertToTraditional(_ text: String) -> String {
        text.applyingTransform(.simplifiedToTraditional, reverse: false) ?? text
    }
}
