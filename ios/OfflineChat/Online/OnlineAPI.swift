import Foundation

enum OnlineAPIError: LocalizedError {
    case invalidServerURL
    case invalidResponse
    case server(status: Int, message: String)
    case decoding(Error)

    var errorDescription: String? {
        switch self {
        case .invalidServerURL:
            return "Не задан адрес личного сервера"
        case .invalidResponse:
            return "Сервер вернул некорректный ответ"
        case let .server(status, message):
            if message.localizedCaseInsensitiveContains("username is already taken") {
                return "Этот @username уже занят"
            }
            if message.localizedCaseInsensitiveContains("invalid owner token") {
                return "Профиль принадлежит другому устройству"
            }
            if message.localizedCaseInsensitiveContains("invalid username/email or password") {
                return "Неверный юз, почта или пароль"
            }
            if message.localizedCaseInsensitiveContains("passwords do not match") {
                return "Пароли не совпадают"
            }
            if message.localizedCaseInsensitiveContains("session expired") {
                return "Сессия закончилась. Войдите снова"
            }
            if message.localizedCaseInsensitiveContains("email delivery is not configured") {
                return "На сервере ещё не подключена отправка писем"
            }
            if message.localizedCaseInsensitiveContains("recipient not found") {
                return "Пользователь не найден"
            }
            return message.isEmpty ? "Ошибка личного сервера (\(status))" : message
        case let .decoding(error):
            return "Не удалось прочитать ответ сервера: \(error.localizedDescription)"
        }
    }
}

private struct ServerErrorBody: Decodable {
    let error: String?
}

struct OnlineAuthChallenge: Decodable {
    let challengeID: String
    let emailHint: String
    let expiresIn: Int

    enum CodingKeys: String, CodingKey {
        case challengeID = "challenge_id"
        case emailHint = "email_hint"
        case expiresIn = "expires_in"
    }
}

struct OnlineAuthSession: Decodable {
    let sessionToken: String
    let profile: OnlineProfile

    enum CodingKeys: String, CodingKey {
        case sessionToken = "session_token"
        case profile
    }
}

final class OnlineAPI {
    let root: URL?
    private let session: URLSession
    private let encoder = JSONEncoder()
    private let decoder: JSONDecoder

    static var configuredRoot: URL? {
        let configured = UserDefaults.standard.string(forKey: "onlinechat.serverURL")
            ?? Bundle.main.object(forInfoDictionaryKey: "OfflineChatServerURL") as? String
        return configured.flatMap { URL(string: $0) }
    }

    init(root: URL? = OnlineAPI.configuredRoot, session: URLSession? = nil) {
        self.root = root
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 60
        configuration.timeoutIntervalForResource = 180
        configuration.waitsForConnectivity = true
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.httpMaximumConnectionsPerHost = 4
        self.session = session ?? URLSession(configuration: configuration)

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let value = try container.decode(String.self)
            let fractional = ISO8601DateFormatter()
            fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = fractional.date(from: value) { return date }
            let basic = ISO8601DateFormatter()
            if let date = basic.date(from: value) { return date }
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Invalid ISO-8601 date")
        }
        self.decoder = decoder
    }

    func startRegistration(username: String, email: String, password: String,
                           confirmation: String, displayName: String) async throws -> OnlineAuthChallenge {
        struct Body: Encodable {
            let username: String; let email: String; let password: String
            let password_confirmation: String; let display_name: String
        }
        return try await call("auth/register/start", body: Body(
            username: username, email: email, password: password,
            password_confirmation: confirmation, display_name: displayName
        ))
    }

    func startLogin(identifier: String, password: String) async throws -> OnlineAuthChallenge {
        try await call("auth/login/start", body: ["identifier": identifier, "password": password])
    }

    func verify(challengeID: String, code: String, registration: Bool) async throws -> OnlineAuthSession {
        let endpoint = registration ? "auth/register/verify" : "auth/login/verify"
        return try await call(endpoint, body: ["challenge_id": challengeID, "code": code])
    }

    func logout(sessionToken: String) async throws {
        struct Reply: Decodable { let ok: Bool }
        let _: Reply = try await call("auth/logout", body: ["session_token": sessionToken])
    }

    func checkConnection() async throws {
        guard let root else { throw OnlineAPIError.invalidServerURL }
        struct Health: Decodable { let ok: Bool }
        var request = URLRequest(url: root.appendingPathComponent("health"))
        request.timeoutInterval = 6
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200,
              let health = try? JSONDecoder().decode(Health.self, from: data), health.ok else {
            throw OnlineAPIError.invalidResponse
        }
    }

    func updateProfile(
        currentUsername: String,
        newUsername: String,
        displayName: String,
        bio: String,
        avatarBase64: String?,
        sessionToken: String
    ) async throws -> OnlineProfile {
        struct Body: Encodable {
            let username: String
            let new_username: String
            let display_name: String
            let bio: String
            let avatar_base64: String?
            let session_token: String
        }
        return try await call("profile/update", body: Body(
            username: currentUsername,
            new_username: newUsername,
            display_name: displayName,
            bio: bio,
            avatar_base64: avatarBase64,
            session_token: sessionToken
        ))
    }

    func search(query: String) async throws -> [OnlineProfile] {
        try await call("profile/search", body: ["query": query])
    }

    func send(_ message: OnlineMessage, sessionToken: String) async throws -> OnlineMessage {
        struct FileBody: Encodable {
            let name: String
            let data_base64: String
        }
        struct Body: Encodable {
            let sender: String
            let recipient: String
            let client_id: UUID
            let body: String
            let session_token: String
            let attachment: FileBody?
        }
        var file: FileBody?
        if let attachment = message.attachment {
            file = FileBody(name: attachment.name, data_base64: try await OnlineFiles.encoded(attachment, id: message.clientID))
        }
        return try await call("messages/send", body: Body(
            sender: message.sender,
            recipient: message.recipient,
            client_id: message.clientID,
            body: message.text,
            session_token: sessionToken,
            attachment: file
        ))
    }

    func download(_ message: OnlineMessage, username: String, sessionToken: String) async throws -> URL {
        guard let id = message.serverID, let attachment = message.attachment else {
            throw OnlineFiles.failure("Дождитесь отправки файла")
        }
        if let cached = await OnlineFiles.cachedDownload(attachment, id: message.clientID) {
            return cached
        }
        struct Body: Encodable {
            let username: String
            let session_token: String
            let message_id: Int64
        }
        struct Download: Decodable { let data_base64: String }
        let result: Download = try await call("files/download", body: Body(username: username, session_token: sessionToken, message_id: id))
        return try await OnlineFiles.saveDownload(result.data_base64, attachment: attachment, id: message.clientID)
    }

    func sync(username: String, sessionToken: String, after cursor: Int64) async throws -> OnlineSyncResponse {
        struct Body: Encodable {
            let username: String
            let session_token: String
            let after_event: Int64
            let wait_ms: Int
        }
        return try await call("sync", body: Body(
            username: username,
            session_token: sessionToken,
            after_event: cursor,
            wait_ms: 20_000
        ))
    }

    func acknowledge(username: String, sessionToken: String, messageIDs: [Int64], status: OnlineMessageStatus) async throws {
        guard !messageIDs.isEmpty else { return }
        struct Body: Encodable {
            let username: String
            let session_token: String
            let message_ids: [Int64]
            let status: String
        }
        let _: [Int64] = try await call("messages/ack", body: Body(
            username: username,
            session_token: sessionToken,
            message_ids: messageIDs,
            status: status.rawValue
        ))
    }

    func setTyping(username: String, recipient: String, sessionToken: String) async throws {
        struct Body: Encodable {
            let username: String
            let recipient: String
            let session_token: String
        }
        let _: Bool = try await call("typing", body: Body(
            username: username,
            recipient: recipient,
            session_token: sessionToken
        ))
    }

    private func call<Response: Decodable, Body: Encodable>(_ endpoint: String, body: Body) async throws -> Response {
        guard let root else { throw OnlineAPIError.invalidServerURL }
        var url = root.appendingPathComponent("v1")
        for component in endpoint.split(separator: "/") {
            url.appendPathComponent(String(component))
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = endpoint == "messages/send" || endpoint == "files/download" ? 150 : 35
        request.httpMethod = "POST"
        request.httpBody = try encoder.encode(body)
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("OfflineChat-iOS/3.0", forHTTPHeaderField: "User-Agent")

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw OnlineAPIError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            let payload = try? decoder.decode(ServerErrorBody.self, from: data)
            let fallback = String(data: data, encoding: .utf8) ?? ""
            throw OnlineAPIError.server(status: http.statusCode, message: payload?.error ?? fallback)
        }
        do {
            return try decoder.decode(Response.self, from: data)
        } catch {
            throw OnlineAPIError.decoding(error)
        }
    }
}
