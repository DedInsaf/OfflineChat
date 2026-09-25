import Foundation
import SwiftUI
import UserNotifications

private struct OnlineCache: Codable, Equatable {
    var cursor: Int64
    var messages: [String: [OnlineMessage]]
    var profiles: [String: OnlineProfile]
    var peers: [String]
}

private final class OnlineLocalStore {
    private let writeQueue = DispatchQueue(label: "onlinechat.cache", qos: .utility)
    private var lastScheduledCache: OnlineCache?
    private let encoder: JSONEncoder = {
        let value = JSONEncoder()
        value.dateEncodingStrategy = .iso8601
        return value
    }()
    private let decoder: JSONDecoder = {
        let value = JSONDecoder()
        value.dateDecodingStrategy = .iso8601
        return value
    }()

    private var url: URL? {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
        return base?.appendingPathComponent("online-chat-cache-v3.json")
    }

    func load() -> OnlineCache? {
        guard let url, let data = try? Data(contentsOf: url) else { return nil }
        return try? decoder.decode(OnlineCache.self, from: data)
    }

    func save(_ cache: OnlineCache) {
        guard cache != lastScheduledCache, let url else { return }
        lastScheduledCache = cache
        writeQueue.async { [self] in
        guard let data = try? encoder.encode(cache) else { return }
        do {
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: url, options: .atomic)
        } catch {
            print("online cache error: \(error.localizedDescription)")
        }
        }
    }
}

@MainActor
final class OnlineChatStore: ObservableObject {
    @Published private(set) var username: String
    @Published private(set) var myProfile: OnlineProfile?
    @Published private(set) var messages: [String: [OnlineMessage]] = [:]
    @Published private(set) var profiles: [String: OnlineProfile] = [:]
    @Published private(set) var peers: [String] = []
    @Published private(set) var typingPeers: Set<String> = []
    @Published private(set) var connectionText = "Не подключено"
    @Published private(set) var isWorking = false
    @Published var claimError = ""
    @Published var searchError = ""
    @Published private(set) var searchResults: [OnlineProfile] = []

    private var api: OnlineAPI
    @Published private(set) var serverAddress: String
    @Published private(set) var serverError = ""
    @Published private(set) var checkingServer = false
    private let localStore = OnlineLocalStore()
    private let defaults = UserDefaults.standard
    private let usernameKey = "onlinechat.username.v3"
    private var ownerToken: String
    private var cursor: Int64 = 0
    private var syncTask: Task<Void, Never>?
    private var syncInFlight = false
    private var lastTypingSent: [String: Date] = [:]
    private(set) var openPeer: String?

    init(api: OnlineAPI = OnlineAPI()) {
        self.api = api
        self.serverAddress = api.root?.absoluteString ?? ""
        username = UsernameRules.normalized(defaults.string(forKey: usernameKey) ?? "")
        ownerToken = OnlineCredentials.ownerToken()

        if let cache = localStore.load() {
            cursor = cache.cursor
            messages = cache.messages
            profiles = cache.profiles
            peers = cache.peers
            myProfile = profiles[username]
        }
        if !username.isEmpty { connectionText = "Подключение…" }
    }

    deinit { syncTask?.cancel() }

    func configureServer(_ raw: String) async -> Bool {
        guard !checkingServer, !isWorking else { return false }
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: text), let host = url.host,
              ["http", "https"].contains(url.scheme ?? ""),
              url.user == nil, url.password == nil, url.query == nil, url.fragment == nil,
              host != "127.0.0.1", host != "localhost" else {
            serverError = "Введите адрес общего сервера"
            return false
        }
        checkingServer = true
        serverError = ""
        defer { checkingServer = false }
        let candidate = OnlineAPI(root: url)
        do {
            try await candidate.checkConnection()
            // Authenticate before switching so an unrelated empty server cannot inherit our cursor.
            if !username.isEmpty {
                _ = try await candidate.claim(username: username, displayName: myProfile?.displayName ?? username, ownerToken: ownerToken)
            }
            let previous = syncTask
            previous?.cancel()
            await previous?.value
            syncTask = nil
            api = candidate
            serverAddress = url.absoluteString
            defaults.set(serverAddress, forKey: "onlinechat.serverURL")
            cursor = 0
            claimError = ""
            connectionText = "Подключено к серверу"
            persist()
            start()
            return true
        } catch {
            serverError = "Не удалось подключиться: \(error.localizedDescription)"
            return false
        }
    }

    var conversations: [OnlineConversation] {
        peers.map { peer in
            let list = messages[peer] ?? []
            return OnlineConversation(
                username: peer,
                profile: profiles[peer],
                lastMessage: list.last,
                unreadCount: list.filter { !$0.isOutgoing(for: username) && $0.status != .read }.count
            )
        }
        .sorted {
            ($0.lastMessage?.createdAt ?? .distantPast) > ($1.lastMessage?.createdAt ?? .distantPast)
        }
    }

    func start() {
        guard syncTask == nil, !username.isEmpty else { return }
        syncTask = Task { [weak self] in
            guard let self else { return }
            await self.restoreIdentity()
            while !Task.isCancelled {
                await self.synchronize()
                try? await Task.sleep(for: .milliseconds(self.connectionText == "Нет связи" ? 2000 : 1000))
            }
        }
    }

    func handleScene(_ phase: ScenePhase) {
        if phase == .active {
            start()
        } else if phase == .background {
            syncTask?.cancel()
            syncTask = nil
            persist()
        }
    }

    func claim(_ rawUsername: String, displayName: String) async {
        guard let wanted = UsernameRules.validate(rawUsername) else {
            claimError = "От 3 до 20 символов: латинские буквы, цифры и _. Первый символ — буква."
            return
        }
        isWorking = true
        defer { isWorking = false }
        do {
            let profile = try await api.claim(
                username: wanted,
                displayName: displayName.trimmingCharacters(in: .whitespacesAndNewlines),
                ownerToken: ownerToken
            )
            username = profile.username
            myProfile = profile
            profiles[profile.username] = profile
            defaults.set(username, forKey: usernameKey)
            claimError = ""
            cursor = 0
            messages = [:]
            peers = []
            connectionText = "Онлайн"
            persist()
            start()
        } catch {
            claimError = error.localizedDescription
        }
    }

    func updateProfile(username newRawUsername: String, displayName: String, bio: String, avatarBase64: String?) async -> Bool {
        guard let newUsername = UsernameRules.validate(newRawUsername) else {
            claimError = "Некорректный @username"
            return false
        }
        isWorking = true
        defer { isWorking = false }
        do {
            let oldUsername = username
            let profile = try await api.updateProfile(
                currentUsername: oldUsername,
                newUsername: newUsername,
                displayName: displayName.trimmingCharacters(in: .whitespacesAndNewlines),
                bio: String(bio.trimmingCharacters(in: .whitespacesAndNewlines).prefix(160)),
                avatarBase64: avatarBase64,
                ownerToken: ownerToken
            )
            username = profile.username
            myProfile = profile
            profiles.removeValue(forKey: oldUsername)
            profiles[profile.username] = profile
            defaults.set(username, forKey: usernameKey)
            claimError = ""
            if oldUsername != username {
                cursor = 0
                messages = [:]
                peers = []
                await synchronize()
            }
            persist()
            return true
        } catch {
            claimError = error.localizedDescription
            return false
        }
    }

    func search(_ raw: String) async {
        let query = UsernameRules.normalized(raw)
        guard query.count >= 2 else {
            searchError = "Введите хотя бы 2 символа"
            searchResults = []
            return
        }
        do {
            let result = try await api.search(query: query)
            searchResults = result.filter { $0.username != username }
            for profile in result { profiles[profile.username] = profile }
            searchError = searchResults.isEmpty ? "Ничего не найдено" : ""
        } catch {
            searchError = error.localizedDescription
        }
    }

    func beginConversation(with profile: OnlineProfile) {
        profiles[profile.username] = profile
        remember(peer: profile.username)
        persist()
    }

    func send(_ rawText: String, to recipient: String) async {
        let text = rawText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, text.count <= 2_000, !username.isEmpty else { return }
        let message = OnlineMessage(
            clientID: UUID(),
            serverID: nil,
            sender: username,
            recipient: recipient,
            text: text,
            createdAt: Date(),
            status: .sending
        )
        remember(peer: recipient)
        upsert(message)
        persist()
        await submit(message)
    }

    func retry(_ message: OnlineMessage) async {
        guard message.isOutgoing(for: username), message.status == .failed else { return }
        var pending = message
        pending.status = .sending
        upsert(pending)
        await submit(pending)
    }

    func openedChat(with peer: String) {
        openPeer = peer
        remember(peer: peer)
        Task { await markRead(peer: peer) }
    }

    func closedChat(with peer: String) {
        if openPeer == peer { openPeer = nil }
    }

    func sendTyping(to recipient: String) {
        let now = Date()
        guard now.timeIntervalSince(lastTypingSent[recipient] ?? .distantPast) > 2 else { return }
        lastTypingSent[recipient] = now
        Task {
            try? await api.setTyping(username: username, recipient: recipient, ownerToken: ownerToken)
        }
    }

    func markRead(peer: String) async {
        let ids = (messages[peer] ?? []).compactMap { message -> Int64? in
            guard !message.isOutgoing(for: username), message.status != .read else { return nil }
            return message.serverID
        }
        guard !ids.isEmpty else { return }
        do {
            try await api.acknowledge(username: username, ownerToken: ownerToken, messageIDs: ids, status: .read)
            var list = messages[peer] ?? []
            for index in list.indices where !list[index].isOutgoing(for: username) {
                list[index].status = .read
            }
            messages[peer] = list
            persist()
        } catch {
            connectionText = "Нет связи"
        }
    }

    private func restoreIdentity() async {
        guard myProfile == nil, !username.isEmpty else { return }
        do {
            let profile = try await api.claim(username: username, displayName: username, ownerToken: ownerToken)
            myProfile = profile
            profiles[profile.username] = profile
            claimError = ""
        } catch {
            claimError = error.localizedDescription
        }
    }

    private func submit(_ message: OnlineMessage) async {
        do {
            let saved = try await api.send(message, ownerToken: ownerToken)
            upsert(saved)
            connectionText = "Онлайн"
        } catch {
            var failed = message
            failed.status = .failed
            upsert(failed)
            connectionText = "Нет связи"
        }
        persist()
    }

    private func synchronize() async {
        guard !syncInFlight, !username.isEmpty else { return }
        syncInFlight = true
        defer { syncInFlight = false }
        do {
            let response = try await api.sync(username: username, ownerToken: ownerToken, after: cursor)
            try Task.checkCancellation()
            var deliveredIDs: [Int64] = []
            for profile in response.profiles {
                profiles[profile.username] = profile
                if profile.username == username { myProfile = profile }
            }
            for event in response.events {
                let message = event.message
                let peer = message.peer(for: username)
                let wasKnown = messages[peer]?.contains(where: { $0.clientID == message.clientID || ($0.serverID != nil && $0.serverID == message.serverID) }) == true
                remember(peer: peer)
                upsert(message)
                if !message.isOutgoing(for: username), message.status == .sent, let id = message.serverID {
                    deliveredIDs.append(id)
                    if !wasKnown, openPeer != peer {
                        notify(message: message, peer: peer)
                    }
                }
            }
            cursor = max(cursor, response.cursor)
            typingPeers = Set(response.typing)
            connectionText = "Онлайн"
            claimError = ""
            if !deliveredIDs.isEmpty {
                try await api.acknowledge(username: username, ownerToken: ownerToken, messageIDs: deliveredIDs, status: .delivered)
            }
            if let openPeer { await markRead(peer: openPeer) }
            persist()
        } catch {
            connectionText = "Нет связи"
            if claimError.isEmpty { claimError = error.localizedDescription }
        }
    }

    private func upsert(_ incoming: OnlineMessage) {
        let peer = incoming.peer(for: username)
        var list = messages[peer] ?? []
        if let index = list.firstIndex(where: {
            $0.clientID == incoming.clientID || ($0.serverID != nil && $0.serverID == incoming.serverID)
        }) {
            var merged = incoming
            if list[index].status.rank > incoming.status.rank { merged.status = list[index].status }
            list[index] = merged
        } else {
            list.append(incoming)
        }
        list.sort { lhs, rhs in
            if lhs.createdAt == rhs.createdAt { return lhs.clientID.uuidString < rhs.clientID.uuidString }
            return lhs.createdAt < rhs.createdAt
        }
        messages[peer] = Array(list.suffix(500))
    }

    private func remember(peer: String) {
        guard !peer.isEmpty, peer != username else { return }
        if !peers.contains(peer) { peers.append(peer) }
    }

    private func notify(message: OnlineMessage, peer: String) {
        let content = UNMutableNotificationContent()
        content.title = profiles[peer]?.title ?? "@\(peer)"
        content.body = message.text
        content.sound = .default
        content.threadIdentifier = "online-chat-\(peer)"
        UNUserNotificationCenter.current().add(
            UNNotificationRequest(identifier: message.clientID.uuidString, content: content, trigger: nil)
        )
    }

    private func persist() {
        localStore.save(OnlineCache(cursor: cursor, messages: messages, profiles: profiles, peers: peers))
    }
}
