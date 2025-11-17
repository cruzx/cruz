import SwiftUI

@main
struct SubtitleTranslatorApp: App {
    @StateObject private var viewModel = SubtitleTranslatorViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(viewModel)
        }
        .commands {
            SidebarCommands()
        }
    }
}
