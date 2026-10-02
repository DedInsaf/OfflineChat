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

struct RGB {
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

enum OC {
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

func sha256File(_ url: URL) throws -> String {
    let handle = try FileHandle(forReadingFrom: url)
    defer { try? handle.close() }
    var hasher = SHA256()
    while let block = try handle.read(upToCount: 1024 * 1024), !block.isEmpty {
        hasher.update(data: block)
    }
    return hasher.finalize().map { String(format: "%02x", $0) }.joined()
}

func safeFileName(_ name: String) -> String {
    let base = URL(fileURLWithPath: name).lastPathComponent
    let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: " ._-()"))
    let sanitized = base.unicodeScalars
        .map { allowed.contains($0) ? String($0) : "_" }
        .joined()
        .trimmingCharacters(in: .whitespacesAndNewlines)
    return sanitized.isEmpty ? "file" : sanitized
}

func humanBytes(_ value: Int64) -> String {
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

func parseChatPayload(_ payload: String) -> (mid: String?, body: String) {
    guard let idx = payload.firstIndex(of: "|") else { return (nil, payload) }
    let mid = String(payload[..<idx])
    let body = String(payload[payload.index(after: idx)...])
    let digits = CharacterSet.decimalDigits
    if !mid.isEmpty, !body.isEmpty, mid.unicodeScalars.allSatisfy({ digits.contains($0) }) {
        return (mid, body)
    }
    return (nil, payload)
}

func initials(for name: String) -> String {
    let parts = name.split(separator: " ").map(String.init)
    if parts.isEmpty { return "?" }
    if parts.count == 1 { return String(parts[0].prefix(2)).uppercased() }
    return String(parts[0].prefix(1) + parts[1].prefix(1)).uppercased()
}

func signalLabel(_ rssi: Int) -> String {
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
