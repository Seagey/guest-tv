// Guest TV for Apple TV (New, Beta): guest-tv's welcome screen as a native tvOS app. tvOS has no web
// view, so this draws the TV page (web/index.html) again in SwiftUI from the house computer's
// /api/tv/native data (docs/APPLE-TV.md). The computer opens it each time the Apple TV wakes.
import SwiftUI

@main
struct GuestTVApp: App {
    @StateObject private var model: WelcomeModel
    @Environment(\.scenePhase) private var phase

    init() {
        Look.registerFonts()
        _model = StateObject(wrappedValue: WelcomeModel())
    }

    var body: some Scene {
        WindowGroup {
            WelcomeView()
                .environmentObject(model)
                .onAppear { model.start() }
                .preferredColorScheme(.dark)
                .onChange(of: phase) { _, now in
                    if now == .active { Task { await model.refresh() } }   // opened again: fresh at once
                }
        }
    }
}
