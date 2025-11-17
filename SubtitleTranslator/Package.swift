// swift-tools-version:5.7
import PackageDescription

let package = Package(
    name: "SubtitleTranslator",
    platforms: [
        .macOS(.v12)
    ],
    products: [
        .executable(name: "SubtitleTranslator", targets: ["SubtitleTranslator"])
    ],
    dependencies: [],
    targets: [
        .executableTarget(
            name: "SubtitleTranslator",
            resources: [
                .process("Resources")
            ]
        ),
        .testTarget(
            name: "SubtitleTranslatorTests",
            dependencies: ["SubtitleTranslator"]
        )
    ]
)
