import SwiftUI
import PhotosUI
import UniformTypeIdentifiers
import CoreTransferable
import AVKit
import UIKit
import CoreLocation

struct OnlineConversationRow: View {
    let conversation: OnlineConversation
    let currentUsername: String

    var body: some View {
        HStack(spacing: 12) {
            OnlineAvatarView(profile: conversation.profile, username: conversation.username, size: 52)
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(conversation.title)
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundColor(.ocText)
                        .lineLimit(1)
                    Spacer()
                    if let date = conversation.lastMessage?.createdAt {
                        Text(date, format: .dateTime.hour().minute())
                            .font(.caption2)
                            .foregroundColor(.ocMuted)
                    }
                }
                HStack(spacing: 4) {
                    if let message = conversation.lastMessage, message.isOutgoing(for: currentUsername) {
                        OnlineReceiptView(status: message.status, compact: true)
                    }
                    Text(conversation.lastMessage?.previewText ?? "Начать диалог")
                        .font(.system(size: 14))
                        .foregroundColor(.ocMuted)
                        .lineLimit(1)
                    Spacer()
                    if conversation.unreadCount > 0 {
                        Text("\(conversation.unreadCount)")
                            .font(.system(size: 11, weight: .bold))
                            .foregroundColor(.white)
                            .padding(.horizontal, 7)
                            .padding(.vertical, 3)
                            .background(Color.ocPrimary)
                            .clipShape(Capsule())
                    }
                }
            }
        }
        .padding(.vertical, 5)
    }
}

struct OnlineSearchView: View {
    @ObservedObject var store: OnlineChatStore
    let onSelect: (OnlineProfile) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""

    var body: some View {
        NavigationStack {
            List {
                ForEach(store.searchResults) { profile in
                    Button { onSelect(profile) } label: {
                        HStack(spacing: 12) {
                            OnlineAvatarView(profile: profile, username: profile.username)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(profile.title).foregroundColor(.ocText)
                                Text("@\(profile.username)").font(.caption).foregroundColor(.ocMuted)
                            }
                        }
                    }
                    .buttonStyle(.plain)
                    .listRowBackground(Color.ocSurface)
                }
                if !store.searchError.isEmpty {
                    Text(store.searchError).foregroundColor(.ocMuted)
                        .listRowBackground(Color.clear)
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background(Color.ocChatBg)
            .navigationTitle("Новый чат")
            .searchable(text: $query, prompt: "@username")
            .onSubmit(of: .search) { Task { await store.search(query) } }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Закрыть") { dismiss() } }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Найти") { Task { await store.search(query) } }
                }
            }
        }
    }
}

struct OnlineChatView: View {
    @ObservedObject var store: OnlineChatStore
    let peer: String
    @State private var draft = ""
    @State private var showProfile = false
    @State private var showFilePicker = false
    @State private var filePickerKind: OnlineFilePickerKind = .document
    @State private var showAttachmentMenu = false
    @State private var showMediaPicker = false
    @State private var showCamera = false
    @State private var selectedMedia: PhotosPickerItem?
    @State private var downloadedFile: DownloadedOnlineFile?
    @State private var previewedMedia: PreviewedOnlineMedia?
    @State private var loadingMedia = false
    @StateObject private var locationProvider = OnlineLocationProvider()
    @FocusState private var composerFocused: Bool
    @StateObject private var recorder = OnlineMessageRecorder()
    @State private var videoRecording = false
    @State private var recordPress: Date?
    @State private var recordJob: DispatchWorkItem?

    private var profile: OnlineProfile? { store.profiles[peer] }
    private var items: [OnlineMessage] { store.messages[peer] ?? [] }

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            VStack(spacing: 0) {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 6) {
                            ForEach(items) { message in
                                OnlineMessageBubble(
                                    message: message,
                                    outgoing: message.isOutgoing(for: store.username),
                                    onRetry: { Task { await store.retry(message) } },
                                    download: { reportErrors in
                                        await store.downloadFile(message, reportErrors: reportErrors)
                                    },
                                    onOpenMedia: { url in
                                        previewedMedia = PreviewedOnlineMedia(url: url, kind: message.attachment?.kind ?? "file")
                                    },
                                    onOpenFile: { url in downloadedFile = DownloadedOnlineFile(url: url) }
                                )
                                .id(message.id)
                            }
                            if store.typingPeers.contains(peer) {
                                HStack {
                                    Text("печатает…")
                                        .font(.system(size: 13))
                                        .foregroundColor(.ocMuted)
                                        .padding(.horizontal, 14)
                                        .padding(.vertical, 9)
                                        .background(Color.ocIncoming)
                                        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                                    Spacer(minLength: 70)
                                }
                            }
                        }
                        .padding(.horizontal, 10)
                        .padding(.vertical, 12)
                    }
                    .scrollDismissesKeyboard(.interactively)
                    .onTapGesture { closeAttachmentMenu() }
                    .onAppear { scrollToBottom(proxy, animated: false) }
                    .onChange(of: items) { _, _ in scrollToBottom(proxy, animated: true) }
                }
                if store.preparingFile || loadingMedia {
                    HStack(spacing: 9) {
                        ProgressView().controlSize(.small)
                        Text(loadingMedia ? "Оптимизируем медиа…" : "Подготавливаем вложение…")
                            .font(.footnote.weight(.medium))
                    }
                    .foregroundStyle(Color.ocMuted)
                    .padding(.vertical, 8)
                    .transition(.opacity)
                }
                composer
            }
            if showAttachmentMenu {
                OnlineAttachmentMenu { action in
                    chooseAttachment(action)
                }
                .padding(.leading, 10)
                .padding(.bottom, 66)
                .transition(.opacity.combined(with: .scale(scale: 0.96, anchor: .bottomLeading)))
                .zIndex(2)
            }
        }
        .background(Color.ocChatBg)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .principal) {
                Button { showProfile = true } label: {
                    HStack(spacing: 9) {
                        OnlineAvatarView(profile: profile, username: peer, size: 34)
                        VStack(alignment: .leading, spacing: 0) {
                            Text(profile?.title ?? "@\(peer)")
                                .font(.system(size: 14, weight: .semibold))
                                .foregroundColor(.ocText)
                            Text(store.typingPeers.contains(peer) ? "печатает…" : "@\(peer)")
                                .font(.caption2)
                                .foregroundColor(.ocMuted)
                        }
                    }
                }
                .buttonStyle(.plain)
            }
        }
        .sheet(isPresented: $showProfile) {
            OnlineProfileView(profile: profile, fallbackUsername: peer)
        }
        .onAppear { store.openedChat(with: peer) }
        .onDisappear { store.closedChat(with: peer) }
        .fileImporter(isPresented: $showFilePicker,
                      allowedContentTypes: filePickerKind == .audio ? [.audio] : [.item]) { result in
            switch result {
            case .success(let url): store.sendPickedFile(url, to: peer)
            case .failure(let error): store.fileError = error.localizedDescription
            }
        }
        .photosPicker(isPresented: $showMediaPicker, selection: $selectedMedia,
                      matching: .any(of: [.images, .videos]),
                      preferredItemEncoding: .automatic)
        .fullScreenCover(isPresented: $showCamera) {
            OnlineCameraPicker { image in
                showCamera = false
                guard let image else { return }
                sendCameraPhoto(image)
            }
            .ignoresSafeArea()
        }
        .sheet(item: $downloadedFile) { file in
            OnlineDownloadedFileSheet(file: file)
                .presentationDetents([.height(280)])
                .presentationDragIndicator(.visible)
        }
        .fullScreenCover(item: $previewedMedia) { media in
            OnlineMediaViewer(media: media)
        }
        .onChange(of: selectedMedia) { _, item in
            guard let item else { return }
            loadMedia(item)
        }
        .alert("Файлы", isPresented: Binding(get: { !store.fileError.isEmpty }, set: { if !$0 { store.fileError = "" } })) {
            Button("ОК") { store.fileError = "" }
        } message: { Text(store.fileError) }
    }

    private var composer: some View {
        VStack {
            if recorder.recording {
                if videoRecording { RecordingPreview(session: recorder.session).frame(width: 180, height: 180).clipShape(Circle()) }
                HStack {
                    Text("● Запись · максимум 60 секунд").foregroundStyle(.red)
                    Button("Отменить") { recorder.cancel() }
                }
            }
        HStack(alignment: .bottom, spacing: 8) {
            if draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                Image(systemName: videoRecording ? "video.fill" : "mic.fill")
                    .font(.system(size: 20))
                    .frame(width: 42, height: 42)
                    .foregroundStyle(Color.ocPrimaryFg)
                    .background(recorder.recording ? Color.red : Color.ocPrimary, in: Circle())
                    .gesture(DragGesture(minimumDistance: 0).onChanged { _ in
                        guard recordPress == nil else { return }
                        recordPress = Date()
                        let job = DispatchWorkItem {
                            recorder.start(video: videoRecording) { url in
                                guard let url else { return }
                                store.sendPickedFile(url, to: peer)
                            }
                        }
                        recordJob = job
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25, execute: job)
                    }.onEnded { _ in
                        recordJob?.cancel()
                        if let pressed = recordPress, Date().timeIntervalSince(pressed) < 0.25 { videoRecording.toggle() }
                        else { recorder.finish() }
                        recordPress = nil
                    })
                    .accessibilityLabel(videoRecording ? "Видеокружок. Удерживайте для записи" : "Голосовое. Удерживайте для записи")
                    .disabled(store.preparingFile)
            } else {
            Button {
                composerFocused = false
                withAnimation(.easeOut(duration: 0.14)) {
                    showAttachmentMenu.toggle()
                }
            } label: {
                Image(systemName: "paperclip")
                    .font(.system(size: 20, weight: .regular))
                    .frame(width: 38, height: 42)
            }
            .disabled(store.preparingFile || loadingMedia)
            .accessibilityLabel("Прикрепить фото, видео или файл до 5 МБ")
            TextField("Сообщение", text: $draft, axis: .vertical)
                .lineLimit(1...5)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(Color.ocSurfaceAlt)
                .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
                .focused($composerFocused)
                .onChange(of: draft) { _, value in
                    if !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        store.sendTyping(to: peer)
                    }
                }
            Button {
                let value = draft
                draft = ""
                Task { await store.send(value, to: peer) }
            } label: {
                Image(systemName: "arrow.up")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundColor(.ocPrimaryFg)
                    .frame(width: 42, height: 42)
                    .background(Color.ocPrimary)
                    .clipShape(Circle())
            }
            .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(.ultraThinMaterial)
        }
        .onDisappear { recordJob?.cancel(); recorder.cancel() }
        .alert("Запись", isPresented: Binding(get: { !recorder.error.isEmpty }, set: { if !$0 { recorder.error = "" } })) {
            Button("ОК") { recorder.error = "" }
        } message: { Text(recorder.error) }
    }

    private func loadMedia(_ item: PhotosPickerItem) {
        loadingMedia = true
        Task {
            defer {
                loadingMedia = false
                selectedMedia = nil
            }
            do {
                let isVideo = item.supportedContentTypes.contains { $0.conforms(to: .movie) }
                if isVideo {
                    guard let movie = try await item.loadTransferable(type: PickedOnlineMovie.self) else {
                        throw OnlineFiles.failure("Не удалось прочитать выбранное видео")
                    }
                    let prepared = try await OnlineMediaPreparation.video(at: movie.url)
                    defer {
                        try? FileManager.default.removeItem(at: movie.url)
                        if prepared.url != movie.url { try? FileManager.default.removeItem(at: prepared.url) }
                    }
                    let data = try await Task.detached(priority: .utility) { try OnlineFiles.read(prepared.url) }.value
                    await store.sendPickedMedia(data, name: prepared.name, to: peer)
                } else {
                    guard let data = try await item.loadTransferable(type: Data.self) else {
                        throw OnlineFiles.failure("Не удалось прочитать выбранную фотографию")
                    }
                    let prepared = try await OnlineMediaPreparation.photo(data)
                    await store.sendPickedMedia(prepared.data, name: prepared.name, to: peer)
                }
            } catch {
                store.fileError = error.localizedDescription
            }
        }
    }

    private func chooseAttachment(_ action: OnlineAttachmentAction) {
        closeAttachmentMenu()
        switch action {
        case .media:
            showMediaPicker = true
        case .file:
            filePickerKind = .document
            showFilePicker = true
        case .camera:
            guard UIImagePickerController.isSourceTypeAvailable(.camera) else {
                store.fileError = "Камера недоступна на этом устройстве."
                return
            }
            showCamera = true
        case .audio:
            filePickerKind = .audio
            showFilePicker = true
        case .location:
            locationProvider.requestLocation { result in
                switch result {
                case .success(let coordinate):
                    let latitude = String(format: "%.6f", coordinate.latitude)
                    let longitude = String(format: "%.6f", coordinate.longitude)
                    Task { await store.send("📍 Местоположение\nhttps://maps.apple.com/?ll=\(latitude),\(longitude)", to: peer) }
                case .failure(let error):
                    store.fileError = error.localizedDescription
                }
            }
        }
    }

    private func closeAttachmentMenu() {
        guard showAttachmentMenu else { return }
        withAnimation(.easeOut(duration: 0.12)) { showAttachmentMenu = false }
    }

    private func sendCameraPhoto(_ image: UIImage) {
        guard let data = image.jpegData(compressionQuality: 0.88) else {
            store.fileError = "Не удалось подготовить фотографию."
            return
        }
        loadingMedia = true
        Task {
            defer { loadingMedia = false }
            do {
                let prepared = try await OnlineMediaPreparation.photo(data)
                await store.sendPickedMedia(prepared.data, name: prepared.name, to: peer)
            } catch {
                store.fileError = error.localizedDescription
            }
        }
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy, animated: Bool) {
        guard let last = items.last else { return }
        let action = { proxy.scrollTo(last.id, anchor: .bottom) }
        if animated { withAnimation(.easeOut(duration: 0.2), action) } else { action() }
    }
}

enum OnlineFilePickerKind { case document, audio }

enum OnlineAttachmentAction: CaseIterable {
    case media, file, camera, audio, location

    var title: String {
        switch self {
        case .media: "Фото или видео"
        case .file: "Файл"
        case .camera: "Камера"
        case .audio: "Звук"
        case .location: "Местоположение"
        }
    }

    var symbol: String {
        switch self {
        case .media: "photo.on.rectangle.angled"
        case .file: "doc"
        case .camera: "camera"
        case .audio: "waveform"
        case .location: "location"
        }
    }
}
