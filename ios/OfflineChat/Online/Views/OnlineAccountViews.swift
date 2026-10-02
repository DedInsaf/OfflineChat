import SwiftUI
import PhotosUI

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

struct OnlineProfileView: View {
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

struct OnlineProfileEditor: View {
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

extension View {
    func onlineField() -> some View {
        self
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(Color.ocSurface)
            .clipShape(RoundedRectangle(cornerRadius: 13, style: .continuous))
    }
}
