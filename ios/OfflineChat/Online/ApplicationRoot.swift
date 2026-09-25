import SwiftUI

@main
struct OfflineChatIOSApp: App {
    @StateObject private var online = OnlineChatStore()
    @StateObject private var theme = AppTheme()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            TabView {
                OnlineMessengerView(store: online)
                    .tabItem { Label("Онлайн", systemImage: "bubble.left.and.bubble.right.fill") }
                OnlineAccountView(store: online)
                    .tabItem { Label("Профиль", systemImage: "person.crop.circle") }
                OfflineChatView()
                    .tabItem { Label("Рядом", systemImage: "dot.radiowaves.left.and.right") }
                OfflineToolsView()
                    .tabItem { Label("Оффлайн", systemImage: "cross.case.fill") }
            }
            .tint(.ocPrimary)
            .preferredColorScheme(theme.scheme)
            .environmentObject(theme)
            .onAppear { Notifier.request() }
            .onChange(of: scenePhase) { _, phase in online.handleScene(phase) }
        }
    }
}
