import Foundation

struct OnlineQuote: Codable, Equatable {
    let id: String
    let sender: String
    let text: String
    init(_ message: OnlineMessage) {
        id = message.clientID.uuidString.lowercased()
        sender = message.sender
        text = String(message.previewText.prefix(240))
    }
}

struct OnlineLocation: Codable, Equatable {
    let latitude: Double
    let longitude: Double
    var valid: Bool { latitude.isFinite && longitude.isFinite && (-90...90).contains(latitude) && (-180...180).contains(longitude) }
    var yandexURL: URL {
        var url = URLComponents(string: "https://yandex.ru/maps/")!
        let point = "\(longitude),\(latitude)"
        url.queryItems = [URLQueryItem(name: "ll", value: point), URLQueryItem(name: "pt", value: point), URLQueryItem(name: "z", value: "16")]
        return url.url!
    }
    var twoGISURL: URL { URL(string: "https://2gis.ru/geo/\(longitude),\(latitude)")! }
}

struct OnlineMessageContent: Codable, Equatable {
    var text: String
    var reply: OnlineQuote? = nil
    var forward: OnlineQuote? = nil
    var location: OnlineLocation? = nil
    static let prefix = "OCM1:"

    static func decode(_ body: String) -> Self {
        var result = Self(text: body)
        if body.hasPrefix(prefix), let data = String(body.dropFirst(prefix.count)).data(using: .utf8),
           let content = try? JSONDecoder().decode(Self.self, from: data) {
            result = content
            if result.location?.valid == false { result.location = nil }
        }
        if result.text.hasPrefix("📍 Местоположение\nhttps://maps.apple.com/"),
           let url = URLComponents(string: String(result.text.split(separator: "\n").last ?? "")),
           let point = url.queryItems?.first(where: { $0.name == "ll" })?.value {
            let values = point.split(separator: ",").compactMap { Double($0) }
            if values.count == 2 {
                let location = OnlineLocation(latitude: values[0], longitude: values[1])
                if location.valid { result.location = location }
            }
        }
        return result
    }

    var encoded: String {
        guard reply != nil || forward != nil || location != nil else { return text }
        guard let data = try? JSONEncoder().encode(self), let json = String(data: data, encoding: .utf8) else { return text }
        return Self.prefix + json
    }
}

extension OnlineMessage {
    var content: OnlineMessageContent { .decode(text) }
    var copyText: String { content.location?.yandexURL.absoluteString ?? previewText }
}
