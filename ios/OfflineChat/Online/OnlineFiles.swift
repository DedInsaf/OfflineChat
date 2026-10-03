import Foundation
import CryptoKit

enum OnlineFiles {
    static let limit = 50 * 1024 * 1024

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

    private static func readDirect(_ url: URL) throws -> Data {
        let stream = try FileHandle(forReadingFrom: url)
        defer { try? stream.close() }
        let data = try stream.read(upToCount: limit + 1) ?? Data()
        guard !data.isEmpty, data.count <= limit else {
            throw failure("Выберите непустой файл размером до 50 МБ")
        }
        return data
    }

    /// File-provider URLs (iCloud Drive, Google Drive and others) must be
    /// coordinated while the security-scoped access is still active.
    static func read(_ url: URL) throws -> Data {
        var coordinationError: NSError?
        var readResult: Result<Data, Error>?
        NSFileCoordinator().coordinate(readingItemAt: url, options: [], error: &coordinationError) { coordinatedURL in
            readResult = Result { try readDirect(coordinatedURL) }
        }
        if let coordinationError { throw coordinationError }
        guard let readResult else { throw failure("Не удалось получить файл из приложения «Файлы»") }
        return try readResult.get()
    }

    static func stage(_ source: URL, id: UUID) async throws -> OnlineAttachment {
        try await Task.detached(priority: .utility) {
            guard safeName(source.lastPathComponent) else { throw failure("Недопустимое имя файла") }
            let data = try read(source)
            let directory = try folder(id)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            try data.write(to: directory.appendingPathComponent(source.lastPathComponent), options: .atomic)
            return OnlineAttachment(name: source.lastPathComponent, size: data.count, sha256: digest(data))
        }.value
    }

    static func stage(_ data: Data, name: String, id: UUID) async throws -> OnlineAttachment {
        try await Task.detached(priority: .utility) {
            guard safeName(name) else { throw failure("Недопустимое имя файла") }
            guard !data.isEmpty, data.count <= limit else {
                throw failure("Выберите файл размером до 50 МБ")
            }
            let directory = try folder(id)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            try data.write(to: directory.appendingPathComponent(name), options: .atomic)
            return OnlineAttachment(name: name, size: data.count, sha256: digest(data))
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

    static func cachedDownload(_ attachment: OnlineAttachment, id: UUID) async -> URL? {
        await Task.detached(priority: .utility) {
            let url = FileManager.default.temporaryDirectory
                .appendingPathComponent("OnlineDownloads").appendingPathComponent(id.uuidString)
                .appendingPathComponent(attachment.name)
            guard FileManager.default.fileExists(atPath: url.path),
                  let data = try? readDirect(url), data.count == attachment.size,
                  digest(data) == attachment.sha256 else { return nil }
            return url
        }.value
    }

    static func removeStaged(_ id: UUID) async {
        await Task.detached(priority: .utility) {
            if let directory = try? folder(id) { try? FileManager.default.removeItem(at: directory) }
        }.value
    }
}
