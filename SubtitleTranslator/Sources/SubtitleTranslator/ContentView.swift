import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var viewModel: SubtitleTranslatorViewModel
    @State private var showingFileImporter = false
    @FocusState private var textEditorIsFocused: Bool

    var body: some View {
        NavigationView {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    transcriptionSection
                    Divider()
                    translationSection
                }
                .padding()
            }
            .frame(minWidth: 700, minHeight: 640)
            .navigationTitle("字幕翻譯工具")
        }
        .navigationViewStyle(.automatic)
        .fileImporter(
            isPresented: $showingFileImporter,
            allowedContentTypes: viewModel.supportedAudioTypes
        ) { result in
            viewModel.handleFileSelection(result: result)
        }
        .alert(item: $viewModel.errorMessage) { message in
            Alert(title: Text("發生錯誤"), message: Text(message.value), dismissButton: .default(Text("好")))
        }
    }

    private var transcriptionSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("語音轉字幕", systemImage: "waveform")
                .font(.title2.bold())

            Text("選擇一個 .m4a、.mp3 或 .wav 檔案，我會使用 macOS 的語音識別服務將其轉成帶有時間軸的字幕。")
                .font(.callout)
                .foregroundColor(.secondary)

            HStack(spacing: 16) {
                Button(action: { showingFileImporter = true }) {
                    Label("選擇音訊檔", systemImage: "folder")
                }
                .buttonStyle(.borderedProminent)
                .disabled(viewModel.isTranscribing)

                Picker("語言", selection: $viewModel.selectedLocale) {
                    ForEach(viewModel.availableLocales, id: \.identifier) { locale in
                        Text(locale.localizedString(forIdentifier: locale.identifier) ?? locale.identifier)
                            .tag(locale)
                    }
                }
                .frame(maxWidth: 220)

                Spacer()

                if viewModel.isTranscribing {
                    ProgressView()
                        .progressViewStyle(.circular)
                        .controlSize(.small)
                }
            }

            if !viewModel.subtitleSegments.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text("預覽 (\(viewModel.subtitleSegments.count) 句)")
                            .font(.headline)
                        Spacer()
                        Button(action: viewModel.copySRTToClipboard) {
                            Label("複製 SRT", systemImage: "doc.on.doc")
                        }
                        Button(action: viewModel.exportSRTFile) {
                            Label("匯出檔案", systemImage: "square.and.arrow.down")
                        }
                    }

                    SubtitleTimelineView(segments: viewModel.subtitleSegments)
                        .frame(maxHeight: 260)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                        .overlay(
                            RoundedRectangle(cornerRadius: 8)
                                .stroke(Color.gray.opacity(0.3))
                        )
                }
            }
        }
    }

    private var translationSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("文字翻譯", systemImage: "character.book.closed")
                .font(.title2.bold())

            Text("輸入簡體中文，我可以轉換成繁體中文或翻譯成英文、日文。若你有自己的 API，也可以在下方設定。")
                .font(.callout)
                .foregroundColor(.secondary)

            VStack(alignment: .leading, spacing: 8) {
                Text("輸入文字")
                    .font(.subheadline)
                TextEditor(text: $viewModel.sourceText)
                    .focused($textEditorIsFocused)
                    .frame(minHeight: 160)
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(Color.gray.opacity(0.3))
                    )
            }

            HStack {
                Picker("目標語言", selection: $viewModel.selectedTranslationTarget) {
                    ForEach(TranslationTarget.allCases, id: \.self) { target in
                        Text(target.displayName).tag(target)
                    }
                }
                .pickerStyle(.segmented)

                Spacer()

                Button(action: viewModel.translateText) {
                    Label("開始翻譯", systemImage: "arrow.triangle.2.circlepath")
                }
                .disabled(viewModel.isTranslating || viewModel.sourceText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                if viewModel.isTranslating {
                    ProgressView()
                        .controlSize(.small)
                }
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("結果")
                    .font(.subheadline)
                ResultView(result: viewModel.translationResult)
                    .frame(minHeight: 120)
            }

            DisclosureGroup("進階設定") {
                VStack(alignment: .leading, spacing: 8) {
                    TextField("翻譯 API 位址 (例如 https://libretranslate.com)", text: $viewModel.translationEndpoint)
                    SecureField("API Token (可選)", text: $viewModel.translationAPIToken)
                    Text("預設會使用公開的 LibreTranslate 服務，建議在正式工作時改用自架或付費服務以避免流量限制。")
                        .font(.footnote)
                        .foregroundColor(.secondary)
                }
            }
        }
    }
}

struct SubtitleTimelineView: View {
    let segments: [SubtitleSegment]

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                ForEach(segments) { segment in
                    VStack(alignment: .leading, spacing: 4) {
                        Text("\(segment.displayIndex). \(segment.displayTimeRange)")
                            .font(.caption)
                            .foregroundColor(.secondary)
                        Text(segment.text)
                            .font(.body)
                            .padding(.bottom, 8)
                    }
                    .padding(.horizontal)
                    Divider()
                }
            }
        }
    }
}

struct ResultView: View {
    let result: TranslationResult

    var body: some View {
        ZStack(alignment: .topLeading) {
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color.gray.opacity(0.3))
            Text(result.text.isEmpty ? "翻譯結果將顯示在這裡" : result.text)
                .padding()
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
