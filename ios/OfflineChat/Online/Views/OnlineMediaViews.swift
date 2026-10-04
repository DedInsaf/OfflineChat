import SwiftUI
import PhotosUI
import UniformTypeIdentifiers
import CoreTransferable
import AVKit
import AVFoundation
import UIKit
import CoreLocation

struct OnlineAttachmentMenu: View {
    let onPick: (OnlineAttachmentAction) -> Void

    var body: some View {
        VStack(spacing: 1) {
            ForEach(OnlineAttachmentAction.allCases, id: \.self) { action in
                Button { onPick(action) } label: {
                    HStack(spacing: 13) {
                        Image(systemName: action.symbol)
                            .font(.system(size: 18, weight: .regular))
                            .frame(width: 25, height: 24)
                        Text(action.title)
                            .font(.system(size: 17, weight: .regular))
                        Spacer(minLength: 8)
                    }
                    .foregroundStyle(Color.ocText)
                    .frame(height: 43)
                    .padding(.horizontal, 14)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .frame(width: 238)
        .padding(.vertical, 7)
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
        .shadow(color: .black.opacity(0.18), radius: 16, y: 7)
    }
}

final class OnlineLocationProvider: NSObject, ObservableObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var completion: ((Result<CLLocationCoordinate2D, Error>) -> Void)?

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
    }

    func requestLocation(completion: @escaping (Result<CLLocationCoordinate2D, Error>) -> Void) {
        self.completion = completion
        switch manager.authorizationStatus {
        case .notDetermined: manager.requestWhenInUseAuthorization()
        case .authorizedAlways, .authorizedWhenInUse: manager.requestLocation()
        default: finish(.failure(OnlineFiles.failure("Разрешите доступ к геопозиции в Настройках iPhone.")))
        }
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        if manager.authorizationStatus == .authorizedAlways || manager.authorizationStatus == .authorizedWhenInUse {
            manager.requestLocation()
        } else if manager.authorizationStatus == .denied || manager.authorizationStatus == .restricted {
            finish(.failure(OnlineFiles.failure("Разрешите доступ к геопозиции в Настройках iPhone.")))
        }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let coordinate = locations.last?.coordinate else { return }
        finish(.success(coordinate))
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        finish(.failure(error))
    }

    private func finish(_ result: Result<CLLocationCoordinate2D, Error>) {
        DispatchQueue.main.async {
            let callback = self.completion
            self.completion = nil
            callback?(result)
        }
    }
}

struct OnlineCameraPicker: UIViewControllerRepresentable {
    let completion: (UIImage?) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(completion: completion) }

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let controller = UIImagePickerController()
        controller.sourceType = .camera
        controller.cameraCaptureMode = .photo
        controller.delegate = context.coordinator
        return controller
    }

    func updateUIViewController(_ uiViewController: UIImagePickerController, context: Context) {}

    final class Coordinator: NSObject, UINavigationControllerDelegate, UIImagePickerControllerDelegate {
        let completion: (UIImage?) -> Void
        init(completion: @escaping (UIImage?) -> Void) { self.completion = completion }

        func imagePickerController(_ picker: UIImagePickerController,
                                   didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            completion(info[.originalImage] as? UIImage)
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { completion(nil) }
    }
}

struct OnlineMessageBubble: View, Equatable {
    let message: OnlineMessage
    let outgoing: Bool
    let onRetry: () -> Void
    let download: (Bool) async -> URL?
    let onOpenMedia: (URL) -> Void
    let onOpenFile: (URL) -> Void
    var onOpenReply: (String) -> Void = { _ in }
    @State private var mediaURL: URL?
    @State private var loading = false

    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.message == rhs.message && lhs.outgoing == rhs.outgoing
    }

    var body: some View {
        let content = message.content
        HStack(alignment: .bottom) {
            if outgoing { Spacer(minLength: message.attachment?.kind == "circle" ? 8 : 24) }
            VStack(alignment: .leading, spacing: 3) {
                if let forwarded = content.forward {
                    Text("Переслано от @" + forwarded.sender).font(.caption).foregroundStyle(Color.ocMuted)
                }
                if let reply = content.reply {
                    Button { onOpenReply(reply.id) } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("↩ @" + reply.sender).font(.caption.weight(.semibold))
                            Text(reply.text).font(.caption).lineLimit(2)
                        }
                        .foregroundStyle(Color.ocText)
                        .padding(8).frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.ocSurfaceAlt, in: RoundedRectangle(cornerRadius: 8))
                    }.buttonStyle(.plain)
                }
                if let attachment = message.attachment {
                    attachmentContent(attachment)
                } else {
                    if let location = content.location {
                        OnlineLocationCard(location: location)
                    } else {
                    OnlineLinkedText(text: content.text)
                        .font(.system(size: 16))
                        .foregroundColor(outgoing ? .ocPrimaryFg : .ocText)
                    }
                }
                HStack(spacing: 4) {
                    Spacer(minLength: 0)
                    Text(message.createdAt, format: .dateTime.hour().minute())
                        .font(.system(size: 10))
                        .foregroundColor(outgoing ? Color.ocPrimaryFg.opacity(0.68) : .ocMuted)
                    if outgoing { OnlineReceiptView(status: message.status) }
                }
            }
            .padding(.horizontal, 11)
            .padding(.vertical, 7)
            .background(message.attachment?.kind == "circle" ? Color.clear : (outgoing ? Color.ocOutgoing : Color.ocIncoming))
            .clipShape(RoundedRectangle(cornerRadius: 17, style: .continuous))
            .overlay(alignment: .bottomTrailing) {
                if message.status == .failed { Button("Повторить", action: onRetry).font(.caption).offset(y: 16) }
            }
            if !outgoing { Spacer(minLength: message.attachment?.kind == "circle" ? 8 : 24) }
        }
        .task(id: message.serverID) {
            guard ["photo", "voice", "circle"].contains(message.attachment?.kind ?? ""), mediaURL == nil, message.serverID != nil else { return }
            await load(openWhenReady: false)
        }
    }

    @ViewBuilder
    private func attachmentContent(_ attachment: OnlineAttachment) -> some View {
        switch attachment.kind {
        case "voice", "circle":
            if let mediaURL {
                RecordedMessageView(url: mediaURL, circle: attachment.kind == "circle")
            } else {
                Button { Task { await load(openWhenReady: false) } } label: {
                    Label(loading ? "Загрузка…" : (attachment.kind == "circle" ? "Видеокружок" : "Голосовое сообщение"), systemImage: "play.fill")
                        .frame(width: attachment.kind == "circle" ? 210 : 220, height: attachment.kind == "circle" ? 210 : 48)
                        .background(Color.black.opacity(0.1), in: RoundedRectangle(cornerRadius: attachment.kind == "circle" ? 105 : 16))
                }.disabled(loading || message.serverID == nil)
            }
        case "photo":
            Button { Task { await load(openWhenReady: true) } } label: {
                ZStack {
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(Color.black.opacity(0.08))
                        .frame(width: 246, height: 184)
                    if let mediaURL {
                        OnlineThumbnailView(url: mediaURL)
                    } else if loading {
                        ProgressView().tint(.white)
                    } else {
                        Image(systemName: "photo")
                            .font(.system(size: 34, weight: .light))
                            .foregroundStyle(outgoing ? Color.ocPrimaryFg.opacity(0.76) : Color.ocMuted)
                    }
                }
            }
            .buttonStyle(.plain)
            .disabled(message.serverID == nil)
        case "video":
            Button { Task { await load(openWhenReady: true) } } label: {
                ZStack {
                    LinearGradient(colors: [Color.black.opacity(0.76), Color.black.opacity(0.48)],
                                   startPoint: .topLeading, endPoint: .bottomTrailing)
                    VStack(spacing: 10) {
                        ZStack {
                            Circle().fill(.white.opacity(0.94)).frame(width: 54, height: 54)
                            if loading {
                                ProgressView().tint(.black)
                            } else {
                                Image(systemName: "play.fill")
                                    .font(.system(size: 20, weight: .bold))
                                    .foregroundStyle(.black.opacity(0.82))
                                    .offset(x: 2)
                            }
                        }
                        Text(loading ? "Загружаем видео…" : "Видео · \(attachment.sizeText)")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.white.opacity(0.9))
                    }
                }
                .frame(width: 246, height: 150)
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            }
            .buttonStyle(.plain)
            .disabled(message.serverID == nil || loading)
        default:
            Button { Task { await load(openWhenReady: true) } } label: {
                HStack(spacing: 12) {
                    Image(systemName: "doc.fill")
                        .font(.system(size: 19, weight: .semibold))
                        .foregroundStyle(outgoing ? Color.ocPrimaryFg : Color.ocPrimary)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(attachment.name).font(.system(size: 14, weight: .semibold)).lineLimit(2)
                        Text(loading ? "Загрузка…" : attachment.sizeText).font(.caption).opacity(0.65)
                    }
                    Spacer(minLength: 8)
                    if loading { ProgressView().controlSize(.small) }
                    else { Image(systemName: "arrow.down").font(.system(size: 14, weight: .semibold)) }
                }
                .foregroundColor(outgoing ? .ocPrimaryFg : .ocText)
                .frame(width: 236)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(message.serverID == nil || loading)
        }
    }

    @MainActor
    private func load(openWhenReady: Bool) async {
        if let mediaURL {
            if openWhenReady { open(mediaURL) }
            return
        }
        guard !loading, message.serverID != nil else { return }
        loading = true
        let url = await download(openWhenReady)
        loading = false
        guard let url else { return }
        mediaURL = url
        if openWhenReady { open(url) }
    }

    private func open(_ url: URL) {
        if message.attachment?.kind == "file" { onOpenFile(url) }
        else { onOpenMedia(url) }
    }
}

struct DownloadedOnlineFile: Identifiable {
    let id = UUID()
    let url: URL
}

struct PreviewedOnlineMedia: Identifiable {
    let id = UUID()
    let url: URL
    let kind: String
}

struct PickedOnlineMovie: Transferable {
    let url: URL

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(contentType: .movie) { movie in
            SentTransferredFile(movie.url)
        } importing: { received in
            let ext = received.file.pathExtension.isEmpty ? "mov" : received.file.pathExtension
            let copy = FileManager.default.temporaryDirectory
                .appendingPathComponent("Видео-\(UUID().uuidString).\(ext)")
            try FileManager.default.copyItem(at: received.file, to: copy)
            return PickedOnlineMovie(url: copy)
        }
    }
}

enum OnlineMediaPreparation {
    struct Photo {
        let data: Data
        let name: String
    }

    struct Video {
        let url: URL
        let name: String
    }

    static func photo(_ source: Data) async throws -> Photo {
        try await Task.detached(priority: .userInitiated) {
            guard let original = UIImage(data: source) else {
                throw OnlineFiles.failure("Не удалось прочитать фотографию")
            }
            let maxSide: CGFloat = 1920
            let sourceSize = original.size
            let scale = min(1, maxSide / max(sourceSize.width, sourceSize.height))
            let image: UIImage
            if scale < 1 {
                let target = CGSize(width: max(1, sourceSize.width * scale), height: max(1, sourceSize.height * scale))
                let renderer = UIGraphicsImageRenderer(size: target)
                image = renderer.image { _ in original.draw(in: CGRect(origin: .zero, size: target)) }
            } else {
                image = original
            }
            var quality: CGFloat = 0.82
            var encoded = image.jpegData(compressionQuality: quality)
            while let value = encoded, value.count > OnlineFiles.limit, quality > 0.34 {
                quality -= 0.12
                encoded = image.jpegData(compressionQuality: quality)
            }
            guard let encoded, !encoded.isEmpty, encoded.count <= OnlineFiles.limit else {
                throw OnlineFiles.failure("Фотографию не удалось уменьшить до 50 МБ")
            }
            return Photo(data: encoded, name: "Фото-\(Int(Date().timeIntervalSince1970)).jpg")
        }.value
    }

    static func video(at source: URL) async throws -> Video {
        let asset = AVURLAsset(url: source)
        for preset in [AVAssetExportPresetMediumQuality, AVAssetExportPresetLowQuality] {
            guard let exporter = AVAssetExportSession(asset: asset, presetName: preset) else { continue }
            let output = FileManager.default.temporaryDirectory
                .appendingPathComponent("Видео-\(UUID().uuidString).mp4")
            do {
                try await exporter.export(to: output, as: .mp4)
                let size = (try? output.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
                if size > 0, size <= OnlineFiles.limit {
                    return Video(url: output, name: "Видео-\(Int(Date().timeIntervalSince1970)).mp4")
                }
            } catch {
                try? FileManager.default.removeItem(at: output)
                continue
            }
            try? FileManager.default.removeItem(at: output)
        }
        let size = (try? source.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        if size > 0, size <= OnlineFiles.limit {
            return Video(url: source, name: "Видео-\(Int(Date().timeIntervalSince1970)).mov")
        }
        throw OnlineFiles.failure("Видео слишком длинное. После сжатия оно всё ещё больше 50 МБ")
    }
}

struct OnlineMediaViewer: View {
    let media: PreviewedOnlineMedia
    @Environment(\.dismiss) private var dismiss
    @State private var player: AVPlayer

    init(media: PreviewedOnlineMedia) {
        self.media = media
        _player = State(initialValue: AVPlayer(url: media.url))
    }

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            if media.kind == "video" {
                VideoPlayer(player: player)
                    .ignoresSafeArea(edges: .horizontal)
                    .onAppear { player.play() }
                    .onDisappear { player.pause() }
            } else if let image = UIImage(contentsOfFile: media.url.path) {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
                    .padding(.vertical, 54)
            } else {
                ContentUnavailableView("Не удалось открыть медиа", systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.white)
            }
            VStack {
                HStack(spacing: 14) {
                    Button { dismiss() } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 16, weight: .bold))
                            .frame(width: 42, height: 42)
                            .background(.ultraThinMaterial, in: Circle())
                    }
                    Spacer()
                    ShareLink(item: media.url) {
                        Image(systemName: "square.and.arrow.up")
                            .font(.system(size: 17, weight: .semibold))
                            .frame(width: 42, height: 42)
                            .background(.ultraThinMaterial, in: Circle())
                    }
                }
                .foregroundStyle(.white)
                .padding(.horizontal, 16)
                .padding(.top, 8)
                Spacer()
            }
        }
        .statusBarHidden()
    }
}

struct OnlineDownloadedFileSheet: View {
    let file: DownloadedOnlineFile
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 18) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 44))
                .foregroundStyle(Color.ocSuccess)
            VStack(spacing: 5) {
                Text("Файл загружен").font(.title3.bold())
                Text(file.url.lastPathComponent).font(.subheadline).foregroundColor(.ocMuted).lineLimit(2)
            }
            ShareLink(item: file.url) {
                Label("Открыть или сохранить", systemImage: "square.and.arrow.up")
                    .fontWeight(.semibold)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .foregroundStyle(Color.ocPrimaryFg)
                    .background(Color.ocPrimary, in: RoundedRectangle(cornerRadius: 14))
            }
            Button("Закрыть") { dismiss() }.foregroundStyle(Color.ocMuted)
        }
        .padding(24)
    }
}
