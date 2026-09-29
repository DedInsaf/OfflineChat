import SwiftUI

@main
struct OfflineChatIOSApp: App {
    @StateObject private var online = OnlineChatStore()
    @StateObject private var theme = AppTheme()
    @StateObject private var bluetooth = OfflineChatBluetooth()
    @State private var selectedTab = 0
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ZStack {
                TabView(selection: $selectedTab) {
                    OnlineMessengerView(store: online)
                        .tabItem { Label("Онлайн", systemImage: "bubble.left.and.bubble.right.fill") }
                        .tag(0)
                    OnlineAccountView(store: online, onOpenLogin: { selectedTab = 0 })
                        .tabItem { Label("Профиль", systemImage: "person.crop.circle") }
                        .tag(1)
                    OfflineChatView(bluetooth: bluetooth)
                        .tabItem { Label("Рядом", systemImage: "dot.radiowaves.left.and.right") }
                        .tag(2)
                    OfflineToolsView()
                        .tabItem { Label("Оффлайн", systemImage: "cross.case.fill") }
                        .tag(3)
                }
                if let request = bluetooth.pendingConnection {
                    IncomingOverlay(
                        name: request.name,
                        onAllow: {
                            selectedTab = 2
                            bluetooth.approveIncoming()
                        },
                        onDeny: { bluetooth.denyIncoming() }
                    )
                    .zIndex(10)
                }
            }
            .tint(.ocPrimary)
            .preferredColorScheme(theme.scheme)
            .environmentObject(theme)
            .onAppear { Notifier.request() }
            .onChange(of: bluetooth.pendingConnection) { _, request in
                if request != nil { selectedTab = 2 }
            }
            .onChange(of: scenePhase) { _, phase in online.handleScene(phase) }
        }
    }
}
