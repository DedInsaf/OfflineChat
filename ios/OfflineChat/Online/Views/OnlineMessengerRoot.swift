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

