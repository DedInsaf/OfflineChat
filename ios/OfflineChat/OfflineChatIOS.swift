/*
 OfflineChat for iPhone
 Совместим с macOS OfflineChat (тот же BLE-протокол и визуальный язык).

 Xcode:
 1. File → New → App → SwiftUI, iOS 16+, язык Swift.
 2. Удалите шаблонные App/ContentView.
 3. Положите этот файл в target.
 4. В Info добавьте ключи из комментария ниже.

 Info.plist:
   NSBluetoothAlwaysUsageDescription =
     OfflineChat использует Bluetooth для обмена сообщениями рядом.
   NSBluetoothPeripheralUsageDescription =
     OfflineChat использует Bluetooth, чтобы другие устройства могли вас найти.
   UIBackgroundModes = bluetooth-central, bluetooth-peripheral, fetch, processing
   BGTaskSchedulerPermittedIdentifiers = com.offlinechat.refresh
   NSUserNotificationsUsageDescription =
     OfflineChat показывает уведомления о новых сообщениях в онлайн-чате.
*/

import SwiftUI
import Foundation
import CoreLocation
import CoreBluetooth
import CryptoKit
import UniformTypeIdentifiers
import UIKit
import UserNotifications
import BackgroundTasks

// MARK: - Theme (не следует за системной)

private struct RGB {
    var r: Double
    var g: Double
    var b: Double
    init(hex: String) {
        let raw = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var value: UInt64 = 0
        Scanner(string: raw).scanHexInt64(&value)
        r = Double((value >> 16) & 0xFF) / 255
        g = Double((value >> 8) & 0xFF) / 255
        b = Double(value & 0xFF) / 255
    }
    init(_ r: Double, _ g: Double, _ b: Double) {
        self.r = r
        self.g = g
        self.b = b
    }
    var color: Color { Color(red: r, green: g, blue: b) }
    var hex: String {
        String(format: "#%02X%02X%02X", Int(r * 255), Int(g * 255), Int(b * 255))
    }
}

private func mix(_ a: RGB, _ b: RGB, _ t: Double) -> RGB {
    RGB(a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t)
}

private func luminance(_ c: RGB) -> Double {
    func lin(_ v: Double) -> Double { v <= 0.04045 ? v / 12.92 : pow((v + 0.055) / 1.055, 2.4) }
    return 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b)
}

final class OCPalette {
    static var shared = OCPalette.light
    let bg, surface, surfaceAlt, text, muted, subtle, line: Color
    let primary, primaryHover, primaryFg, accent: Color
    let incoming, outgoing, success, warning, danger, chatBg: Color
    let isDark: Bool

    init(bgHex: String, textHex: String, accentHex: String) {
        let bg = RGB(hex: bgHex)
        let text = RGB(hex: textHex)
        let accent = RGB(hex: accentHex)
        let dark = luminance(bg) < 0.45
        isDark = dark
        self.bg = bg.color
        surface = mix(bg, text, dark ? 0.07 : 0.05).color
        surfaceAlt = mix(bg, text, dark ? 0.13 : 0.09).color
        self.text = text.color
        muted = mix(text, bg, 0.38).color
        subtle = mix(text, bg, 0.55).color
        line = mix(bg, text, 0.2).color
        primary = accent.color
        primaryHover = mix(accent, dark ? text : bg, 0.16).color
        primaryFg = (luminance(accent) < 0.45 ? RGB(hex: "#F4F1EA") : RGB(hex: "#121418")).color
        self.accent = accent.color
        incoming = mix(mix(bg, text, dark ? 0.13 : 0.09), accent, 0.1).color
        outgoing = accent.color
        success = accent.color
        warning = RGB(hex: "#E0B05A").color
        danger = RGB(hex: "#E25B5B").color
        chatBg = mix(bg, accent, 0.04).color
    }

    static let light = OCPalette(bgHex: "#EFEAE2", textHex: "#1C1915", accentHex: "#1F4F46")
    static let dark = OCPalette(bgHex: "#0B0F14", textHex: "#E8EEF4", accentHex: "#3EE0B4")
}

extension Color {
    static var ocBg: Color { OCPalette.shared.bg }
    static var ocSurface: Color { OCPalette.shared.surface }
    static var ocSurfaceAlt: Color { OCPalette.shared.surfaceAlt }
    static var ocText: Color { OCPalette.shared.text }
    static var ocMuted: Color { OCPalette.shared.muted }
    static var ocSubtle: Color { OCPalette.shared.subtle }
    static var ocLine: Color { OCPalette.shared.line }
    static var ocPrimary: Color { OCPalette.shared.primary }
    static var ocPrimaryHover: Color { OCPalette.shared.primaryHover }
    static var ocPrimaryFg: Color { OCPalette.shared.primaryFg }
    static var ocAccent: Color { OCPalette.shared.accent }
    static var ocIncoming: Color { OCPalette.shared.incoming }
    static var ocOutgoing: Color { OCPalette.shared.outgoing }
    static var ocSuccess: Color { OCPalette.shared.success }
    static var ocWarning: Color { OCPalette.shared.warning }
    static var ocDanger: Color { OCPalette.shared.danger }
    static var ocChatBg: Color { OCPalette.shared.chatBg }
}

final class AppTheme: ObservableObject {
    @Published var preset: String
    @Published var bgHex: String
    @Published var textHex: String
    @Published var accentHex: String
    @Published var stamp = 0

    var scheme: ColorScheme { OCPalette.shared.isDark ? .dark : .light }

    init() {
        let defaults = UserDefaults.standard
        preset = defaults.string(forKey: "theme.preset") ?? "light"
        bgHex = defaults.string(forKey: "theme.bg") ?? "#EFEAE2"
        textHex = defaults.string(forKey: "theme.text") ?? "#1C1915"
        accentHex = defaults.string(forKey: "theme.accent") ?? "#1F4F46"
        apply(save: false)
    }

    func applyLight() { preset = "light"; bgHex = "#EFEAE2"; textHex = "#1C1915"; accentHex = "#1F4F46"; apply() }
    func applyDark() { preset = "dark"; bgHex = "#0B0F14"; textHex = "#E8EEF4"; accentHex = "#3EE0B4"; apply() }
    func applyCustom() { preset = "custom"; apply() }

    func apply(save: Bool = true) {
        let run = {
            if self.preset == "light" { OCPalette.shared = .light }
            else if self.preset == "dark" { OCPalette.shared = .dark }
            else { OCPalette.shared = OCPalette(bgHex: self.bgHex, textHex: self.textHex, accentHex: self.accentHex) }
            self.stamp += 1
            if save {
                let defaults = UserDefaults.standard
                defaults.set(self.preset, forKey: "theme.preset")
                defaults.set(self.bgHex, forKey: "theme.bg")
                defaults.set(self.textHex, forKey: "theme.text")
                defaults.set(self.accentHex, forKey: "theme.accent")
            }
        }
        if Thread.isMainThread { run() } else { DispatchQueue.main.async(execute: run) }
    }
}

private final class NotificationPresenter: NSObject, UNUserNotificationCenterDelegate {
    static let shared = NotificationPresenter()
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification, withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound, .badge, .list])
    }
}

enum Notifier {
    static func request() {
        UNUserNotificationCenter.current().delegate = NotificationPresenter.shared
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
    }
    static func post(title: String, body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        content.threadIdentifier = "online-chat"
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
    }
}

private enum OC {
    static let serviceUUID = CBUUID(string: "8F3A1000-7A91-4C91-AF20-000000000001")
    static let characteristicUUID = CBUUID(string: "8F3A1000-7A91-4C91-AF20-000000000002")
    static let appName = "OfflineChat"
    static let connectRequest = "OC_CONNECT_REQUEST|"
    static let connectAccept = "OC_CONNECT_ACCEPT|"
    static let connectDeny = "OC_CONNECT_DENY|"
    static let connectAck = "OC_CONNECT_ACK|"
    static let message = "OC_MESSAGE|"
    static let typing = "OC_TYPING|"
    static let delivered = "OC_DELIV|"
    static let read = "OC_READ|"
    static let fileMeta = "OC_FILE_META|"
    static let fileReady = "OC_FILE_READY|"
    static let fileChunk = "OC_FILE_CHUNK|"
    static let fileAck = "OC_FILE_ACK|"
    static let fileEnd = "OC_FILE_END|"
    static let fileCancel = "OC_FILE_CANCEL|"
    static let fileDeny = "OC_FILE_DENY|"
    static let frameMagic = Data([0x4F, 0x43, 0x46, 0x31]) // OCF1
    static let binMagic = Data([0x4F, 0x43, 0x42, 0x31]) // OCB1
    static let ackMagic = Data([0x4F, 0x43, 0x41, 0x31]) // OCA1
    static let frameHeader = 8
    static let frameLength = 18
    static let binHeader = 8
    static let fileChunkBytes = 48
    static let fileWindow = 8
    static let fileAckEvery = 4
    static let maxFileBytes = 25 * 1024 * 1024
    static let maxRetries = 6
    static let ackTimeout: TimeInterval = 6
}

private func sha256File(_ url: URL) throws -> String {
    let handle = try FileHandle(forReadingFrom: url)
    defer { try? handle.close() }
    var hasher = SHA256()
    while let block = try handle.read(upToCount: 1024 * 1024), !block.isEmpty {
        hasher.update(data: block)
    }
    return hasher.finalize().map { String(format: "%02x", $0) }.joined()
}

private func safeFileName(_ name: String) -> String {
    let base = URL(fileURLWithPath: name).lastPathComponent
    let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: " ._-()"))
    let sanitized = base.unicodeScalars
        .map { allowed.contains($0) ? String($0) : "_" }
        .joined()
        .trimmingCharacters(in: .whitespacesAndNewlines)
    return sanitized.isEmpty ? "file" : sanitized
}

private func humanBytes(_ value: Int64) -> String {
    let units = ["Б", "КБ", "МБ", "ГБ"]
    var number = Double(value)
    for unit in units {
        if number < 1024 || unit == units.last {
            return unit == "Б" ? "\(Int(number)) \(unit)" : String(format: "%.1f %@", number, unit)
        }
        number /= 1024
    }
    return "\(value) Б"
}

private func parseChatPayload(_ payload: String) -> (mid: String?, body: String) {
    guard let idx = payload.firstIndex(of: "|") else { return (nil, payload) }
    let mid = String(payload[..<idx])
    let body = String(payload[payload.index(after: idx)...])
    let digits = CharacterSet.decimalDigits
    if !mid.isEmpty, !body.isEmpty, mid.unicodeScalars.allSatisfy({ digits.contains($0) }) {
        return (mid, body)
    }
    return (nil, payload)
}

private func initials(for name: String) -> String {
    let parts = name.split(separator: " ").map(String.init)
    if parts.isEmpty { return "?" }
    if parts.count == 1 { return String(parts[0].prefix(2)).uppercased() }
    return String(parts[0].prefix(1) + parts[1].prefix(1)).uppercased()
}

private func signalLabel(_ rssi: Int) -> String {
    if rssi >= -45 { return "рядом" }
    if rssi >= -60 { return "в паре метров" }
    if rssi >= -75 { return "слабый сигнал" }
    return "на грани"
}

// MARK: - Models

struct OfflineDevice: Identifiable, Equatable {
    let id: UUID
    var name: String
    var rssi: Int
}

struct ChatLine: Identifiable, Equatable {
    enum Kind: Equatable {
        case text(String)
        case file(name: String, size: Int64, url: URL?)
        case system(String)
    }
    let id: UUID
    let kind: Kind
    let outgoing: Bool
    var status: String
    var mid: String?
    init(id: UUID = UUID(), kind: Kind, outgoing: Bool, status: String = "sent", mid: String? = nil) {
        self.id = id
        self.kind = kind
        self.outgoing = outgoing
        self.status = status
        self.mid = mid
    }
}

struct IncomingRequest: Identifiable, Equatable {
    let id = UUID()
    let name: String
}

final class OfflineLocation: NSObject, ObservableObject, CLLocationManagerDelegate {
    @Published var coordinates = "Координаты ещё не определены"
    @Published var accuracy = ""
    @Published var errorText = ""
    private let manager = CLLocationManager()

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBest
    }

    func update() {
        let status = manager.authorizationStatus
        if status == .notDetermined { manager.requestWhenInUseAuthorization() }
        else if status == .denied || status == .restricted { errorText = "Разрешите геопозицию в Настройках iPhone." }
        else { manager.requestLocation() }
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        DispatchQueue.main.async {
            if manager.authorizationStatus == .authorizedAlways || manager.authorizationStatus == .authorizedWhenInUse {
                manager.requestLocation()
            }
        }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let point = locations.last else { return }
        DispatchQueue.main.async {
            self.coordinates = String(format: "%.5f, %.5f", point.coordinate.latitude, point.coordinate.longitude)
            self.accuracy = "Точность около \(Int(point.horizontalAccuracy)) м"
            self.errorText = ""
        }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        DispatchQueue.main.async {
            self.errorText = "Не удалось получить координаты: \(error.localizedDescription)"
        }
    }
}

// MARK: - BLE framing (как на Mac: 20 байт, OCF1)

private final class FrameAssembler {
    private var frames: [UInt16: (total: UInt8, parts: [UInt8: Data], last: Date)] = [:]
    private var nextID: UInt16 = 1

    func newID() -> UInt16 {
        let current = nextID
        nextID = nextID == 0xFFFF ? 1 : nextID + 1
        if nextID == 0 { nextID = 1 }
        return current
    }

    func makeFrames(_ text: String, frameLength: Int = OC.frameLength) -> [Data] {
        let bytes = Array(text.data(using: .utf8) ?? Data())
        let length = max(OC.frameHeader + 1, min(max(frameLength, 20), 512))
        let payload = length - OC.frameHeader
        let total = max(1, Int(ceil(Double(max(bytes.count, 1)) / Double(payload))))
        guard total <= 255 else { return [] }
        let messageID = newID()
        return (0..<total).map { sequence in
            let start = sequence * payload
            let end = min(start + payload, bytes.count)
            var packet = OC.frameMagic
            packet.append(UInt8(messageID >> 8))
            packet.append(UInt8(messageID & 0xFF))
            packet.append(UInt8(sequence))
            packet.append(UInt8(total))
            if start < end {
                packet.append(contentsOf: bytes[start..<end])
            }
            return packet
        }
    }

    func accept(_ data: Data) -> String? {
        guard data.count >= OC.frameHeader, data.prefix(4) == OC.frameMagic else {
            return String(data: data, encoding: .utf8)
        }
        let bytes = Array(data)
        let messageID = (UInt16(bytes[4]) << 8) | UInt16(bytes[5])
        let sequence = bytes[6]
        let total = bytes[7]
        guard total > 0, sequence < total else { return nil }
        var entry = frames[messageID] ?? (total: total, parts: [:], last: Date())
        guard entry.total == total else {
            frames.removeValue(forKey: messageID)
            return nil
        }
        entry.parts[sequence] = Data(bytes.dropFirst(OC.frameHeader))
        entry.last = Date()
        frames[messageID] = entry
        frames = frames.filter { Date().timeIntervalSince($0.value.last) < 60 }
        guard entry.parts.count == Int(total) else { return nil }
        var assembled = Data()
        for index in 0..<Int(total) {
            if let part = entry.parts[UInt8(index)] { assembled.append(part) }
        }
        frames.removeValue(forKey: messageID)
        return String(data: assembled, encoding: .utf8)
    }
}

// MARK: - Bluetooth

final class OfflineChatBluetooth: NSObject, ObservableObject {
    @Published var devices: [OfflineDevice] = []
    @Published var messages: [ChatLine] = []
    @Published var events: [String] = ["Приложение запущено."]
    @Published var status = "Ожидание системного Bluetooth"
    @Published var statusTone: Tone = .warning
    @Published var isConnected = false
    @Published var isScanning = false
    @Published var awaitingApproval = false
    @Published var transferText = ""
    @Published var peerName = "Собеседник"
    @Published var showChat = false
    @Published var pendingConnection: IncomingRequest?
    @Published var displayName: String
    @Published var peerTyping = false

    enum Tone { case success, warning, danger, muted }

    private let bleQueue = DispatchQueue(label: "com.offlinechat.bluetooth", qos: .userInitiated)
    private var central: CBCentralManager!
    private var peripheralManager: CBPeripheralManager!
    private var mutableCharacteristic: CBMutableCharacteristic?
    private var connectedPeripheral: CBPeripheral?
    private var connectedCharacteristic: CBCharacteristic?
    private var subscribedCentral: CBCentral?
    private var centralAssembler = FrameAssembler()
    private var peripheralAssembler = FrameAssembler()
    private var peripheralServiceReady = false
    private var centralApproved = false
    private var peripheralApproved = false
    private var pendingPeerName: String?
    private var discovered: [UUID: CBPeripheral] = [:]
    private var pendingWrites: [Data] = []
    private var isWriting = false
    private var pendingNotifies: [Data] = []
    private var pendingRawWrites: [Data] = []
    private var notifyEnabled = false
    private var pendingConnectRequest = false
    private var acceptAcked = false
    private var acceptTries = 0
    private var notifyFrameLength = OC.frameLength
    private var completedFileIDs: [String: Date] = [:]

    private final class IncomingFile {
        let id: String
        let name: String
        let size: Int64
        let sha256: String
        let tempURL: URL
        let handle: FileHandle
        var received: Int64 = 0
        var nextSequence = 0
        var hasher = SHA256()
        var pending: [Int: Data] = [:]
        var lastAck = -1
        init(id: String, name: String, size: Int64, sha256: String, tempURL: URL, handle: FileHandle) {
            self.id = id
            self.name = name
            self.size = size
            self.sha256 = sha256
            self.tempURL = tempURL
            self.handle = handle
        }
    }

    private final class OutgoingFile {
        enum Phase { case waitingReady, waitingChunkAck, waitingEndAck }
        let id: String
        let name: String
        let size: Int64
        let sha256: String
        let handle: FileHandle
        var phase: Phase = .waitingReady
        var sequence = 0
        var sent: Int64 = 0
        var lastPacket = ""
        var retryCount = 0
        var ackToken = UUID()
        var inFlight: [Int: Data] = [:]
        var highestAck = -1
        var eof = false
        var chunkBytes = 160
        init(id: String, name: String, size: Int64, sha256: String, handle: FileHandle) {
            self.id = id
            self.name = name
            self.size = size
            self.sha256 = sha256
            self.handle = handle
        }
    }

    private var incomingFile: IncomingFile?
    private var outgoingFile: OutgoingFile?

    override init() {
        let stored = UserDefaults.standard.string(forKey: "offlinechat.displayName")?.trimmingCharacters(in: .whitespacesAndNewlines)
        displayName = (stored?.isEmpty == false) ? stored! : UIDevice.current.name
        super.init()
        central = CBCentralManager(delegate: self, queue: bleQueue, options: [
            CBCentralManagerOptionShowPowerAlertKey: true
        ])
        peripheralManager = CBPeripheralManager(delegate: self, queue: bleQueue, options: [
            CBPeripheralManagerOptionShowPowerAlertKey: true
        ])
    }

    private func onMain(_ block: @escaping () -> Void) {
        if Thread.isMainThread { block() } else { DispatchQueue.main.async(execute: block) }
    }

    private func log(_ text: String) {
        onMain {
            self.events.append(text)
            if self.events.count > 40 { self.events.removeFirst(self.events.count - 40) }
        }
    }

    func setStatus(_ text: String, _ tone: Tone = .muted) {
        onMain {
            self.status = text
            self.statusTone = tone
        }
    }

    func saveDisplayName(_ name: String) {
        let clean = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let value = clean.isEmpty ? UIDevice.current.name : String(clean.prefix(18))
        UserDefaults.standard.set(value, forKey: "offlinechat.displayName")
        onMain { self.displayName = value }
        bleQueue.async {
            guard self.peripheralServiceReady else { return }
            self.peripheralManager.stopAdvertising()
            self.startAdvertising()
        }
        log("Имя обновлено: \(value).")
        setStatus("Имя обновлено: \(value)", .success)
    }

    func startScanning() {
        bleQueue.async {
            guard self.central.state == .poweredOn else {
                self.setStatus("Включите Bluetooth", .danger)
                return
            }
            self.onMain {
                self.devices.removeAll()
                self.isScanning = true
            }
            self.discovered.removeAll()
            self.central.scanForPeripherals(withServices: [OC.serviceUUID], options: [
                CBCentralManagerScanOptionAllowDuplicatesKey: false
            ])
            self.setStatus("Сканирование рядом находящихся устройств", .warning)
            self.log("Начат поиск устройств.")
            self.bleQueue.asyncAfter(deadline: .now() + 10) { [weak self] in
                guard let self, self.isScanning else { return }
                self.central.stopScan()
                self.onMain { self.isScanning = false }
                self.setStatus("Поиск завершён. Можно выбрать найденное устройство", .success)
                self.log("Поиск остановлен.")
            }
        }
    }

    func connect(to device: OfflineDevice) {
        bleQueue.async {
            guard self.central.state == .poweredOn else {
                self.setStatus("Включите Bluetooth", .danger)
                return
            }
            let peripheral = self.discovered[device.id]
                ?? self.central.retrievePeripherals(withIdentifiers: [device.id]).first
            guard let peripheral else {
                self.setStatus("Устройство не найдено", .danger)
                return
            }
            self.discovered[device.id] = peripheral
            if self.central.isScanning { self.central.stopScan() }
            self.onMain {
                self.isScanning = false
                self.peerName = device.name
                self.awaitingApproval = true
                self.isConnected = false
                self.messages = [ChatLine(kind: .system("Чат с \(device.name) открыт."), outgoing: false)]
                self.showChat = true
            }
            self.setStatus("Подключаюсь к \(device.name)", .warning)
            self.log("Подключение к \(device.name).")
            if peripheral.state == .connected {
                self.connectedPeripheral = peripheral
                peripheral.delegate = self
                peripheral.discoverServices([OC.serviceUUID])
            } else {
                self.central.connect(peripheral, options: nil)
            }
        }
    }

    func approveIncoming() {
        bleQueue.async {
            guard self.subscribedCentral != nil else { return }
            self.peripheralApproved = true
            self.acceptAcked = false
            self.acceptTries = 0
            let name = self.pendingPeerName ?? "Собеседник"
            self.sendAccept()
            self.onMain {
                self.peerName = name
                self.isConnected = true
                self.awaitingApproval = false
                self.showChat = true
                self.pendingConnection = nil
                self.messages = [ChatLine(kind: .system("Чат с \(name) открыт."), outgoing: false)]
            }
            self.setStatus("Канал чата готов", .success)
            self.log("Подключение разрешено: \(name).")
        }
    }

    private func sendAccept() {
        acceptTries += 1
        sendProtocol(OC.connectAccept + displayName, forceNotify: true)
        bleQueue.asyncAfter(deadline: .now() + 0.45) { [weak self] in
            guard let self else { return }
            guard self.peripheralApproved, !self.acceptAcked, self.acceptTries < 8 else { return }
            self.sendAccept()
        }
    }

    func denyIncoming() {
        bleQueue.async {
            self.peripheralApproved = false
            self.sendProtocol(OC.connectDeny + "Подключение отклонено")
            self.onMain {
                self.pendingConnection = nil
                self.isConnected = false
            }
            self.setStatus("Вы отклонили входящее подключение", .danger)
            self.log("Входящее подключение отклонено.")
        }
    }

    func closeChat() {
        onMain {
            self.showChat = false
        }
    }

    func sendMessage(_ text: String) {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return }
        let mid = String(Int(Date().timeIntervalSince1970 * 1000) % 100_000_000)
        onMain {
            self.messages.append(ChatLine(kind: .text(value), outgoing: true, status: "sending", mid: mid))
        }
        bleQueue.async {
            guard self.centralApproved || self.peripheralApproved else {
                self.setStatus("Сообщение ожидает разрешения собеседника.", .warning)
                return
            }
            self.sendProtocol(OC.message + mid + "|" + value)
            self.onMain {
                if let index = self.messages.lastIndex(where: { $0.mid == mid }) {
                    self.messages[index].status = "sent"
                }
            }
            self.log("Сообщение отправлено.")
        }
    }

    func pingTyping() {
        bleQueue.async {
            guard self.centralApproved || self.peripheralApproved else { return }
            self.sendProtocol(OC.typing + "1")
        }
    }

    func sendFile(from url: URL) {
        bleQueue.async {
            guard self.centralApproved || self.peripheralApproved else {
                self.setStatus("Сначала подключитесь к собеседнику", .danger)
                return
            }
            do {
                let values = try url.resourceValues(forKeys: [.fileSizeKey])
                let size = Int64(values.fileSize ?? 0)
                let name = safeFileName(url.lastPathComponent)
                guard size > 0 else { throw OCError("Нельзя отправить пустой файл") }
                guard size <= Int64(OC.maxFileBytes) else {
                    throw OCError("Максимум для BLE: \(humanBytes(Int64(OC.maxFileBytes)))")
                }
                guard self.outgoingFile == nil else { throw OCError("Уже передаётся другой файл") }
                let checksum = try sha256File(url)
                let handle = try FileHandle(forReadingFrom: url)
                let id = UUID().uuidString
                let state = OutgoingFile(id: id, name: name, size: size, sha256: checksum, handle: handle)
                self.outgoingFile = state
                self.onMain {
                    self.messages.append(ChatLine(kind: .file(name: name, size: size, url: url), outgoing: true))
                }
                let metadata: [String: Any] = [
                    "id": id,
                    "name": name,
                    "size": size,
                    "sha256": checksum,
                    "mtime": Int(Date().timeIntervalSince1970),
                    "chunk_bytes": OC.fileChunkBytes
                ]
                let json = try JSONSerialization.data(withJSONObject: metadata)
                guard let jsonText = String(data: json, encoding: .utf8) else { throw OCError("Не удалось упаковать метаданные") }
                state.lastPacket = OC.fileMeta + jsonText
                state.phase = .waitingReady
                self.sendProtocol(state.lastPacket)
                self.scheduleTimeout(for: state)
                self.onMain { self.transferText = "Отправляю файл: \(name) · \(humanBytes(size))" }
                self.log("Начата отправка файла \(name).")
            } catch {
                self.setStatus("Не удалось отправить файл: \(error.localizedDescription)", .danger)
            }
        }
    }

    private struct OCError: LocalizedError {
        let errorDescription: String?
        init(_ text: String) { errorDescription = text }
    }

    private func packetData(_ text: String, framedWith assembler: FrameAssembler, frameLength: Int) -> [Data] {
        guard let raw = text.data(using: .utf8) else { return [] }
        let limit = max(20, dataMTU())
        if raw.count <= limit, !raw.starts(with: OC.frameMagic) {
            return [raw]
        }
        return assembler.makeFrames(text, frameLength: frameLength)
    }

    private func sendProtocol(_ text: String, forceNotify: Bool = false, forceWrite: Bool = false) {
        let useNotify = forceNotify || (peripheralApproved && subscribedCentral != nil && !forceWrite)
        let useWrite = forceWrite || (centralApproved && connectedPeripheral != nil && connectedCharacteristic != nil && !forceNotify)

        if useNotify, subscribedCentral != nil {
            let frames = packetData(text, framedWith: peripheralAssembler, frameLength: notifyFrameLength)
            guard !frames.isEmpty else {
                setStatus("Служебный пакет слишком большой", .danger)
                return
            }
            pendingNotifies.append(contentsOf: frames)
            flushNotifies()
            return
        }
        if useWrite, connectedPeripheral != nil, connectedCharacteristic != nil {
            let frames = packetData(text, framedWith: centralAssembler, frameLength: OC.frameLength)
            guard !frames.isEmpty else {
                setStatus("Служебный пакет слишком большой", .danger)
                return
            }
            pendingWrites.append(contentsOf: frames)
            flushWrites()
            return
        }
        if subscribedCentral != nil {
            let frames = packetData(text, framedWith: peripheralAssembler, frameLength: notifyFrameLength)
            pendingNotifies.append(contentsOf: frames)
            flushNotifies()
        } else if connectedPeripheral != nil, connectedCharacteristic != nil {
            let frames = packetData(text, framedWith: centralAssembler, frameLength: OC.frameLength)
            pendingWrites.append(contentsOf: frames)
            flushWrites()
        }
    }

    private func flushWrites() {
        guard !isWriting else { return }
        guard let peripheral = connectedPeripheral, peripheral.state == .connected,
              let characteristic = connectedCharacteristic else { return }
        guard let frame = pendingWrites.first else { return }
        isWriting = true
        let canRespond = characteristic.properties.contains(.write)
        peripheral.writeValue(frame, for: characteristic, type: canRespond ? .withResponse : .withoutResponse)
        if !canRespond {
            pendingWrites.removeFirst()
            isWriting = false
            bleQueue.async { [weak self] in self?.flushWrites() }
        }
    }

    private func flushNotifies() {
        guard let characteristic = mutableCharacteristic, let central = subscribedCentral else { return }
        while let frame = pendingNotifies.first {
            if peripheralManager.updateValue(frame, for: characteristic, onSubscribedCentrals: [central]) {
                pendingNotifies.removeFirst()
            } else {
                return
            }
        }
    }

    private func handleProtocol(_ text: String) {
        if text.hasPrefix(OC.connectRequest) {
            let name = String(text.dropFirst(OC.connectRequest.count)).trimmingCharacters(in: .whitespacesAndNewlines)
            let peer = name.isEmpty ? "Собеседник" : name
            pendingPeerName = peer
            if peripheralApproved {
                sendAccept()
                return
            }
            if pendingConnection != nil {
                return
            }
            peripheralApproved = false
            onMain {
                self.pendingConnection = IncomingRequest(name: peer)
            }
            setStatus("\(peer) хочет подключиться", .warning)
            log("\(peer) хочет подключиться.")
            return
        }
        if text.hasPrefix(OC.connectAck) {
            acceptAcked = true
            peripheralApproved = true
            onMain {
                self.isConnected = true
                self.awaitingApproval = false
            }
            return
        }
        if text.hasPrefix(OC.connectAccept) {
            let name = String(text.dropFirst(OC.connectAccept.count)).trimmingCharacters(in: .whitespacesAndNewlines)
            centralApproved = true
            onMain {
                if !name.isEmpty { self.peerName = name }
                self.isConnected = true
                self.awaitingApproval = false
                self.showChat = true
            }
            setStatus("Канал чата готов", .success)
            log("Канал чата готов.")
            return
        }
        if text.hasPrefix(OC.connectDeny) {
            centralApproved = false
            let reason = String(text.dropFirst(OC.connectDeny.count)).trimmingCharacters(in: .whitespacesAndNewlines)
            onMain {
                self.isConnected = false
                self.awaitingApproval = false
                self.messages.append(ChatLine(kind: .system(reason.isEmpty ? "Подключение отклонено" : reason), outgoing: false))
            }
            setStatus(reason.isEmpty ? "Подключение отклонено" : reason, .danger)
            return
        }
        if text.hasPrefix(OC.message) {
            if !centralApproved && !peripheralApproved {
                centralApproved = true
                peripheralApproved = true
                onMain {
                    self.isConnected = true
                    self.awaitingApproval = false
                    self.showChat = true
                }
            }
            let payload = String(text.dropFirst(OC.message.count))
            let parsed = parseChatPayload(payload)
            onMain { self.messages.append(ChatLine(kind: .text(parsed.body), outgoing: false, mid: parsed.mid)) }
            if let mid = parsed.mid {
                sendProtocol(OC.delivered + mid)
                if showChat { sendProtocol(OC.read + mid) }
            }
            if !showChat {
                Notifier.post(title: peerName, body: parsed.body)
            }
            setStatus("Новое сообщение", .success)
            return
        }
        if text.hasPrefix(OC.typing) {
            onMain {
                self.peerTyping = true
            }
            bleQueue.asyncAfter(deadline: .now() + 3.2) { [weak self] in
                self?.onMain { self?.peerTyping = false }
            }
            return
        }
        if text.hasPrefix(OC.delivered) {
            let mid = String(text.dropFirst(OC.delivered.count))
            onMain {
                if let index = self.messages.lastIndex(where: { $0.mid == mid && $0.outgoing }) {
                    self.messages[index].status = "delivered"
                }
            }
            return
        }
        if text.hasPrefix(OC.read) {
            onMain {
                for i in self.messages.indices where self.messages[i].outgoing {
                    self.messages[i].status = "read"
                }
            }
            return
        }
        if text.hasPrefix(OC.fileReady) {
            let id = String(text.dropFirst(OC.fileReady.count)).trimmingCharacters(in: .whitespacesAndNewlines)
            guard let state = outgoingFile, state.id == id else { return }
            state.phase = .waitingChunkAck
            sendNextChunk()
            return
        }
        if text.hasPrefix(OC.fileAck) {
            let payload = String(text.dropFirst(OC.fileAck.count))
            let fields = payload.split(separator: "|", maxSplits: 1).map(String.init)
            guard fields.count == 2, let state = outgoingFile, fields[0] == state.id else { return }
            if fields[1] == "END", state.phase == .waitingEndAck {
                finishOutgoing(success: true, reason: nil)
            } else if Int(fields[1]).map({ $0 + 1 }) == state.sequence, state.phase == .waitingChunkAck {
                state.retryCount = 0
                sendNextChunk()
            }
            return
        }
        if text.hasPrefix(OC.fileDeny) {
            let payload = String(text.dropFirst(OC.fileDeny.count))
            let fields = payload.split(separator: "|", maxSplits: 1).map(String.init)
            let reason = fields.count > 1 ? fields[1] : payload
            if let state = outgoingFile, fields.first == state.id || fields.count == 1 {
                finishOutgoing(success: false, reason: reason)
            }
            return
        }
        if text.hasPrefix(OC.fileMeta) {
            handleIncomingMeta(String(text.dropFirst(OC.fileMeta.count)))
            return
        }
        if text.hasPrefix(OC.fileChunk) {
            handleIncomingChunk(String(text.dropFirst(OC.fileChunk.count)))
            return
        }
        if text.hasPrefix(OC.fileEnd) {
            handleIncomingEnd(String(text.dropFirst(OC.fileEnd.count)))
            return
        }
        if text.hasPrefix(OC.fileCancel) {
            cancelIncoming(String(text.dropFirst(OC.fileCancel.count)).trimmingCharacters(in: .whitespacesAndNewlines))
            return
        }
        if text.hasPrefix("OC_") { return }
        let parsed = parseChatPayload(text)
        onMain { self.messages.append(ChatLine(kind: .text(parsed.body), outgoing: false, mid: parsed.mid)) }
    }

    private func packBinChunk(_ seq: Int, _ payload: Data) -> Data {
        var packet = OC.binMagic
        packet.append(contentsOf: [
            UInt8((seq >> 24) & 0xFF),
            UInt8((seq >> 16) & 0xFF),
            UInt8((seq >> 8) & 0xFF),
            UInt8(seq & 0xFF)
        ])
        packet.append(payload)
        return packet
    }

    private func packBinAck(_ seq: Int) -> Data {
        var packet = OC.ackMagic
        packet.append(contentsOf: [
            UInt8((seq >> 24) & 0xFF),
            UInt8((seq >> 16) & 0xFF),
            UInt8((seq >> 8) & 0xFF),
            UInt8(seq & 0xFF)
        ])
        return packet
    }

    private func parseBin(_ data: Data) -> (isAck: Bool, seq: Int, payload: Data)? {
        guard data.count >= OC.binHeader else { return nil }
        let magic = data.prefix(4)
        guard magic == OC.binMagic || magic == OC.ackMagic else { return nil }
        let bytes = Array(data)
        let seq = (Int(bytes[4]) << 24) | (Int(bytes[5]) << 16) | (Int(bytes[6]) << 8) | Int(bytes[7])
        return (magic == OC.ackMagic, seq, Data(data.dropFirst(OC.binHeader)))
    }

    private func dataMTU() -> Int {
        if let peripheral = connectedPeripheral {
            return max(20, min(512, peripheral.maximumWriteValueLength(for: .withoutResponse)))
        }
        if let central = subscribedCentral {
            return max(20, min(512, central.maximumUpdateValueLength))
        }
        return 20
    }

    private func sendRaw(_ data: Data) {
        if connectedPeripheral != nil, connectedCharacteristic != nil {
            pendingRawWrites.append(data)
            flushRawWrites()
            return
        }
        if subscribedCentral != nil {
            pendingNotifies.append(data)
            flushNotifies()
        }
    }

    private func flushRawWrites() {
        guard let peripheral = connectedPeripheral, let characteristic = connectedCharacteristic else { return }
        while let frame = pendingRawWrites.first {
            if !peripheral.canSendWriteWithoutResponse { return }
            peripheral.writeValue(frame, for: characteristic, type: .withoutResponse)
            pendingRawWrites.removeFirst()
        }
    }

    private func ingestRaw(_ data: Data, asCentral: Bool) {
        if let parsed = parseBin(data) {
            if parsed.isAck {
                handleBinAck(parsed.seq)
            } else {
                handleBinChunk(parsed.seq, parsed.payload)
            }
            return
        }
        let assembler = asCentral ? centralAssembler : peripheralAssembler
        if let text = assembler.accept(data) { handleProtocol(text) }
    }

    private func handleBinAck(_ seq: Int) {
        guard let state = outgoingFile else { return }
        if seq > state.highestAck { state.highestAck = seq }
        for key in state.inFlight.keys where key <= state.highestAck {
            state.inFlight.removeValue(forKey: key)
        }
        state.retryCount = 0
        sendNextChunk()
    }

    private func handleBinChunk(_ seq: Int, _ payload: Data) {
        guard let state = incomingFile, !payload.isEmpty else { return }
        if seq < state.nextSequence {
            sendRaw(packBinAck(state.nextSequence - 1))
            return
        }
        if seq != state.nextSequence {
            if state.pending.count < 48 { state.pending[seq] = payload }
            return
        }
        func commit(_ blob: Data) {
            do {
                try state.handle.write(contentsOf: blob)
                state.hasher.update(data: blob)
                state.received += Int64(blob.count)
                state.nextSequence += 1
            } catch {
                sendProtocol(OC.fileDeny + "\(state.id)|Ошибка записи")
                cancelIncoming(state.id)
            }
        }
        commit(payload)
        while let blob = state.pending.removeValue(forKey: state.nextSequence) {
            commit(blob)
        }
        if state.nextSequence % OC.fileAckEvery == 0 || state.received >= state.size {
            sendRaw(packBinAck(state.nextSequence - 1))
        }
        onMain { self.transferText = "\(state.name): \(humanBytes(state.received)) из \(humanBytes(state.size))" }
    }

    private func sendNextChunk() {
        guard let state = outgoingFile else { return }
        if state.phase == .waitingEndAck { return }
        do {
            let chunkBytes = max(8, dataMTU() - OC.binHeader)
            while !state.eof, state.inFlight.count < OC.fileWindow {
                let data = try state.handle.read(upToCount: chunkBytes) ?? Data()
                if data.isEmpty {
                    state.eof = true
                    break
                }
                let packet = packBinChunk(state.sequence, data)
                state.inFlight[state.sequence] = packet
                sendRaw(packet)
                state.sent += Int64(data.count)
                state.sequence += 1
            }
            let sent = state.sent
            onMain { self.transferText = "\(state.name): \(humanBytes(sent)) из \(humanBytes(state.size))" }
            if state.eof, state.inFlight.isEmpty {
                state.phase = .waitingEndAck
                state.lastPacket = OC.fileEnd + "\(state.id)|\(state.sha256)"
                sendProtocol(state.lastPacket)
                state.retryCount = 0
                scheduleTimeout(for: state)
                onMain { self.transferText = "Проверка файла…" }
                return
            }
            if !state.inFlight.isEmpty {
                scheduleTimeout(for: state)
            }
        } catch {
            finishOutgoing(success: false, reason: error.localizedDescription)
        }
    }

    private func scheduleTimeout(for state: OutgoingFile) {
        let token = UUID()
        state.ackToken = token
        bleQueue.asyncAfter(deadline: .now() + OC.ackTimeout) { [weak self, weak state] in
            guard let self, let state, self.outgoingFile === state, state.ackToken == token else { return }
            guard state.retryCount < OC.maxRetries else {
                self.sendProtocol(OC.fileCancel + state.id)
                self.finishOutgoing(success: false, reason: "Получатель не подтвердил пакет")
                return
            }
            state.retryCount += 1
            if state.phase == .waitingEndAck {
                self.sendProtocol(state.lastPacket)
            } else if let lowest = state.inFlight.keys.min(), let packet = state.inFlight[lowest] {
                self.sendRaw(packet)
            }
            self.scheduleTimeout(for: state)
        }
    }

    private func finishOutgoing(success: Bool, reason: String?) {
        guard let state = outgoingFile else { return }
        try? state.handle.close()
        outgoingFile = nil
        onMain { self.transferText = "" }
        if success {
            setStatus("Файл отправлен: \(state.name)", .success)
            log("Файл отправлен: \(state.name).")
        } else {
            setStatus("Ошибка файла: \(reason ?? "передача прервана")", .danger)
            log("Файл отклонён: \(reason ?? "передача прервана")")
        }
    }

    private func handleIncomingMeta(_ jsonText: String) {
        guard centralApproved || peripheralApproved else {
            sendProtocol(OC.fileDeny + "Подключение не подтверждено")
            return
        }
        guard let data = jsonText.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let id = object["id"] as? String,
              let name = object["name"] as? String else { return }
        let size: Int64
        if let number = object["size"] as? NSNumber {
            size = number.int64Value
        } else if let int = object["size"] as? Int {
            size = Int64(int)
        } else {
            return
        }
        let checksum = ((object["sha256"] as? String) ?? "").lowercased()
        let cleanName = safeFileName(name)
        guard !id.isEmpty, id.count <= 80, size > 0, size <= Int64(OC.maxFileBytes) else {
            sendProtocol(OC.fileDeny + "\(id)|Файл имеет недопустимый размер")
            return
        }
        guard checksum.count == 64, checksum.unicodeScalars.allSatisfy({ "0123456789abcdef".unicodeScalars.contains($0) }) else {
            sendProtocol(OC.fileDeny + "\(id)|Некорректная контрольная сумма")
            return
        }
        if let current = incomingFile { cancelIncoming(current.id) }
        do {
            let directory = try FileManager.default.url(for: .cachesDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
            let tempURL = directory.appendingPathComponent(".offlinechat-\(id).part")
            if FileManager.default.fileExists(atPath: tempURL.path) {
                try FileManager.default.removeItem(at: tempURL)
            }
            FileManager.default.createFile(atPath: tempURL.path, contents: nil)
            let handle = try FileHandle(forWritingTo: tempURL)
            incomingFile = IncomingFile(id: id, name: cleanName, size: size, sha256: checksum, tempURL: tempURL, handle: handle)
            sendProtocol(OC.fileReady + id)
            setStatus("Получаю файл: \(cleanName) · \(humanBytes(size))", .warning)
            log("Начат приём файла \(cleanName).")
        } catch {
            sendProtocol(OC.fileDeny + "\(id)|Не удалось создать временный файл")
        }
    }

    private func handleIncomingChunk(_ payload: String) {
        let fields = payload.split(separator: "|", maxSplits: 2).map(String.init)
        guard fields.count == 3, let state = incomingFile, fields[0] == state.id, let sequence = Int(fields[1]) else { return }
        if sequence < state.nextSequence {
            sendProtocol(OC.fileAck + "\(state.id)|\(sequence)")
            return
        }
        guard sequence == state.nextSequence, let data = Data(base64Encoded: fields[2]), !data.isEmpty else { return }
        guard state.received + Int64(data.count) <= state.size else {
            sendProtocol(OC.fileDeny + "\(state.id)|Повреждённый размер чанка")
            cancelIncoming(state.id)
            return
        }
        do {
            try state.handle.write(contentsOf: data)
            state.hasher.update(data: data)
            state.received += Int64(data.count)
            state.nextSequence += 1
            sendProtocol(OC.fileAck + "\(state.id)|\(sequence)")
            onMain { self.transferText = "\(state.name): \(humanBytes(state.received)) из \(humanBytes(state.size))" }
        } catch {
            sendProtocol(OC.fileDeny + "\(state.id)|Ошибка записи")
            cancelIncoming(state.id)
        }
    }

    private func handleIncomingEnd(_ payload: String) {
        let fields = payload.split(separator: "|", maxSplits: 1).map(String.init)
        guard fields.count == 2 else { return }
        let id = fields[0]
        if let done = completedFileIDs[id], Date().timeIntervalSince(done) < 120 {
            sendProtocol(OC.fileAck + "\(id)|END")
            return
        }
        guard let state = incomingFile, state.id == id else { return }
        incomingFile = nil
        do {
            try state.handle.synchronize()
            try state.handle.close()
            let running = state.hasher.finalize().map { String(format: "%02x", $0) }.joined()
            let fileHash = try sha256File(state.tempURL)
            guard state.received == state.size,
                  running == state.sha256,
                  fileHash == state.sha256,
                  fields[1].lowercased() == state.sha256 else {
                try? FileManager.default.removeItem(at: state.tempURL)
                sendProtocol(OC.fileDeny + "\(state.id)|Контрольная сумма или размер не совпали")
                setStatus("Получен повреждённый файл", .danger)
                return
            }
            let documents = try FileManager.default.url(for: .documentDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
            let directory = documents.appendingPathComponent("OfflineChat", isDirectory: true)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            var destination = directory.appendingPathComponent(state.name)
            var counter = 1
            while FileManager.default.fileExists(atPath: destination.path) {
                let stem = destination.deletingPathExtension().lastPathComponent
                let ext = destination.pathExtension
                let suffix = ext.isEmpty ? "" : ".\(ext)"
                destination = directory.appendingPathComponent("\(stem) (\(counter))\(suffix)")
                counter += 1
            }
            try FileManager.default.moveItem(at: state.tempURL, to: destination)
            completedFileIDs[id] = Date()
            sendProtocol(OC.fileAck + "\(state.id)|END")
            onMain {
                self.messages.append(ChatLine(kind: .file(name: state.name, size: state.size, url: destination), outgoing: false))
                self.transferText = ""
                if !self.showChat {
                    self.showChat = true
                }
            }
            setStatus("Файл сохранён: \(state.name)", .success)
            log("Файл сохранён: \(state.name).")
        } catch {
            try? FileManager.default.removeItem(at: state.tempURL)
            sendProtocol(OC.fileDeny + "\(id)|Не удалось сохранить файл")
            setStatus("Не удалось сохранить файл", .danger)
        }
    }

    private func cancelIncoming(_ id: String) {
        guard let state = incomingFile, state.id == id || id.isEmpty else { return }
        incomingFile = nil
        try? state.handle.close()
        try? FileManager.default.removeItem(at: state.tempURL)
    }

    private func startAdvertising() {
        peripheralManager.startAdvertising([
            CBAdvertisementDataLocalNameKey: "\(OC.appName): \(displayName.prefix(18))",
            CBAdvertisementDataServiceUUIDsKey: [OC.serviceUUID]
        ])
    }

    private func resetLink(message: String) {
        connectedPeripheral = nil
        connectedCharacteristic = nil
        pendingWrites.removeAll()
        pendingNotifies.removeAll()
        pendingRawWrites.removeAll()
        isWriting = false
        if let state = outgoingFile {
            sendProtocol(OC.fileCancel + state.id)
            finishOutgoing(success: false, reason: "Bluetooth-соединение разорвано")
        }
        if let incoming = incomingFile { cancelIncoming(incoming.id) }
        onMain {
            self.isConnected = false
            self.awaitingApproval = false
            if self.showChat {
                self.messages.append(ChatLine(kind: .system("Собеседник отключился."), outgoing: false))
            }
        }
        setStatus(message, .danger)
        log(message)
    }
}

extension OfflineChatBluetooth: CBCentralManagerDelegate, CBPeripheralDelegate {
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        setStatus(central.state == .poweredOn ? "Bluetooth работает" : "Включите Bluetooth", central.state == .poweredOn ? .success : .danger)
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral, advertisementData: [String: Any], rssi RSSI: NSNumber) {
        let raw = peripheral.name ?? advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? OC.appName
        let prefix = "\(OC.appName): "
        let name = raw.hasPrefix(prefix) ? String(raw.dropFirst(prefix.count)) : (raw == OC.appName ? "OfflineChat user" : raw)
        discovered[peripheral.identifier] = peripheral
        let device = OfflineDevice(id: peripheral.identifier, name: name.isEmpty ? "Собеседник" : name, rssi: RSSI.intValue)
        onMain {
            if let index = self.devices.firstIndex(where: { $0.id == device.id }) {
                self.devices[index] = device
            } else {
                self.devices.append(device)
                self.log("Найдено устройство \(device.name), сигнал \(device.rssi).")
            }
        }
        setStatus("Найдено устройство: \(device.name)", .success)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        connectedPeripheral = peripheral
        centralApproved = false
        pendingWrites.removeAll()
        pendingRawWrites.removeAll()
        isWriting = false
        peripheral.delegate = self
        setStatus("Ожидаем подтверждение на другом устройстве", .warning)
        log("Соединение установлено, отправляется запрос доступа.")
        peripheral.discoverServices([OC.serviceUUID])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        setStatus("Не удалось подключиться", .danger)
        onMain { self.awaitingApproval = false }
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        resetLink(message: "Собеседник отключился")
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard error == nil else { return }
        peripheral.services?.filter { $0.uuid == OC.serviceUUID }.forEach {
            peripheral.discoverCharacteristics([OC.characteristicUUID], for: $0)
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didModifyServices invalidatedServices: [CBService]) {
        guard invalidatedServices.contains(where: { $0.uuid == OC.serviceUUID }) else { return }
        log("Сервис на устройстве изменился, ищу заново.")
        connectedCharacteristic = nil
        notifyEnabled = false
        peripheral.discoverServices([OC.serviceUUID])
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard error == nil,
              let characteristic = service.characteristics?.first(where: { $0.uuid == OC.characteristicUUID }) else { return }
        connectedCharacteristic = characteristic
        notifyEnabled = false
        pendingConnectRequest = true
        isWriting = false
        pendingWrites.removeAll()
        peripheral.setNotifyValue(true, for: characteristic)
        setStatus("На другом устройстве нужно разрешить подключение", .warning)
        log("Характеристика найдена, запрос доступа чуть позже.")
        bleQueue.asyncAfter(deadline: .now() + 0.2) { [weak self] in
            guard let self, self.connectedCharacteristic?.uuid == OC.characteristicUUID else { return }
            self.sendProtocol(OC.connectRequest + self.displayName, forceWrite: true)
            self.log("Запрос доступа отправлен.")
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        if let error {
            setStatus("Не удалось включить уведомления: \(error.localizedDescription)", .danger)
            return
        }
        notifyEnabled = characteristic.isNotifying
        guard characteristic.isNotifying, pendingConnectRequest else { return }
        pendingConnectRequest = false
        sendProtocol(OC.connectRequest + displayName, forceWrite: true)
        log("Запрос на подключение отправлен.")
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard error == nil, let data = characteristic.value else { return }
        ingestRaw(data, asCentral: true)
    }

    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        if !pendingWrites.isEmpty { pendingWrites.removeFirst() }
        isWriting = false
        if let error {
            log("Запись BLE: \(error.localizedDescription)")
        }
        flushWrites()
        flushRawWrites()
    }

    func peripheralIsReady(toSendWriteWithoutResponse peripheral: CBPeripheral) {
        flushRawWrites()
    }
}

extension OfflineChatBluetooth: CBPeripheralManagerDelegate {
    func peripheralManagerDidUpdateState(_ peripheral: CBPeripheralManager) {
        guard peripheral.state == .poweredOn else {
            setStatus("Bluetooth peripheral недоступен", .danger)
            return
        }
        if mutableCharacteristic == nil {
            let characteristic = CBMutableCharacteristic(
                type: OC.characteristicUUID,
                properties: [.read, .write, .writeWithoutResponse, .notify],
                value: nil,
                permissions: [.readable, .writeable]
            )
            mutableCharacteristic = characteristic
            let service = CBMutableService(type: OC.serviceUUID, primary: true)
            service.characteristics = [characteristic]
            peripheralManager.add(service)
        } else if peripheralServiceReady {
            startAdvertising()
        }
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, didAdd service: CBService, error: Error?) {
        guard error == nil else {
            setStatus("Не удалось создать Bluetooth-сервис", .danger)
            return
        }
        peripheralServiceReady = true
        startAdvertising()
    }

    func peripheralManagerDidStartAdvertising(_ peripheral: CBPeripheralManager, error: Error?) {
        setStatus(error == nil ? "OfflineChat доступен" : "Ошибка Bluetooth-рекламы", error == nil ? .success : .danger)
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, didReceiveWrite requests: [CBATTRequest]) {
        for request in requests {
            if let value = request.value, !value.isEmpty {
                ingestRaw(value, asCentral: false)
            }
            if request.characteristic.properties.contains(.write) {
                peripheral.respond(to: request, withResult: .success)
            }
        }
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, central: CBCentral, didSubscribeTo characteristic: CBCharacteristic) {
        subscribedCentral = central
        peripheralApproved = false
        acceptAcked = false
        notifyFrameLength = max(OC.frameHeader + 1, min(OC.frameLength, central.maximumUpdateValueLength))
        setStatus("Входящее подключение ожидает подтверждения", .warning)
        log("Входящее подключение, notifyMTU=\(central.maximumUpdateValueLength).")
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, central: CBCentral, didUnsubscribeFrom characteristic: CBCharacteristic) {
        subscribedCentral = nil
        peripheralApproved = false
        if let incoming = incomingFile { cancelIncoming(incoming.id) }
        onMain {
            self.isConnected = false
            if self.showChat {
                self.messages.append(ChatLine(kind: .system("Собеседник отключился."), outgoing: false))
            }
        }
        setStatus("Собеседник отключился", .danger)
    }
}

// MARK: - Shared chrome

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

private struct IncomingOverlay: View {
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
    @StateObject private var bluetooth = OfflineChatBluetooth()
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
            if let request = bluetooth.pendingConnection {
                IncomingOverlay(
                    name: request.name,
                    onAllow: { bluetooth.approveIncoming() },
                    onDeny: { bluetooth.denyIncoming() }
                )
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
