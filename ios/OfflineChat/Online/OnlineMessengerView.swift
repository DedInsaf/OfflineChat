import SwiftUI
import PhotosUI
import UniformTypeIdentifiers
import CoreTransferable
import AVKit
import AVFoundation
import UIKit
import CoreLocation

struct OnlineMessengerView: View {
    @ObservedObject var store: OnlineChatStore
    @State private var path: [String] = []
    @State private var showSearch = false
    @State private var showProfileEditor = false
    @State private var usernameDraft = ""
    @State private var nameDraft = ""
    @State private var emailDraft = ""
    @State private var passwordDraft = ""
    @State private var confirmationDraft = ""
    @State private var codeDraft = ""
    @State private var registering = false
    @State private var showServer = false
    @State private var serverDraft = ""

    var body: some View {
        NavigationStack(path: $path) {
            Group {
                if store.username.isEmpty {
                    onboarding
                } else {
                    conversationList
                }
            }
            .navigationDestination(for: String.self) { peer in
                OnlineChatView(store: store, peer: peer)
            }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        serverDraft = store.serverAddress
                        showServer = true
                    } label: { Image(systemName: "network") }
                    .accessibilityLabel("Подключение к серверу")
                }
            }
        }
        .task { store.start() }
        .sheet(isPresented: $showSearch) {
            OnlineSearchView(store: store) { profile in
                store.beginConversation(with: profile)
                showSearch = false
                path.append(profile.username)
            }
        }
        .sheet(isPresented: $showProfileEditor) {
            OnlineProfileEditor(store: store)
        }
        .sheet(isPresented: $showServer) {
            NavigationStack {
                Form {
                    Section("Адрес сервера") {
                        TextField("https://адрес-сервера", text: $serverDraft)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)
                        Text("На всех устройствах используется один адрес общего сервера.")
                            .font(.footnote)
                        Text("История сохраняется при переносе той же базы на другой сервер.")
                            .font(.footnote)
                    }
                    if !store.serverError.isEmpty {
                        Text(store.serverError).foregroundStyle(.red)
                    }
                    Button {
                        Task {
                            if await store.configureServer(serverDraft) { showServer = false }
                        }
                    } label: {
                        HStack {
                            if store.checkingServer { ProgressView() }
                            Text("Проверить и подключиться")
                        }
                    }
                    .disabled(store.checkingServer || store.isWorking)
                }
                .navigationTitle("Сервер")
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Закрыть") { showServer = false }
                            .disabled(store.checkingServer)
                    }
                }
                .interactiveDismissDisabled(store.checkingServer)
            }
        }
    }

    private var onboarding: some View {
        VStack(alignment: .leading, spacing: 16) {
            Spacer()
            Image(systemName: "paperplane.fill")
                .font(.system(size: 46))
                .foregroundColor(.ocPrimary)
            Text(store.authChallenge == nil ? (registering ? "Регистрация" : "Вход") : "Код из письма")
                .font(.system(size: 34, weight: .bold))
                .foregroundColor(.ocText)
            Text(authDescription)
                .font(.system(size: 15))
                .foregroundColor(.ocMuted)
            if store.authChallenge != nil {
                TextField("6-значный код", text: $codeDraft)
                    .keyboardType(.numberPad)
                    .textContentType(.oneTimeCode)
                    .onlineField()
            } else {
                if registering {
                    TextField("Имя", text: $nameDraft).onlineField()
                }
                TextField(registering ? "username" : "Юз или почта", text: $usernameDraft)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .onlineField()
                if registering {
                    TextField("Почта", text: $emailDraft)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.emailAddress)
                        .textContentType(.emailAddress)
                        .onlineField()
                }
                SecureField("Пароль", text: $passwordDraft)
                    .textContentType(registering ? .newPassword : .password)
                    .onlineField()
                if registering {
                    SecureField("Подтвердите пароль", text: $confirmationDraft)
                        .textContentType(.newPassword)
                        .onlineField()
                }
            }
            if !store.claimError.isEmpty {
                Text(store.claimError)
                    .font(.system(size: 13))
                    .foregroundColor(.ocDanger)
            }
            Button {
                Task {
                    if store.authChallenge != nil {
                        await store.verifyCode(codeDraft)
                    } else if registering {
                        await store.startRegistration(username: usernameDraft, email: emailDraft,
                                                      password: passwordDraft, confirmation: confirmationDraft,
                                                      displayName: nameDraft)
                    } else {
                        await store.startLogin(identifier: usernameDraft, password: passwordDraft)
                    }
                }
            } label: {
                HStack {
                    if store.isWorking { ProgressView().tint(.ocPrimaryFg) }
                    Text(store.authChallenge != nil ? "Подтвердить" : "Получить код").fontWeight(.bold)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 13)
                .foregroundColor(.ocPrimaryFg)
                .background(Color.ocPrimary)
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            }
            .disabled(store.isWorking)
            if store.authChallenge != nil {
                Button("Назад") {
                    store.cancelVerification()
                    codeDraft = ""
                }
                .foregroundColor(.ocAccent)
            } else {
                Button(registering ? "У меня уже есть аккаунт" : "Создать аккаунт") {
                    registering.toggle()
                    store.claimError = ""
                }
                .foregroundColor(.ocAccent)
            }
            Spacer()
        }
        .padding(24)
        .background(Color.ocChatBg.ignoresSafeArea())
    }

    private var authDescription: String {
        if let challenge = store.authChallenge {
            return "Мы отправили шестизначный код на \(challenge.emailHint). Код действует 10 минут."
        }
        if registering {
            return "Придумайте уникальный юз и пароль. Почту нужно подтвердить кодом."
        }
        return "Введите юз или почту и пароль. Для безопасности вход подтверждается кодом из письма."
    }

    private var conversationList: some View {
        List {
            if !store.claimError.isEmpty {
                Section {
                    Label(store.claimError, systemImage: "exclamationmark.triangle.fill")
                        .font(.system(size: 13))
                        .foregroundColor(.ocDanger)
                }
                .listRowBackground(Color.ocSurface)
            }
            Section {
                if store.conversations.isEmpty {
                    ContentUnavailableView(
                        "Диалогов пока нет",
                        systemImage: "message",
                        description: Text("Найдите человека по уникальному @username")
                    )
                    .listRowBackground(Color.clear)
                }
                ForEach(store.conversations) { conversation in
                    NavigationLink(value: conversation.username) {
                        OnlineConversationRow(conversation: conversation, currentUsername: store.username)
                    }
                    .listRowBackground(Color.ocSurface)
                }
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .background(Color.ocChatBg)
        .navigationTitle("Чаты")
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button { showProfileEditor = true } label: {
                    OnlineAvatarView(profile: store.myProfile, username: store.username, size: 34)
                }
            }
            ToolbarItem(placement: .principal) {
                VStack(spacing: 0) {
                    Text("Чаты").font(.headline)
                    Text(store.connectionText)
                        .font(.caption2)
                        .foregroundColor(store.connectionText == "Онлайн" ? .ocSuccess : .ocMuted)
                }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button { showSearch = true } label: {
                    Image(systemName: "square.and.pencil")
                }
            }
        }
    }
}

private struct OnlineConversationRow: View {
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

private struct OnlineSearchView: View {
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

private struct OnlineChatView: View {
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
        HStack(alignment: .bottom, spacing: 8) {
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
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(.ultraThinMaterial)
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

private enum OnlineFilePickerKind { case document, audio }

private enum OnlineAttachmentAction: CaseIterable {
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

private struct OnlineAttachmentMenu: View {
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

private final class OnlineLocationProvider: NSObject, ObservableObject, CLLocationManagerDelegate {
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

private struct OnlineCameraPicker: UIViewControllerRepresentable {
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

private struct OnlineMessageBubble: View {
    let message: OnlineMessage
    let outgoing: Bool
    let onRetry: () -> Void
    let download: (Bool) async -> URL?
    let onOpenMedia: (URL) -> Void
    let onOpenFile: (URL) -> Void
    @State private var mediaURL: URL?
    @State private var loading = false

    var body: some View {
        HStack(alignment: .bottom) {
            if outgoing { Spacer(minLength: 54) }
            VStack(alignment: .leading, spacing: 3) {
                if let attachment = message.attachment {
                    attachmentContent(attachment)
                } else {
                    Text(message.text)
                        .font(.system(size: 16))
                        .foregroundColor(outgoing ? .ocPrimaryFg : .ocText)
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
            .background(outgoing ? Color.ocOutgoing : Color.ocIncoming)
            .clipShape(RoundedRectangle(cornerRadius: 17, style: .continuous))
            .onTapGesture { if message.status == .failed { onRetry() } }
            if !outgoing { Spacer(minLength: 54) }
        }
        .task(id: message.serverID) {
            guard message.attachment?.kind == "photo", mediaURL == nil, message.serverID != nil else { return }
            await load(openWhenReady: false)
        }
    }

    @ViewBuilder
    private func attachmentContent(_ attachment: OnlineAttachment) -> some View {
        switch attachment.kind {
        case "photo":
            Button { Task { await load(openWhenReady: true) } } label: {
                ZStack {
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(Color.black.opacity(0.08))
                        .frame(width: 246, height: 184)
                    if let mediaURL, let image = UIImage(contentsOfFile: mediaURL.path) {
                        Image(uiImage: image)
                            .resizable()
                            .scaledToFill()
                            .frame(width: 246, height: 184)
                            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
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

private struct DownloadedOnlineFile: Identifiable {
    let id = UUID()
    let url: URL
}

private struct PreviewedOnlineMedia: Identifiable {
    let id = UUID()
    let url: URL
    let kind: String
}

private struct PickedOnlineMovie: Transferable {
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

private enum OnlineMediaPreparation {
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
                throw OnlineFiles.failure("Фотографию не удалось уменьшить до 5 МБ")
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
        throw OnlineFiles.failure("Видео слишком длинное. После сжатия оно всё ещё больше 5 МБ")
    }
}

private struct OnlineMediaViewer: View {
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

private struct OnlineDownloadedFileSheet: View {
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

struct OnlineReceiptView: View {
    let status: OnlineMessageStatus
    var compact = false

    var body: some View {
        Group {
            switch status {
            case .sending:
                Image(systemName: "clock")
            case .sent:
                Image(systemName: "checkmark")
            case .delivered:
                Image(systemName: "checkmark.circle")
            case .read:
                Image(systemName: "checkmark.circle.fill")
            case .failed:
                Image(systemName: "exclamationmark.circle.fill")
            }
        }
        .font(.system(size: compact ? 10 : 11, weight: .bold))
        .foregroundColor(status == .read ? .ocAccent : (status == .failed ? .ocDanger : .ocMuted))
        .accessibilityLabel(accessibilityText)
    }

    private var accessibilityText: String {
        switch status {
        case .sending: return "Отправляется"
        case .sent: return "Отправлено"
        case .delivered: return "Доставлено"
        case .read: return "Прочитано"
        case .failed: return "Не отправлено. Нажмите, чтобы повторить"
        }
    }
}

private struct OnlineProfileView: View {
    let profile: OnlineProfile?
    let fallbackUsername: String
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                OnlineAvatarView(profile: profile, username: fallbackUsername, size: 104)
                Text(profile?.title ?? "@\(fallbackUsername)")
                    .font(.title2.bold())
                    .foregroundColor(.ocText)
                Text("@\(profile?.username ?? fallbackUsername)")
                    .foregroundColor(.ocAccent)
                if let bio = profile?.bio, !bio.isEmpty {
                    Text(bio)
                        .multilineTextAlignment(.center)
                        .foregroundColor(.ocMuted)
                        .padding(.horizontal, 28)
                }
                Spacer()
            }
            .padding(.top, 28)
            .frame(maxWidth: .infinity)
            .background(Color.ocChatBg.ignoresSafeArea())
            .navigationTitle("Профиль")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Готово") { dismiss() } } }
        }
    }
}

struct OnlineAccountView: View {
    @ObservedObject var store: OnlineChatStore
    let onOpenLogin: () -> Void
    @State private var editing = false
    @State private var confirmLogout = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    VStack(spacing: 12) {
                        OnlineAvatarView(profile: store.myProfile, username: store.username, size: 88)
                        Text(store.myProfile?.title ?? "Мой профиль")
                            .font(.title2.bold())
                        Text(store.username.isEmpty ? "Создайте профиль во вкладке «Онлайн»" : "@\(store.username)")
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 20)
                }
                if !store.username.isEmpty {
                    Section("О себе") {
                        Text(store.myProfile?.bio.isEmpty == false ? store.myProfile!.bio : "Пока ничего не добавлено")
                        Button("Редактировать профиль") { editing = true }
                    }
                    Section("Аккаунт") {
                        Button("Сменить аккаунт") {
                            store.logout()
                            onOpenLogin()
                        }
                        Button("Выйти", role: .destructive) { confirmLogout = true }
                    }
                } else {
                    Section("Аккаунт") {
                        Button("Войти или зарегистрироваться") { onOpenLogin() }
                    }
                }
                Section("Подключение") {
                    LabeledContent("Статус", value: store.connectionText)
                    Text(store.serverAddress).font(.footnote).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Профиль")
            .sheet(isPresented: $editing) { OnlineProfileEditor(store: store) }
            .confirmationDialog("Выйти из аккаунта?", isPresented: $confirmLogout, titleVisibility: .visible) {
                Button("Выйти", role: .destructive) {
                    store.logout()
                    onOpenLogin()
                }
                Button("Отмена", role: .cancel) {}
            } message: {
                Text("Переписка останется на сервере. Для повторного входа понадобятся пароль и код из письма.")
            }
        }
    }
}

private struct OnlineProfileEditor: View {
    @ObservedObject var store: OnlineChatStore
    @Environment(\.dismiss) private var dismiss
    @State private var username: String
    @State private var displayName: String
    @State private var bio: String
    @State private var avatarBase64: String?
    @State private var photoItem: PhotosPickerItem?

    init(store: OnlineChatStore) {
        self.store = store
        _username = State(initialValue: store.username)
        _displayName = State(initialValue: store.myProfile?.displayName ?? "")
        _bio = State(initialValue: store.myProfile?.bio ?? "")
        _avatarBase64 = State(initialValue: store.myProfile?.avatarBase64)
    }

    private var preview: OnlineProfile {
        OnlineProfile(username: username, displayName: displayName, bio: bio, avatarBase64: avatarBase64, lastSeen: nil)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack {
                        Spacer()
                        VStack(spacing: 10) {
                            OnlineAvatarView(profile: preview, username: username, size: 96)
                            PhotosPicker(selection: $photoItem, matching: .images) {
                                Text("Изменить фото")
                            }
                            if avatarBase64 != nil {
                                Button("Удалить фото", role: .destructive) { avatarBase64 = nil }
                                    .font(.caption)
                            }
                        }
                        Spacer()
                    }
                }
                Section("Профиль") {
                    TextField("Имя", text: $displayName)
                    TextField("username", text: $username)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    TextField("О себе", text: $bio, axis: .vertical)
                        .lineLimit(2...5)
                }
                if !store.claimError.isEmpty {
                    Section { Text(store.claimError).foregroundColor(.ocDanger) }
                }
            }
            .navigationTitle("Редактировать")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Отмена") { dismiss() } }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Сохранить") {
                        Task {
                            if await store.updateProfile(
                                username: username,
                                displayName: displayName,
                                bio: bio,
                                avatarBase64: avatarBase64
                            ) { dismiss() }
                        }
                    }
                    .disabled(store.isWorking)
                }
            }
            .onChange(of: photoItem) { _, item in
                guard let item else { return }
                Task {
                    if let data = try? await item.loadTransferable(type: Data.self),
                       let encoded = AvatarEncoder.encode(data) {
                        avatarBase64 = encoded
                    }
                }
            }
        }
    }
}

private extension View {
    func onlineField() -> some View {
        self
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(Color.ocSurface)
            .clipShape(RoundedRectangle(cornerRadius: 13, style: .continuous))
    }
}
