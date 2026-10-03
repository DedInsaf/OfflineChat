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
    @State private var recordingLocked = false
    @State private var recordingCancelled = false
    @State private var recordedDraft: URL?
    @State private var replyTo: OnlineMessage?
    @State private var selecting = false
    @State private var selectedIDs: Set<UUID> = []
    @State private var forwarding: [OnlineMessage] = []
    @State private var showForwardPicker = false

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
                                    onOpenFile: { url in downloadedFile = DownloadedOnlineFile(url: url) },
                                    onOpenReply: { id in
                                        if let target = items.first(where: { $0.id.uuidString.lowercased() == id.lowercased() }) {
                                            withAnimation { proxy.scrollTo(target.id, anchor: .center) }
                                        }
                                    }
                                )
                                .overlay {
                                    if selecting {
                                        RoundedRectangle(cornerRadius: 14).fill(selectedIDs.contains(message.id) ? Color.ocPrimary.opacity(0.14) : Color.clear)
                                            .contentShape(Rectangle())
                                            .onTapGesture { toggleSelection(message) }
                                    }
                                }
                                .contextMenu {
                                    Button { UIPasteboard.general.string = message.copyText } label: { Label("Скопировать", systemImage: "doc.on.doc") }
                                    Button { beginForwarding([message]) } label: { Label("Переслать", systemImage: "arrowshape.turn.up.right") }
                                    Button { selecting = true; selectedIDs.insert(message.id) } label: { Label("Выбрать", systemImage: "checkmark.circle") }
                                    Button { replyTo = message; composerFocused = true } label: { Label("Ответить", systemImage: "arrowshape.turn.up.left") }
                                    if let location = message.content.location {
                                        Button("Яндекс Карты") { openYandexLocation(location) }
                                        Link("2ГИС", destination: location.twoGISURL)
                                    }
                                }
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
                    .simultaneousGesture(TapGesture().onEnded { closeAttachmentMenu() })
                    .onAppear { scrollToBottom(proxy, animated: false) }
                    .onChange(of: items) { old, new in
                        if !selecting && old.last?.id != new.last?.id { scrollToBottom(proxy, animated: true) }
                    }
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
            ToolbarItemGroup(placement: .topBarTrailing) {
                if selecting {
                    Button { UIPasteboard.general.string = selectedItems.map(\.copyText).joined(separator: "\n") } label: { Image(systemName: "doc.on.doc") }.disabled(selectedIDs.isEmpty)
                    Button { beginForwarding(selectedItems) } label: { Image(systemName: "arrowshape.turn.up.right") }.disabled(selectedIDs.isEmpty)
                    Button("Готово") { selecting = false; selectedIDs.removeAll() }
                }
            }
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
        .sheet(isPresented: $showForwardPicker) {
            OnlineForwardPicker(store: store) { recipient in
                let messages = forwarding
                forwarding = []
                selecting = false
                selectedIDs.removeAll()
                Task { await store.forward(messages, to: recipient) }
            }
        }
        .onAppear { store.openedChat(with: peer) }
        .onDisappear { store.closedChat(with: peer) }
        .fileImporter(isPresented: $showFilePicker,
                      allowedContentTypes: filePickerKind == .audio ? [.audio] : [.item]) { result in
            switch result {
            case .success(let url): store.sendPickedFile(url, to: peer, body: attachmentBody())
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
            if let replyTo {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Ответ @" + replyTo.sender).font(.caption.weight(.semibold))
                        Text(replyTo.previewText).font(.caption).lineLimit(2)
                    }.foregroundStyle(Color.ocText)
                    Spacer()
                    Button { self.replyTo = nil } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(Color.ocMuted) }
                }.padding(10).background(Color.ocSurfaceAlt)
            }
            if recorder.recording {
                if videoRecording { RecordingPreview(session: recorder.session).frame(width: 180, height: 180).clipShape(Circle()) }
                HStack {
                    TimelineView(.periodic(from: .now, by: 0.2)) { _ in
                        Text("● " + recorder.durationText).monospacedDigit().foregroundStyle(.red)
                    }
                    Text(recordingLocked ? "Запись закреплена" : "← отмена · ↑ закрепить").font(.caption)
                    Button("Отменить") { discardRecording() }
                    if recordingLocked {
                        Button("Прослушать") { recorder.finish() }
                        Button("Отправить") { recordingLocked = false; recorder.finish() }
                    }
                }
            }
            if let recordedDraft {
                RecordedMessageView(url: recordedDraft, circle: videoRecording)
                HStack {
                    Button("Удалить", role: .destructive) { try? FileManager.default.removeItem(at: recordedDraft); self.recordedDraft = nil }
                    Button("Отправить") { store.sendPickedFile(recordedDraft, to: peer, body: attachmentBody()); self.recordedDraft = nil }
                }
            }
        HStack(alignment: .bottom, spacing: 8) {
            attachmentButton
            TextField("Сообщение", text: $draft, axis: .vertical)
                .lineLimit(1...5)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(Color.ocSurfaceAlt)
                .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
                .focused($composerFocused)
                .disabled(recorder.recording)
                .onChange(of: draft) { _, value in
                    if !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { store.sendTyping(to: peer) }
                }
            if draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                Image(systemName: videoRecording ? "video.fill" : "mic.fill")
                    .font(.system(size: 20))
                    .frame(width: 42, height: 42)
                    .foregroundStyle(Color.ocPrimaryFg)
                    .background(recorder.recording ? Color.red : Color.ocPrimary, in: Circle())
                    .gesture(DragGesture(minimumDistance: 0).onChanged { gesture in
                        if gesture.translation.width < -80 && !recordingLocked {
                            recordingCancelled = true
                            recordJob?.cancel()
                            recorder.cancel()
                            return
                        }
                        if gesture.translation.height < -65 && !recordingCancelled {
                            recordingLocked = true
                        }
                        guard !recordingCancelled else { return }
                        guard recordPress == nil else { return }
                        recordPress = Date()
                        let job = DispatchWorkItem {
                            recorder.start(video: videoRecording) { url in
                                guard let url else { return }
                                if recordingLocked { recordedDraft = url; recordingLocked = false }
                                else { store.sendPickedFile(url, to: peer, body: attachmentBody()) }
                            }
                        }
                        recordJob = job
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25, execute: job)
                    }.onEnded { _ in
                        recordJob?.cancel()
                        if recordingCancelled { recordingCancelled = false }
                        else if recordingLocked {
                            if !recorder.recording {
                                recorder.start(video: videoRecording) { url in
                                    guard let url else { return }
                                    if recordingLocked { recordedDraft = url; recordingLocked = false }
                                    else { store.sendPickedFile(url, to: peer, body: attachmentBody()) }
                                }
                            }
                        }
                        else if let pressed = recordPress, Date().timeIntervalSince(pressed) < 0.25 { videoRecording.toggle() }
                        else { recorder.finish() }
                        recordPress = nil
                    })
                    .accessibilityLabel(videoRecording ? "Видеокружок. Удерживайте для записи" : "Голосовое. Удерживайте для записи")
                    .disabled(store.preparingFile || recordingLocked || recordedDraft != nil)
            } else {
            Button {
                let value = OnlineMessageContent(text: draft, reply: replyTo.map(OnlineQuote.init)).encoded
                draft = ""
                replyTo = nil
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
        .onDisappear { discardRecording() }
        .onChange(of: recorder.recording) { _, recording in
            if !recording { recordPress = nil; recordJob = nil }
        }
        .alert("Запись", isPresented: Binding(get: { !recorder.error.isEmpty }, set: { if !$0 { recorder.error = "" } })) {
            Button("ОК") { recorder.error = "" }
        } message: { Text(recorder.error) }
    }

    private func discardRecording() {
        recordJob?.cancel()
        recordPress = nil
        recordJob = nil
        recordingCancelled = false
        recordingLocked = false
        recorder.cancel()
        if let recordedDraft { try? FileManager.default.removeItem(at: recordedDraft) }
        recordedDraft = nil
    }

    private var attachmentButton: some View {
        Button {
            composerFocused = false
            withAnimation(.easeOut(duration: 0.14)) { showAttachmentMenu.toggle() }
        } label: {
            Image(systemName: "paperclip").font(.system(size: 20)).frame(width: 38, height: 42)
        }
        .disabled(store.preparingFile || loadingMedia || recorder.recording)
        .accessibilityLabel("Прикрепить")
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
                    await store.sendPickedMedia(data, name: prepared.name, to: peer, body: attachmentBody())
                } else {
                    guard let data = try await item.loadTransferable(type: Data.self) else {
                        throw OnlineFiles.failure("Не удалось прочитать выбранную фотографию")
                    }
                    let prepared = try await OnlineMediaPreparation.photo(data)
                    await store.sendPickedMedia(prepared.data, name: prepared.name, to: peer, body: attachmentBody())
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
                    let body = OnlineMessageContent(text: "", reply: replyTo.map(OnlineQuote.init),
                        location: OnlineLocation(latitude: coordinate.latitude, longitude: coordinate.longitude)).encoded
                    replyTo = nil
                    Task { await store.send(body, to: peer) }
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
                await store.sendPickedMedia(prepared.data, name: prepared.name, to: peer, body: attachmentBody())
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

    private var selectedItems: [OnlineMessage] { items.filter { selectedIDs.contains($0.id) } }
    private func toggleSelection(_ message: OnlineMessage) {
        if selectedIDs.contains(message.id) { selectedIDs.remove(message.id) }
        else { selectedIDs.insert(message.id) }
    }
    private func beginForwarding(_ messages: [OnlineMessage]) {
        forwarding = messages
        showForwardPicker = true
    }
    private func attachmentBody() -> String {
        let body = OnlineMessageContent(text: "", reply: replyTo.map(OnlineQuote.init)).encoded
        replyTo = nil
        return body
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
