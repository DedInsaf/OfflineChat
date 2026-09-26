import Foundation
import CryptoKit

enum OnlineFiles {
    static let limit = 5 * 1024 * 1024

    static func folder(_ id: UUID) throws -> URL {
        let root = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                               appropriateFor: nil, create: true)
        return root.appendingPathComponent("OnlineAttachments").appendingPathComponent(id.uuidString)
    }

    static func safeName(_ name: String) -> Bool {
        !name.isEmpty && name.count <= 180 && name != "." && name != ".."
        && !name.contains("/") && !name.contains("\\")
        && !name.unicodeScalars.contains { CharacterSet.controlCharacters.contains($0) }
    }

    static func failure(_ text: String) -> NSError {
        NSError(domain: "OnlineFiles", code: 1, userInfo: [NSLocalizedDescriptionKey: text])
    }

    static func digest(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    static func read(_ url: URL) throws -> Data {
        let stream = try FileHandle(forReadingFrom: url)
        defer { try? stream.close() }
        let data = try stream.read(upToCount: limit + 1) ?? Data()
        guard !data.isEmpty, data.count <= limit else {
            throw failure("Выберите непустой файл размером до 5 МБ")
        }
        return data
    }

    static func stage(_ source: URL, id: UUID) async throws -> OnlineAttachment {
        try await Task.detached(priority: .utility) {
            let access = source.startAccessingSecurityScopedResource()
            defer { if access { source.stopAccessingSecurityScopedResource() } }
            guard safeName(source.lastPathComponent) else { throw failure("Недопустимое имя файла") }
            let data = try read(source)
            let directory = try folder(id)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            try data.write(to: directory.appendingPathComponent(source.lastPathComponent), options: .atomic)
            return OnlineAttachment(name: source.lastPathComponent, size: data.count, sha256: digest(data))
        }.value
    }

    static func encoded(_ attachment: OnlineAttachment, id: UUID) async throws -> String {
        try await Task.detached(priority: .utility) {
            guard safeName(attachment.name) else { throw failure("Недопустимое имя файла") }
            let data = try read(folder(id).appendingPathComponent(attachment.name))
            guard data.count == attachment.size, digest(data) == attachment.sha256 else {
                throw failure("Локальный файл изменён. Выберите его заново.")
            }
            return data.base64EncodedString()
        }.value
    }

    static func saveDownload(_ encoded: String, attachment: OnlineAttachment, id: UUID) async throws -> URL {
        try await Task.detached(priority: .utility) {
            guard safeName(attachment.name), let data = Data(base64Encoded: encoded), data.count <= limit,
                  data.count == attachment.size, digest(data) == attachment.sha256 else {
                throw failure("Файл повреждён. Повторите скачивание.")
            }
            // Cache is expendable; uploading originals remain in Application Support for retry.
            let directory = FileManager.default.temporaryDirectory
                .appendingPathComponent("OnlineDownloads").appendingPathComponent(id.uuidString)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let url = directory.appendingPathComponent(attachment.name)
            try data.write(to: url, options: .atomic)
            return url
        }.value
    }

    static func removeStaged(_ id: UUID) async {
        await Task.detached(priority: .utility) {
            if let directory = try? folder(id) { try? FileManager.default.removeItem(at: directory) }
        }.value
    }
}
