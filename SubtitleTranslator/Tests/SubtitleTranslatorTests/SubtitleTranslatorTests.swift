import XCTest
@testable import SubtitleTranslator

final class SubtitleTranslatorTests: XCTestCase {
    func testSRTExport() {
        let segments = [
            SubtitleSegment(index: 0, startTime: 0, endTime: 1.5, text: "你好"),
            SubtitleSegment(index: 1, startTime: 1.5, endTime: 3.8, text: "世界")
        ]
        let srt = SubtitleFileExporter.makeSRT(from: segments)
        XCTAssertTrue(srt.contains("00:00:00,000 --> 00:00:01,500"))
        XCTAssertTrue(srt.contains("你好"))
    }

    func testSimplifiedToTraditional() {
        let converter = ChineseConverter()
        let result = converter.convertToTraditional("汉字")
        XCTAssertEqual(result, "漢字")
    }
}
