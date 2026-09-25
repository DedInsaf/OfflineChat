import Foundation

enum OnlineMessageStatus: String, Codable, CaseIterable {
    case sending
    case sent
    case delivered
    case read
    case failed

    var rank: Int {
        switch self {
        case .failed: return -1
        case .sending: return 0
        case .sent: return 1
        case .delivered: return 2
        case .read: return 3
        }
    }
}

struct OnlineProfile: Codable, Equatable, Identifiable {
    var id: String { username }
    let username: String
    var displayName: String
    var bio: String
    var avatarBase64: String?
    var lastSeen: Date?

    enum CodingKeys: String, CodingKey {
        case username = "name"
        case displayName = "display_name"
        case bio
        case avatarBase64 = "avatar_base64"
        case lastSeen = "last_seen"
    }

    var title: String {
        let value = displayName.trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? "@\(username)" : value
    }
}

struct OnlineMessage: Codable, Equatable, Identifiable {
    let clientID: UUID
    var serverID: Int64?
    let sender: String
    let recipient: String
    let text: String
    let createdAt: Date
    var status: OnlineMessageStatus

    var id: UUID { clientID }

    enum CodingKeys: String, CodingKey {
        case clientID = "client_id"
        case serverID = "id"
        case sender
        case recipient
        case text = "body"
        case createdAt = "created_at"
        case status
    }

    func isOutgoing(for username: String) -> Bool { sender == username }
    func peer(for username: String) -> String { sender == username ? recipient : sender }
}

struct OnlineEvent: Decodable {
    let eventID: Int64
    let kind: String
    let message: OnlineMessage

    enum CodingKeys: String, CodingKey {
        case eventID = "event_id"
        case kind
        case message
    }
}

struct OnlineSyncResponse: Decodable {
    let cursor: Int64
    let events: [OnlineEvent]
    let profiles: [OnlineProfile]
    let typing: [String]
}

struct OnlineConversation: Identifiable, Equatable {
    let username: String
    let profile: OnlineProfile?
    let lastMessage: OnlineMessage?
    let unreadCount: Int

    var id: String { username }
    var title: String { profile?.title ?? "@\(username)" }
}

enum UsernameRules {
    static func normalized(_ raw: String) -> String {
        var value = raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if value.hasPrefix("@") { value.removeFirst() }
        return String(value.filter { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "_") }.prefix(20))
    }

    static func validate(_ raw: String) -> String? {
        let value = normalized(raw)
        guard value.count >= 3, value.first?.isLetter == true else { return nil }
        return value
    }
}
