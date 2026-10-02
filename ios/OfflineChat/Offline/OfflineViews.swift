import SwiftUI
import UIKit

private struct RadarMark: View {
    var size: CGFloat = 40
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size * 0.3, style: .continuous)
                .fill(Color.ocPrimary)
            Circle().stroke(Color.ocPrimaryFg, lineWidth: 1.4).padding(size * 0.2)
            Circle().stroke(Color.ocPrimaryFg, lineWidth: 1.4).padding(size * 0.32)
            Circle().fill(Color.ocPrimaryFg).frame(width: size * 0.12, height: size * 0.12)
        }
        .frame(width: size, height: size)
    }
}

private struct PersonAvatar: View {
    let name: String
    var size: CGFloat = 42
    var body: some View {
        ZStack {
            Circle().fill(Color.ocIncoming)
            Text(initials(for: name))
                .font(.system(size: size < 48 ? 11 : 14, weight: .bold))
                .foregroundColor(.ocAccent)
        }
        .frame(width: size, height: size)
    }
}

private struct PillButton: View {
    let title: String
    var variant: Variant = .primary
    var fillWidth: Bool = false
    let action: () -> Void
    enum Variant { case primary, secondary, ghost, danger }
    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 14, weight: .bold))
                .foregroundColor(foreground)
                .frame(maxWidth: fillWidth ? .infinity : nil)
                .padding(.horizontal, 18)
                .padding(.vertical, 12)
                .background(background)
                .clipShape(Capsule())
        }
        .buttonStyle(.plain)
    }
    private var background: Color {
        switch variant {
        case .primary: return .ocPrimary
        case .secondary: return .ocSurfaceAlt
        case .ghost: return .ocSurface
        case .danger: return .ocDanger
        }
    }
    private var foreground: Color {
        switch variant {
        case .primary, .danger: return .ocPrimaryFg
        case .secondary: return .ocText
        case .ghost: return .ocMuted
        }
    }
}

private struct StatusChip: View {
    let text: String
    let tone: OfflineChatBluetooth.Tone
    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(color)
                .frame(width: 6, height: 6)
            Text(text)
                .font(.system(size: 12, weight: .semibold))
                .foregroundColor(color)
                .lineLimit(1)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(Color.ocSurfaceAlt)
        .clipShape(Capsule())
    }
    private var color: Color {
        switch tone {
        case .success: return .ocSuccess
        case .warning: return .ocWarning
        case .danger: return .ocDanger
        case .muted: return .ocMuted
        }
    }
}

// MARK: - Name setup

private struct NameSetupView: View {
    @ObservedObject var bluetooth: OfflineChatBluetooth
    @State private var draft = ""
    @State private var appeared = false

    var body: some View {
        ZStack {
            Color.ocBg.ignoresSafeArea()
            VStack(spacing: 0) {
                Spacer()
                VStack(alignment: .leading, spacing: 18) {
                    RadarMark(size: 56)
                    Text("КАК ВАС ПРЕДСТАВИТЬ")
                        .font(.system(size: 11, weight: .bold))
                        .tracking(1.6)
                        .foregroundColor(.ocAccent)
                    Text("Имя, которое увидят рядом")
                        .font(.system(size: 28, weight: .bold))
                        .foregroundColor(.ocText)
                        .fixedSize(horizontal: false, vertical: true)
                    Text("OfflineChat работает без интернета. Сначала назовите себя — это имя уйдёт в Bluetooth-эфир.")
                        .font(.system(size: 15))
                        .foregroundColor(.ocMuted)
                        .fixedSize(horizontal: false, vertical: true)
                    TextField("Например, Анна", text: $draft)
                        .textInputAutocapitalization(.words)
                        .disableAutocorrection(true)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 14)
                        .background(Color.ocSurfaceAlt)
                        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Color.ocLine, lineWidth: 1))
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                    PillButton(title: "Продолжить", fillWidth: true) {
                        bluetooth.saveDisplayName(draft)
                    }
                }
                .padding(24)
                .background(Color.ocSurface)
                .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
                .shadow(color: Color.black.opacity(0.06), radius: 18, y: 8)
                .padding(.horizontal, 20)
                .opacity(appeared ? 1 : 0)
                .offset(y: appeared ? 0 : 12)
                Spacer()
            }
        }
        .onAppear {
            draft = bluetooth.displayName
            withAnimation(.easeOut(duration: 0.35)) { appeared = true }
        }
    }
}

// MARK: - Discover

private struct DiscoverView: View {
    @ObservedObject var bluetooth: OfflineChatBluetooth
    @State private var editingName = false
    @State private var draft = ""

    var body: some View {
        VStack(spacing: 0) {
            header
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text("Кто рядом")
                        .font(.system(size: 28, weight: .bold))
                        .foregroundColor(.ocText)
                    Text("Bluetooth — 10–40 метров. Найдите устройство и запросите доступ.")
                        .font(.system(size: 14))
                        .foregroundColor(.ocMuted)
                    PillButton(title: bluetooth.isScanning ? "Идёт поиск…" : "Найти устройства", fillWidth: true) {
                        bluetooth.startScanning()
                    }
                    .disabled(bluetooth.isScanning)
                    .opacity(bluetooth.isScanning ? 0.7 : 1)

                    if bluetooth.devices.isEmpty {
                        VStack(spacing: 10) {
                            RadarMark(size: 48)
                            Text(bluetooth.isScanning ? "Слушаем эфир рядом с вами…" : "Список пуст. Нажмите «Найти», чтобы увидеть, кто рядом.")
                                .font(.system(size: 14))
                                .foregroundColor(.ocMuted)
                                .multilineTextAlignment(.center)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 36)
                        .background(Color.ocSurfaceAlt)
                        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                    } else {
                        VStack(spacing: 8) {
                            ForEach(bluetooth.devices) { device in
                                Button {
                                    bluetooth.connect(to: device)
                                } label: {
                                    HStack(spacing: 12) {
                                        PersonAvatar(name: device.name)
                                        VStack(alignment: .leading, spacing: 2) {
                                            Text(device.name)
                                                .font(.system(size: 15, weight: .semibold))
                                                .foregroundColor(.ocText)
                                            Text("\(signalLabel(device.rssi))  ·  \(device.rssi) дБ")
                                                .font(.system(size: 12))
                                                .foregroundColor(.ocMuted)
                                        }
                                        Spacer()
                                        Text("Связаться")
                                            .font(.system(size: 12, weight: .bold))
                                            .foregroundColor(.ocText)
                                            .padding(.horizontal, 12)
                                            .padding(.vertical, 8)
                                            .background(Color.ocSurfaceAlt)
                                            .clipShape(Capsule())
                                    }
                                    .padding(12)
                                    .background(Color.ocSurface)
                                    .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color.ocLine, lineWidth: 1))
                                    .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }

                    VStack(alignment: .leading, spacing: 8) {
                        Text("СОБЫТИЯ")
                            .font(.system(size: 11, weight: .bold))
                            .tracking(1.4)
                            .foregroundColor(.ocSubtle)
                        ForEach(Array(bluetooth.events.suffix(6).enumerated()), id: \.offset) { _, line in
                            Text("• \(line)")
                                .font(.system(size: 12))
                                .foregroundColor(.ocMuted)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .padding(.top, 8)
                    .padding(.bottom, 28)
                }
                .padding(.horizontal, 20)
                .padding(.top, 18)
            }
        }
        .background(Color.ocSurface.ignoresSafeArea())
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .center, spacing: 12) {
                RadarMark(size: 40)
                VStack(alignment: .leading, spacing: 2) {
                    Text("OfflineChat")
                        .font(.system(size: 22, weight: .bold))
                        .foregroundColor(.ocText)
                    Text(bluetooth.status)
                        .font(.system(size: 12))
                        .foregroundColor(.ocMuted)
                        .lineLimit(2)
                }
                Spacer(minLength: 8)
                StatusChip(text: chipLabel, tone: bluetooth.statusTone)
            }
            HStack(spacing: 8) {
                if editingName {
                    TextField("Имя", text: $draft)
                        .textInputAutocapitalization(.words)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 10)
                        .background(Color.ocSurfaceAlt)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                    PillButton(title: "Ок", variant: .secondary) {
                        bluetooth.saveDisplayName(draft)
                        editingName = false
                    }
                } else {
                    Button {
                        draft = bluetooth.displayName
                        editingName = true
                    } label: {
                        HStack(spacing: 6) {
                            Text(bluetooth.displayName)
                                .font(.system(size: 13, weight: .medium))
                                .foregroundColor(.ocText)
                            Image(systemName: "pencil")
                                .font(.system(size: 11, weight: .bold))
                                .foregroundColor(.ocMuted)
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(Color.ocSurfaceAlt)
                        .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .padding(.horizontal, 20)
        .padding(.top, 12)
        .padding(.bottom, 14)
        .background(Color.ocSurface)
        .overlay(alignment: .bottom) { Color.ocLine.frame(height: 1) }
    }

    private var chipLabel: String {
        if bluetooth.isConnected { return "Канал открыт" }
        if bluetooth.isScanning { return "Поиск" }
        if bluetooth.awaitingApproval { return "Ждём согласие" }
        return "Видимы рядом"
    }
}

// MARK: - Chat

private struct ChatView: View {
    @ObservedObject var bluetooth: OfflineChatBluetooth
    @State private var draft = ""
    @FocusState private var focused: Bool

    var body: some View {
        VStack(spacing: 0) {
            header
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        ForEach(bluetooth.messages) { line in
                            messageRow(line).id(line.id)
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 16)
                }
                .scrollDismissesKeyboard(.interactively)
                .onChange(of: bluetooth.messages.count) {
                    if let last = bluetooth.messages.last {
                        withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                    }
                }
            }
            .background(Color.ocChatBg)

            if !bluetooth.transferText.isEmpty {
                Text(bluetooth.transferText)
                    .font(.system(size: 12))
                    .foregroundColor(.ocMuted)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 8)
                    .background(Color.ocSurfaceAlt)
            }

            composer
        }
        .background(Color.ocChatBg.ignoresSafeArea())
    }

    private var header: some View {
        HStack(spacing: 10) {
            Button {
                bluetooth.closeChat()
            } label: {
                Image(systemName: "chevron.left")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundColor(.ocText)
                    .frame(width: 36, height: 36)
                    .background(Color.ocSurfaceAlt)
                    .clipShape(Circle())
            }
            PersonAvatar(name: bluetooth.peerName, size: 40)
            VStack(alignment: .leading, spacing: 2) {
                Text(bluetooth.peerName)
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundColor(.ocText)
                    .lineLimit(1)
                Text(bluetooth.isConnected ? "Канал чата готов" : (bluetooth.awaitingApproval ? "Ожидаем подтверждение" : bluetooth.status))
                    .font(.system(size: 12))
                    .foregroundColor(.ocMuted)
                    .lineLimit(1)
            }
            Spacer()
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(Color.ocSurface)
        .overlay(alignment: .bottom) { Color.ocLine.frame(height: 1) }
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: 8) {
            TextField(bluetooth.isConnected ? "Сообщение" : "Ждём согласие", text: $draft, axis: .vertical)
                .focused($focused)
                .disabled(!bluetooth.isConnected)
                .lineLimit(1...4)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(Color.ocSurfaceAlt)
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))

            Button {
                bluetooth.sendMessage(draft)
                draft = ""
            } label: {
                Text("Отправить")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundColor(.ocPrimaryFg)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 11)
                    .background(bluetooth.isConnected && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? Color.ocPrimary : Color.ocLine)
                    .clipShape(Capsule())
            }
            .disabled(!bluetooth.isConnected || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(Color.ocSurface)
        .overlay(alignment: .top) { Color.ocLine.frame(height: 1) }
    }

    @ViewBuilder
    private func messageRow(_ line: ChatLine) -> some View {
        switch line.kind {
        case .system(let text):
            Text(text)
                .font(.system(size: 12))
                .foregroundColor(.ocSubtle)
                .multilineTextAlignment(.center)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 6)
        case .text(let text):
            HStack {
                if line.outgoing { Spacer(minLength: 48) }
                VStack(alignment: line.outgoing ? .trailing : .leading, spacing: 4) {
                    Text(parseChatPayload(text).body)
                        .font(.system(size: 15))
                        .foregroundColor(line.outgoing ? .ocPrimaryFg : .ocText)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 10)
                        .background(line.outgoing ? Color.ocOutgoing : Color.ocIncoming)
                        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                    Text(line.outgoing ? "Вы" : String(bluetooth.peerName.split(separator: " ").first.map(String.init) ?? "Собеседник"))
                        .font(.system(size: 11))
                        .foregroundColor(.ocSubtle)
                }
                if !line.outgoing { Spacer(minLength: 48) }
            }
        case .file(let name, let size, let url):
            HStack {
                if line.outgoing { Spacer(minLength: 48) }
                VStack(alignment: .leading, spacing: 6) {
                    Text("Файл: \(name)")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(line.outgoing ? .ocPrimaryFg : .ocText)
                    Text(humanBytes(size))
                        .font(.system(size: 12))
                        .foregroundColor(line.outgoing ? Color.ocPrimaryFg.opacity(0.8) : .ocMuted)
                    if let url {
                        ShareLink(item: url) {
                            Text("Открыть")
                                .font(.system(size: 12, weight: .bold))
                                .foregroundColor(line.outgoing ? .ocPrimaryFg : .ocPrimary)
                                .padding(.horizontal, 12)
                                .padding(.vertical, 6)
                                .background(line.outgoing ? Color.white.opacity(0.12) : Color.ocSurface)
                                .clipShape(Capsule())
                        }
                    }
                }
                .padding(12)
                .background(line.outgoing ? Color.ocOutgoing : Color.ocIncoming)
                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                if !line.outgoing { Spacer(minLength: 48) }
            }
        }
    }
}

// MARK: - Incoming overlay

struct IncomingOverlay: View {
    let name: String
    let onAllow: () -> Void
    let onDeny: () -> Void

    var body: some View {
        ZStack {
            Color.black.opacity(0.55).ignoresSafeArea()
            VStack(alignment: .leading, spacing: 16) {
                PersonAvatar(name: name, size: 64)
                Text("Кто-то рядом стучится")
                    .font(.system(size: 24, weight: .bold))
                    .foregroundColor(.ocText)
                Text("\(name) хочет открыть локальный канал с вами. Пока вы не разрешите, сообщения не проходят.")
                    .font(.system(size: 15))
                    .foregroundColor(.ocMuted)
                    .fixedSize(horizontal: false, vertical: true)
                HStack {
                    PillButton(title: "Отклонить", variant: .ghost, action: onDeny)
                    Spacer()
                    PillButton(title: "Разрешить", action: onAllow)
                }
                .padding(.top, 6)
            }
            .padding(26)
            .background(Color.ocSurface)
            .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
            .padding(.horizontal, 22)
        }
    }
}

struct OfflineToolsView: View {
    var body: some View {
        NavigationStack {
            List {
                Section {
                    NavigationLink { ThemeView() } label: { Label("Тема", systemImage: "paintpalette.fill") }
                    NavigationLink { OfflineGuideView() } label: { Label("Экстренный справочник", systemImage: "cross.case.fill") }
                    NavigationLink { OfflineLocationView() } label: { Label("Карта и GPS", systemImage: "location.fill") }
                    NavigationLink { OfflineNotesView() } label: { Label("Заметки", systemImage: "note.text") }
                    NavigationLink { MedicalCardView() } label: { Label("Медицинская карточка", systemImage: "heart.text.square.fill") }
                } header: {
                    Text("БЕЗ ИНТЕРНЕТА")
                } footer: {
                    Text("Тема не следует за системной. Цвета живут только в приложении.")
                }
            }
            .scrollContentBackground(.hidden)
            .background(Color.ocChatBg)
            .navigationTitle("Оффлайн")
        }
    }
}

private func hexString(from color: Color) -> String {
    let ui = UIColor(color)
    var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
    ui.getRed(&r, green: &g, blue: &b, alpha: &a)
    return String(format: "#%02X%02X%02X", Int(r * 255), Int(g * 255), Int(b * 255))
}

private struct ThemeView: View {
    @EnvironmentObject private var theme: AppTheme
    @State private var bg: Color = Color.ocBg
    @State private var text: Color = Color.ocText
    @State private var accent: Color = Color.ocAccent

    var body: some View {
        List {
            Section("ГОТОВЫЕ") {
                HStack {
                    Button("Светлая") { theme.applyLight(); sync() }
                    Spacer()
                    Button("Тёмная") { theme.applyDark(); sync() }
                }
                .font(.system(size: 16, weight: .bold))
                .foregroundColor(.ocPrimary)
            }
            Section("СВОИ ЦВЕТА") {
                ColorPicker("Фон", selection: $bg, supportsOpacity: false)
                ColorPicker("Текст", selection: $text, supportsOpacity: false)
                ColorPicker("Акцент", selection: $accent, supportsOpacity: false)
                Button("Применить свои цвета") {
                    theme.bgHex = hexString(from: bg)
                    theme.textHex = hexString(from: text)
                    theme.accentHex = hexString(from: accent)
                    theme.applyCustom()
                }
                .font(.system(size: 16, weight: .bold))
                .foregroundColor(.ocPrimary)
            }
            Section {
                Text("Системная тема iPhone больше не перекрашивает поля и подписи. Меняется только то, что вы выбрали здесь.")
                    .font(.system(size: 13))
                    .foregroundColor(.ocMuted)
            }
        }
        .scrollContentBackground(.hidden)
        .background(Color.ocChatBg)
        .navigationTitle("Тема")
        .onAppear(perform: sync)
    }

    private func sync() {
        bg = RGB(hex: theme.bgHex).color
        text = RGB(hex: theme.textHex).color
        accent = RGB(hex: theme.accentHex).color
    }
}

private struct OfflineGuideView: View {
    private let guides = [
        ("Экстренные номера", "112 — единый номер. 101 — пожарные, 102 — полиция, 103 — скорая. 112 можно набрать без SIM и интернета."),
        ("Кровотечение", "Сильно прижмите рану чистой тканью на 10–15 минут. Жгут используйте только при сильном артериальном кровотечении и запишите время."),
        ("Нет дыхания", "Проверьте реакцию и дыхание 10 секунд. Вызовите 112. Делайте 30 нажатий на центр груди и 2 вдоха, 100–120 нажатий в минуту."),
        ("Ожог", "Охлаждайте прохладной водой 20 минут. Не прикладывайте лёд, масло или вату. Накройте чистой тканью."),
        ("Заблудились", "Остановитесь, не уходите дальше в темноте. Подайте три световых или звуковых сигнала, сохраните заряд и оставайтесь на месте.")
    ]
    @Environment(\.openURL) private var openURL

    var body: some View {
        List {
            Section {
                Button { openURL(URL(string: "tel://112")!) } label: {
                    Label("Позвонить 112", systemImage: "phone.fill")
                        .foregroundColor(.ocDanger)
                }
            }
            ForEach(guides, id: \.0) { item in
                Section(item.0) { Text(item.1).foregroundColor(.ocMuted) }
            }
        }
        .navigationTitle("Справочник")
    }
}

private struct OfflineLocationView: View {
    @StateObject private var location = OfflineLocation()
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("GPS работает со спутниками и не требует мобильного интернета.")
                .font(.system(size: 15))
                .foregroundColor(.ocMuted)
            Text(location.coordinates)
                .font(.system(size: 22, weight: .bold, design: .monospaced))
                .foregroundColor(.ocText)
                .textSelection(.enabled)
            if !location.accuracy.isEmpty { Text(location.accuracy).foregroundColor(.ocMuted) }
            if !location.errorText.isEmpty { Text(location.errorText).foregroundColor(.ocDanger) }
            PillButton(title: "Обновить GPS", fillWidth: true) { location.update() }
            Spacer()
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.ocChatBg.ignoresSafeArea())
        .navigationTitle("Карта и GPS")
    }
}

private struct OfflineNotesView: View {
    @AppStorage("offline.notes") private var notes = ""
    var body: some View {
        TextEditor(text: $notes)
            .padding(12)
            .scrollContentBackground(.hidden)
            .background(Color.ocSurfaceAlt)
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .padding(16)
            .background(Color.ocChatBg.ignoresSafeArea())
            .navigationTitle("Заметки")
    }
}

private struct MedicalCardView: View {
    @AppStorage("offline.blood") private var blood = ""
    @AppStorage("offline.allergies") private var allergies = ""
    @AppStorage("offline.meds") private var meds = ""
    @AppStorage("offline.ice") private var ice = ""
    @AppStorage("offline.medicalNote") private var note = ""
    var body: some View {
        Form {
            Section("ВАЖНОЕ") {
                TextField("Группа крови", text: $blood).foregroundColor(.ocText)
                TextField("Аллергии", text: $allergies).foregroundColor(.ocText)
                TextField("Лекарства", text: $meds).foregroundColor(.ocText)
            }
            Section("КОНТАКТ") { TextField("Кому звонить", text: $ice).foregroundColor(.ocText) }
            Section("ЗАМЕТКА") { TextEditor(text: $note).foregroundColor(.ocText).frame(minHeight: 110) }
        }
        .navigationTitle("Медкарта")
    }
}

struct OfflineChatView: View {
    @ObservedObject var bluetooth: OfflineChatBluetooth
    @State private var named = false

    var body: some View {
        ZStack {
            Color.ocBg.ignoresSafeArea()
            if !named {
                NameSetupView(bluetooth: bluetooth)
            } else if bluetooth.showChat {
                ChatView(bluetooth: bluetooth)
            } else {
                DiscoverView(bluetooth: bluetooth)
            }
        }
        .onAppear {
            named = UserDefaults.standard.string(forKey: "offlinechat.displayName")?.isEmpty == false
        }
        .onChange(of: bluetooth.displayName) {
            named = !bluetooth.displayName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
    }
}
