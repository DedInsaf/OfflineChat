import SwiftUI
import PhotosUI

struct OnlineMessengerView: View {
    @ObservedObject var store: OnlineChatStore
    @State private var path: [String] = []
    @State private var showSearch = false
    @State private var showProfileEditor = false
    @State private var usernameDraft = ""
    @State private var nameDraft = ""
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
            Text("Ваш профиль")
                .font(.system(size: 34, weight: .bold))
                .foregroundColor(.ocText)
            Text("Создайте уникальный @username. Отображаемое имя и фотографию можно изменить в профиле.")
                .font(.system(size: 15))
                .foregroundColor(.ocMuted)
            TextField("Имя", text: $nameDraft)
                .onlineField()
            TextField("username", text: $usernameDraft)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .onlineField()
            if !store.claimError.isEmpty {
                Text(store.claimError)
                    .font(.system(size: 13))
                    .foregroundColor(.ocDanger)
            }
            Button {
                Task { await store.claim(usernameDraft, displayName: nameDraft) }
            } label: {
                HStack {
                    if store.isWorking { ProgressView().tint(.ocPrimaryFg) }
                    Text("Продолжить").fontWeight(.bold)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 13)
                .foregroundColor(.ocPrimaryFg)
                .background(Color.ocPrimary)
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            }
            .disabled(store.isWorking)
            Spacer()
        }
        .padding(24)
        .background(Color.ocChatBg.ignoresSafeArea())
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
                    Text(conversation.lastMessage?.text ?? "Начать диалог")
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

    private var profile: OnlineProfile? { store.profiles[peer] }
    private var items: [OnlineMessage] { store.messages[peer] ?? [] }

    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 6) {
                        ForEach(items) { message in
                            OnlineMessageBubble(
                                message: message,
                                outgoing: message.isOutgoing(for: store.username),
                                onRetry: { Task { await store.retry(message) } }
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
                .onAppear { scrollToBottom(proxy, animated: false) }
                .onChange(of: items) { _, _ in scrollToBottom(proxy, animated: true) }
            }
            composer
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
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: 8) {
            TextField("Сообщение", text: $draft, axis: .vertical)
                .lineLimit(1...5)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(Color.ocSurfaceAlt)
                .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
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

    private func scrollToBottom(_ proxy: ScrollViewProxy, animated: Bool) {
        guard let last = items.last else { return }
        let action = { proxy.scrollTo(last.id, anchor: .bottom) }
        if animated { withAnimation(.easeOut(duration: 0.2), action) } else { action() }
    }
}

private struct OnlineMessageBubble: View {
    let message: OnlineMessage
    let outgoing: Bool
    let onRetry: () -> Void

    var body: some View {
        HStack(alignment: .bottom) {
            if outgoing { Spacer(minLength: 54) }
            VStack(alignment: .leading, spacing: 3) {
                Text(message.text)
                    .font(.system(size: 16))
                    .foregroundColor(outgoing ? .ocPrimaryFg : .ocText)
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
    @State private var editing = false

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
                }
                Section("Подключение") {
                    LabeledContent("Статус", value: store.connectionText)
                    Text(store.serverAddress).font(.footnote).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Профиль")
            .sheet(isPresented: $editing) { OnlineProfileEditor(store: store) }
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
