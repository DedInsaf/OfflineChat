import SwiftUI
import Foundation
import CoreLocation
import CoreBluetooth
import CryptoKit

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
            Notifier.post(title: "Запрос на оффлайн-чат", body: "\(peer) хочет подключиться")
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
