# SubtitleTranslator for macOS

這個專案提供一個以 SwiftUI 寫成的 macOS 應用程式，可以：

1. 匯入 `.m4a`、`.mp3`、`.wav` 等音訊檔並利用 `SFSpeechRecognizer` 轉成帶時間軸的字幕。
2. 將簡體中文轉為繁體中文，或透過可自訂的 LibreTranslate API 將文字翻譯成英文、日文。
3. 預覽、複製或匯出標準 SRT 字幕檔。

## 開始使用

1. 在 macOS 上安裝 Xcode 14+。
2. `cd SubtitleTranslator` 後執行 `swift package generate-xcodeproj` 或直接在 Xcode 以「開啟封裝」載入。
3. 在 `SubtitleTranslatorApp` 目標的 `Info.plist` 中新增：
   - `NSSpeechRecognitionUsageDescription`：描述為何需要語音辨識權限。
4. 執行 App 後即可選擇音訊檔或輸入文字。

若你要使用自己的翻譯服務，請在 App 的「進階設定」輸入 API 位址（例如 `https://yourdomain.com/translate`）和 Token。

## 測試

```bash
cd SubtitleTranslator
swift test
```

## 部署建議

* 若需要更準確的字幕，可考慮在本地安裝 Whisper 等模型，再把輸出結果貼到翻譯區塊。
* 建議自架 LibreTranslate 或改接商用服務（如 DeepL、Azure Translator），確保穩定度與保密性。
