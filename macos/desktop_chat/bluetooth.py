"""CoreBluetooth transport used by the macOS application."""

from .shared import *


def ble_worker(status_queue, command_queue):
    log("[BLE] Поток запущен")
    from Foundation import NSObject, NSRunLoop, NSDate, NSData
    from CoreBluetooth import (
        CBPeripheralManager, CBMutableService, CBMutableCharacteristic, CBUUID,
        CBCharacteristicPropertyRead, CBCharacteristicPropertyWrite, CBCharacteristicPropertyNotify,
        CBAttributePermissionsReadable, CBAttributePermissionsWriteable, CBCentralManager,
        CBAdvertisementDataLocalNameKey, CBAdvertisementDataServiceUUIDsKey,
    )
    CBCharacteristicPropertyWriteWithoutResponse = 0x04
    SERVICE_UUID = CBUUID.UUIDWithString_(SERVICE_UUID_STRING)
    CHARACTERISTIC_UUID = CBUUID.UUIDWithString_(CHARACTERISTIC_UUID_STRING)
    FRAME_MAGIC = b"OCF1"
    FRAME_HEADER_BYTES = 8
    FRAME_BYTES = 20

    def pump(seconds=0.01):
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(seconds))

    def nsd(data):
        return NSData.alloc().initWithBytes_length_(bytes(data), len(data))

    class FrameAssembler:
        def __init__(self):
            self.frames = {}
            self.next_id = 1

        def new_message_id(self):
            value = self.next_id
            self.next_id = 1 if self.next_id >= 0xFFFF else self.next_id + 1
            return value

        def accept(self, raw, handler):
            raw = bytes(raw or b"")
            if len(raw) < FRAME_HEADER_BYTES or raw[:4] != FRAME_MAGIC:
                try:
                    text = raw.decode("utf-8")
                except Exception:
                    return
                if text:
                    handler(text)
                return
            msg_id = (raw[4] << 8) | raw[5]
            seq, total = raw[6], raw[7]
            if total == 0 or seq >= total:
                return
            entry = self.frames.setdefault(msg_id, {"total": total, "parts": {}, "last": time.time()})
            if entry["total"] != total:
                self.frames.pop(msg_id, None)
                return
            entry["parts"][seq] = raw[FRAME_HEADER_BYTES:]
            entry["last"] = time.time()
            if len(entry["parts"]) != total:
                return
            payload = b"".join(entry["parts"].get(i, b"") for i in range(total))
            self.frames.pop(msg_id, None)
            try:
                handler(payload.decode("utf-8"))
            except Exception as exc:
                log(f"[BLE] assemble: {exc}")

        def make_frames(self, text, frame_len=FRAME_BYTES):
            data = text.encode("utf-8")
            payload = max(1, frame_len - FRAME_HEADER_BYTES)
            total = max(1, (len(data) + payload - 1) // payload)
            if total > 255:
                raise ValueError("Слишком длинное сообщение")
            msg_id = self.new_message_id()
            frames = []
            for seq in range(total):
                chunk = data[seq * payload:(seq + 1) * payload]
                frames.append(FRAME_MAGIC + bytes([(msg_id >> 8) & 0xFF, msg_id & 0xFF, seq, total]) + chunk)
            return frames

    class PeripheralDelegate(NSObject):
        def initWithQueue_(self, sq):
            self = self.init()
            if self is not None:
                self.status_queue = sq
                self.manager = None
                self.characteristic = None
                self.has_subscriber = False
                self.connection_approved = False
                self.pending_peer_name = None
                self.local_name = default_display_name()
                self.service_added = False
                self.assembler = FrameAssembler()
                self.notify_frame_bytes = FRAME_BYTES
                self.notify_max = 182
                self.notify_queue = []
                self._flushing_notify = False
                self.accept_acked = False
                self.accept_tries = 0
                self.next_msg_id = 1
                self.next_accept_at = 0
                self.sos_active = False
            return self

        def send_event(self, event, message, **extra):
            data = {"event": event, "message": message}
            data.update(extra)
            try:
                self.status_queue.put(data)
            except Exception:
                pass

        def peripheralManagerDidUpdateState_(self, peripheral):
            state = peripheral.state()
            log(f"Peripheral state: {state}")
            if state != 5:
                self.send_event("error", f"Bluetooth недоступен: {state}")
                return
            self.send_event("ready", "Bluetooth готов")
            if self.characteristic is not None:
                self.start_advertising()
                return
            characteristic = CBMutableCharacteristic.alloc().initWithType_properties_value_permissions_(
                CHARACTERISTIC_UUID,
                (CBCharacteristicPropertyRead | CBCharacteristicPropertyWrite | CBCharacteristicPropertyWriteWithoutResponse | CBCharacteristicPropertyNotify),
                None,
                (CBAttributePermissionsReadable | CBAttributePermissionsWriteable),
            )
            self.characteristic = characteristic
            service = CBMutableService.alloc().initWithType_primary_(SERVICE_UUID, True)
            service.setCharacteristics_([characteristic])
            peripheral.addService_(service)

        def peripheralManager_didAddService_error_(self, peripheral, service, error):
            if error:
                self.send_event("error", str(error))
                return
            self.service_added = True
            self.start_advertising()

        def start_advertising(self):
            if not (self.manager and self.service_added):
                return
            try:
                self.manager.stopAdvertising()
            except Exception:
                pass
            self.manager.startAdvertising_({
                CBAdvertisementDataLocalNameKey: advertised_name(self.local_name, sos=self.sos_active),
                CBAdvertisementDataServiceUUIDsKey: [SERVICE_UUID],
            })

        def peripheralManagerDidStartAdvertising_error_(self, peripheral, error):
            if error:
                self.send_event("error", str(error))
                return
            self.send_event("advertising", "Видимы рядом")

        def peripheralManager_didReceiveWriteRequests_(self, peripheral, requests):
            for request in requests:
                try:
                    value = request.value()
                    if value:
                        self.assembler.accept(bytes(value), self.handle_incoming_text)
                    peripheral.respondToRequest_withResult_(request, 0)
                except Exception as exc:
                    log(f"Receive error: {exc}")

        def handle_incoming_text(self, text):
            if text.startswith(CONNECT_REQUEST_PREFIX):
                peer_name = text[len(CONNECT_REQUEST_PREFIX):].strip() or "Собеседник"
                self.pending_peer_name = peer_name
                self.connection_approved = False
                self.accept_acked = False
                self.send_event("connection_request", f"{peer_name} хочет подключиться", name=peer_name)
                return
            if text.startswith(CONNECT_ACK_PREFIX):
                self.accept_acked = True
                self.connection_approved = True
                return
            if text.startswith(CHAT_MESSAGE_PREFIX):
                if not self.connection_approved:
                    self.connection_approved = True
                    self.accept_acked = True
                    self.send_event("peer_connected", "Канал открыт", name=self.pending_peer_name or "Собеседник")
                payload = text[len(CHAT_MESSAGE_PREFIX):]
                mid, rest = parse_chat_payload(payload)
                if mid:
                    self.send_notification(DELIVERED_PREFIX + mid)
                    self.send_event("message_received", rest, mid=mid)
                else:
                    self.send_event("message_received", rest)
                return
            if text.startswith(TYPING_PREFIX):
                self.send_event("peer_typing", "печатает")
                return
            if text.startswith(DELIVERED_PREFIX):
                self.send_event("ble_delivered", text[len(DELIVERED_PREFIX):])
                return
            if text.startswith(READ_PREFIX):
                self.send_event("ble_read", text[len(READ_PREFIX):])
                return
            if text.startswith(SOS_PREFIX):
                parts = unpack_tagged(text, SOS_PREFIX)
                self.send_event("sos_received", "SOS рядом", name=parts[0] if parts else "Кто-то", coords=parts[1] if len(parts) > 1 else "-", note=parts[2] if len(parts) > 2 else "")
                return
            if text.startswith(OK_PREFIX):
                self.send_event("ok_received", "Человек в порядке", name=text[len(OK_PREFIX):].strip() or "Собеседник")
                return
            if text.startswith(LOC_PREFIX):
                parts = unpack_tagged(text, LOC_PREFIX)
                self.send_event("loc_received", "Точка на карте", name=parts[0] if parts else "Собеседник", coords=parts[1] if len(parts) > 1 else "-")
                return
            if text.startswith(CONNECT_ACCEPT_PREFIX):
                return
            self.send_event("message_received", text)

        def send_notification(self, text):
            if not (self.manager and self.characteristic and self.has_subscriber):
                return False
            raw = text.encode("utf-8")
            limit = max(20, int(getattr(self, "notify_max", 182) or 182))
            try:
                packets = [raw] if len(raw) <= limit and not raw.startswith(FRAME_MAGIC) else self.assembler.make_frames(text, self.notify_frame_bytes)
            except ValueError as exc:
                self.send_event("error", str(exc))
                return False
            self.notify_queue.extend(packets)
            return self.flush_notify_queue()

        def flush_notify_queue(self):
            if getattr(self, "_flushing_notify", False):
                return True
            if not (self.manager and self.characteristic and self.has_subscriber):
                return False
            self._flushing_notify = True
            try:
                while self.notify_queue:
                    frame = self.notify_queue.pop(0)
                    try:
                        ok = bool(self.manager.updateValue_forCharacteristic_onSubscribedCentrals_(nsd(frame), self.characteristic, None))
                    except Exception as exc:
                        log(f"notify: {exc}")
                        self.notify_queue.insert(0, frame)
                        return False
                    if not ok:
                        self.notify_queue.insert(0, frame)
                        return False
                return True
            finally:
                self._flushing_notify = False

        def peripheralManagerIsReadyToUpdateSubscribers_(self, peripheral):
            try:
                self.flush_notify_queue()
            except Exception:
                pass

        def approve_connection(self):
            if not self.has_subscriber:
                return False
            self.connection_approved = True
            self.accept_acked = False
            self.accept_tries = 0
            self.next_accept_at = 0
            self.send_accept()
            self.send_event("peer_connected", "Канал открыт", name=self.pending_peer_name or "Собеседник")
            return True

        def send_accept(self):
            if self.notify_queue:
                self.next_accept_at = time.time() + 0.2
                return self.flush_notify_queue()
            self.accept_tries += 1
            self.next_accept_at = time.time() + 0.45
            return self.send_notification(CONNECT_ACCEPT_PREFIX + self.local_name)

        def deny_connection(self):
            self.connection_approved = False
            self.send_notification(CONNECT_DENY_PREFIX + "Подключение отклонено")
            self.send_event("peer_denied", "Отклонено")
            return True

        def peripheralManager_central_didSubscribeToCharacteristic_(self, peripheral, central, characteristic):
            self.has_subscriber = True
            self.connection_approved = False
            self.accept_acked = False
            try:
                mtu = int(central.maximumUpdateValueLength())
            except Exception:
                mtu = FRAME_BYTES
            self.notify_max = max(20, min(512, mtu))
            self.notify_frame_bytes = max(FRAME_HEADER_BYTES + 1, min(FRAME_BYTES, mtu))
            self.send_event("peer_waiting", "Входящее подключение")

        def peripheralManager_central_didUnsubscribeFromCharacteristic_(self, peripheral, central, characteristic):
            self.has_subscriber = False
            self.connection_approved = False
            self.send_event("peer_disconnected", "Собеседник отключился")

    class CentralDelegate(NSObject):
        def initWithQueue_(self, sq):
            self = self.init()
            if self is not None:
                self.status_queue = sq
                self.central = None
                self.peripheral = None
                self.characteristic = None
                self.discovered_peripherals = {}
                self.pending_messages = []
                self.local_name = default_display_name()
                self.peer_approved = False
                self.next_msg_id = 1
                self.assembler = FrameAssembler()
                self.notify_enabled = False
                self.pending_connect_request = False
                self.pending_writes = []
                self.write_busy = False
                self.write_mtu = 182
                self.connect_tries = 0
                self.next_connect_at = 0
            return self

        def send_event(self, event, message, **extra):
            data = {"event": event, "message": message}
            data.update(extra)
            try:
                self.status_queue.put(data)
            except Exception:
                pass

        def centralManagerDidUpdateState_(self, central):
            if central.state() == 5:
                self.send_event("central_ready", "Bluetooth готов")

        def centralManager_didDiscoverPeripheral_advertisementData_RSSI_(self, central, peripheral, adv_data, rssi):
            raw_name = peripheral.name() or adv_data.get("kCBAdvDataLocalName", APP_NAME)
            name = peer_name_from_advertisement(raw_name)
            identifier = str(peripheral.identifier())
            self.discovered_peripherals[identifier] = peripheral
            self.send_event("device_found", "Найден узел", name=name, identifier=identifier, rssi=int(rssi), sos=advertisement_is_sos(raw_name))

        def centralManager_didConnectPeripheral_(self, central, peripheral):
            self.peripheral = peripheral
            self.characteristic = None
            self.peer_approved = False
            self.notify_enabled = False
            self.pending_connect_request = False
            peripheral.setDelegate_(self)
            self.send_event("connected", "Соединение установлено")
            peripheral.discoverServices_([SERVICE_UUID])

        def centralManager_didDisconnectPeripheral_error_(self, central, peripheral, error):
            self.peripheral = None
            self.characteristic = None
            self.peer_approved = False
            self.pending_messages.clear()
            self.send_event("peer_disconnected", "Собеседник отключился")

        def peripheral_didDiscoverServices_(self, peripheral, error):
            if error:
                return
            for service in (peripheral.services() or []):
                if str(service.UUID()).upper() == SERVICE_UUID_STRING:
                    peripheral.discoverCharacteristics_forService_([CHARACTERISTIC_UUID], service)

        def peripheral_didDiscoverCharacteristicsForService_error_(self, peripheral, service, error):
            if error:
                return
            for char in (service.characteristics() or []):
                if str(char.UUID()).upper() == CHARACTERISTIC_UUID_STRING:
                    self.characteristic = char
                    self.notify_enabled = False
                    self.pending_connect_request = True
                    self.connect_tries = 0
                    self.next_connect_at = 0
                    try:
                        mtu_wr = int(peripheral.maximumWriteValueLengthForType_(0))
                    except Exception:
                        mtu_wr = 0
                    try:
                        mtu_wo = int(peripheral.maximumWriteValueLengthForType_(1))
                    except Exception:
                        mtu_wo = 0
                    self.write_mtu = min(512, max(182, mtu_wr, mtu_wo))
                    peripheral.setNotifyValue_forCharacteristic_(True, char)
                    self.write_protocol(CONNECT_REQUEST_PREFIX + self.local_name)
                    self.connect_tries = 1
                    self.next_connect_at = time.time() + 0.8
                    self.send_event("approval_requested", "Запрос отправлен")

        def peripheral_didUpdateNotificationStateForCharacteristic_error_(self, peripheral, characteristic, error):
            if error:
                return
            notifying = True
            try:
                notifying = bool(characteristic.isNotifying())
            except Exception:
                pass
            self.notify_enabled = notifying
            if notifying and self.pending_connect_request:
                self.pending_connect_request = False
                self.write_protocol(CONNECT_REQUEST_PREFIX + self.local_name)
                self.connect_tries = max(self.connect_tries, 1)
                self.next_connect_at = time.time() + 0.35

        def mark_ready(self, peer_name=None):
            already = self.peer_approved
            self.peer_approved = True
            self.connect_tries = ACCEPT_RETRY_LIMIT
            if not already:
                self.send_event("ready_to_chat", "Канал готов", name=peer_name or "Собеседник")
                self.write_protocol(CONNECT_ACK_PREFIX + self.local_name)
                while self.pending_messages:
                    self.send_message(self.pending_messages.pop(0))

        def write_protocol(self, text):
            if not (self.peripheral and self.characteristic):
                return False
            raw = text.encode("utf-8")
            limit = max(20, int(getattr(self, "write_mtu", 182) or 182))
            try:
                if len(raw) <= limit:
                    packets = [raw]
                else:
                    packets = self.assembler.make_frames(text, min(limit, 182))
            except Exception as exc:
                log(f"Write: {exc}")
                return False
            self.pending_writes.extend(packets)
            self.flush_pending_writes()
            return True

        def flush_pending_writes(self):
            if getattr(self, "write_busy", False):
                return
            if not self.pending_writes or not (self.peripheral and self.characteristic):
                return
            frame = self.pending_writes[0]
            self.write_busy = True
            try:
                self.peripheral.writeValue_forCharacteristic_type_(nsd(frame), self.characteristic, 0)
            except Exception as exc:
                log(f"Write: {exc}")
                self.write_busy = False
                self.pending_writes.pop(0)
                self.flush_pending_writes()

        def peripheral_didWriteValueForCharacteristic_error_(self, peripheral, characteristic, error):
            if self.pending_writes:
                self.pending_writes.pop(0)
            self.write_busy = False
            if error:
                log(f"Write err: {error}")
            self.flush_pending_writes()

        def send_message(self, text, mid=None):
            if not self.peer_approved:
                self.pending_messages.append(text)
                self.send_event("waiting_for_approval", "Ждём согласие")
                return False
            mid = str(mid or self.next_msg_id)
            self.next_msg_id += 1
            if not self.write_protocol(CHAT_MESSAGE_PREFIX + mid + "|" + text):
                return False
            self.send_event("message_sent", text, mid=mid)
            return True

        def peripheral_didUpdateValueForCharacteristic_error_(self, peripheral, characteristic, error):
            if error or not characteristic.value():
                return
            try:
                self.assembler.accept(bytes(characteristic.value()), self.handle_incoming_text)
            except Exception as exc:
                log(f"notify in: {exc}")

        def handle_incoming_text(self, text):
            if text.startswith(CONNECT_ACCEPT_PREFIX):
                self.mark_ready(text[len(CONNECT_ACCEPT_PREFIX):].strip() or "Собеседник")
                return
            if text.startswith(CONNECT_ACK_PREFIX):
                self.mark_ready()
                return
            if text.startswith(CONNECT_DENY_PREFIX):
                self.peer_approved = False
                self.send_event("connection_denied", text[len(CONNECT_DENY_PREFIX):].strip() or "Отклонено")
                return
            if text.startswith(CHAT_MESSAGE_PREFIX):
                if not self.peer_approved:
                    self.mark_ready()
                payload = text[len(CHAT_MESSAGE_PREFIX):]
                mid, rest = parse_chat_payload(payload)
                if mid:
                    self.write_protocol(DELIVERED_PREFIX + mid)
                    self.send_event("message_received", rest, mid=mid)
                else:
                    self.send_event("message_received", rest)
                return
            if text.startswith(TYPING_PREFIX):
                self.send_event("peer_typing", "печатает")
                return
            if text.startswith(DELIVERED_PREFIX):
                self.send_event("ble_delivered", text[len(DELIVERED_PREFIX):])
                return
            if text.startswith(READ_PREFIX):
                self.send_event("ble_read", text[len(READ_PREFIX):])
                return
            if text.startswith(SOS_PREFIX):
                parts = unpack_tagged(text, SOS_PREFIX)
                if not self.peer_approved:
                    self.mark_ready()
                self.send_event("sos_received", "SOS", name=parts[0] if parts else "Кто-то", coords=parts[1] if len(parts) > 1 else "-", note=parts[2] if len(parts) > 2 else "")
                return
            if text.startswith(OK_PREFIX):
                self.send_event("ok_received", "В порядке", name=text[len(OK_PREFIX):].strip() or "Собеседник")
                return
            if text.startswith(LOC_PREFIX):
                parts = unpack_tagged(text, LOC_PREFIX)
                self.send_event("loc_received", "Точка", name=parts[0] if parts else "Собеседник", coords=parts[1] if len(parts) > 1 else "-")
                return
            self.send_event("message_received", text)

    p_delegate = PeripheralDelegate.alloc().initWithQueue_(status_queue)
    p_manager = CBPeripheralManager.alloc().initWithDelegate_queue_(p_delegate, None)
    p_delegate.manager = p_manager
    c_delegate = CentralDelegate.alloc().initWithQueue_(status_queue)
    c_manager = CBCentralManager.alloc().initWithDelegate_queue_(c_delegate, None)
    c_delegate.central = c_manager
    location_manager = {"mgr": None}
    next_sos_at = 0

    def read_gps():
        try:
            from CoreLocation import CLLocationManager
            mgr = location_manager["mgr"]
            if mgr is None:
                mgr = CLLocationManager.alloc().init()
                location_manager["mgr"] = mgr
                try:
                    mgr.requestWhenInUseAuthorization()
                except Exception:
                    pass
                try:
                    mgr.startUpdatingLocation()
                except Exception:
                    pass
            loc = mgr.location()
            if not loc:
                return None, None, None
            coord = loc.coordinate()
            acc = float(loc.horizontalAccuracy())
            if acc < 0:
                return None, None, None
            return float(coord.latitude), float(coord.longitude), acc
        except Exception as exc:
            log(f"[GPS] {exc}")
            return None, None, None

    def write_outgoing_packet(packet):
        if c_delegate.peripheral:
            if not c_delegate.peer_approved:
                return False
            return c_delegate.write_protocol(packet)
        if p_delegate.connection_approved:
            return p_delegate.send_notification(packet)
        return False

    shutdown = False
    while not shutdown:
        try:
            while True:
                cmd = command_queue.get_nowait()
                cmd_type = cmd.get("type")
                if cmd_type == "shutdown":
                    shutdown = True
                    break
                if cmd_type == "scan":
                    if c_manager.state() == 5:
                        c_manager.scanForPeripheralsWithServices_options_([SERVICE_UUID], None)
                        status_queue.put({"event": "scanning", "message": "Поиск..."})
                elif cmd_type == "stop_scan":
                    c_manager.stopScan()
                elif cmd_type == "connect":
                    identifier = cmd.get("identifier")
                    peripheral = c_delegate.discovered_peripherals.get(identifier)
                    if peripheral:
                        c_delegate.characteristic = None
                        c_delegate.peer_approved = False
                        c_delegate.notify_enabled = False
                        c_delegate.pending_connect_request = False
                        c_delegate.connect_tries = 0
                        c_delegate.next_connect_at = 0
                        c_delegate.pending_messages.clear()
                        peripheral.setDelegate_(c_delegate)
                        status_queue.put({"event": "connecting", "message": "Подключение..."})
                        c_manager.connectPeripheral_options_(peripheral, None)
                    else:
                        status_queue.put({"event": "error", "message": "Устройство не найдено"})
                elif cmd_type == "message":
                    mid = cmd.get("mid") or str(int(time.time() * 1000) % 100000)
                    text = cmd.get("text", "")
                    payload = CHAT_MESSAGE_PREFIX + str(mid) + "|" + text
                    sent = False
                    if c_delegate.peripheral and c_delegate.characteristic:
                        sent = bool(c_delegate.send_message(text, mid=mid))
                    if not sent and p_delegate.has_subscriber:
                        if not p_delegate.connection_approved:
                            p_delegate.connection_approved = True
                        sent = bool(p_delegate.send_notification(payload))
                    if sent:
                        status_queue.put({"event": "message_sent", "message": text, "mid": str(mid)})
                    else:
                        status_queue.put({"event": "error", "message": "Нет канала"})
                elif cmd_type == "typing":
                    token = TYPING_PREFIX + "1"
                    if c_delegate.peripheral:
                        c_delegate.write_protocol(token)
                    if p_delegate.has_subscriber:
                        p_delegate.send_notification(token)
                elif cmd_type == "ble_read":
                    token = READ_PREFIX + str(cmd.get("mid") or "")
                    if c_delegate.peripheral:
                        c_delegate.write_protocol(token)
                    if p_delegate.has_subscriber:
                        p_delegate.send_notification(token)
                elif cmd_type == "approve_connection":
                    p_delegate.approve_connection()
                elif cmd_type == "deny_connection":
                    p_delegate.deny_connection()
                elif cmd_type == "set_name":
                    name = (cmd.get("name") or default_display_name()).strip() or default_display_name()
                    p_delegate.local_name = name
                    c_delegate.local_name = name
                    p_delegate.start_advertising()
                elif cmd_type == "sos":
                    active = bool(cmd.get("active"))
                    p_delegate.sos_active = active
                    p_delegate.start_advertising()
                    lat, lng, _acc = read_gps() if active else (None, None, None)
                    if active:
                        write_outgoing_packet(pack_sos(p_delegate.local_name, lat, lng, cmd.get("note") or ""))
                        status_queue.put({"event": "sos_on", "message": "Маяк в эфире", "coords": f"{lat:.5f},{lng:.5f}" if lat is not None else "-"})
                    else:
                        status_queue.put({"event": "sos_off", "message": "Маяк выключен"})
                elif cmd_type == "ok":
                    p_delegate.sos_active = False
                    p_delegate.start_advertising()
                    write_outgoing_packet(OK_PREFIX + p_delegate.local_name)
                    status_queue.put({"event": "ok_sent", "message": "Отметили: я в порядке"})
                elif cmd_type == "loc":
                    lat, lng, acc = read_gps()
                    if lat is None:
                        status_queue.put({"event": "error", "message": "Нет GPS. Разрешите Геопозицию."})
                    elif write_outgoing_packet(LOC_PREFIX + f"{p_delegate.local_name}|{lat:.5f},{lng:.5f}|{acc:.0f}"):
                        status_queue.put({"event": "loc_sent", "message": f"{lat:.5f}, {lng:.5f}", "coords": f"{lat:.5f},{lng:.5f}"})
                    else:
                        status_queue.put({"event": "error", "message": "Сначала откройте связь рядом"})
                elif cmd_type == "gps":
                    lat, lng, acc = read_gps()
                    if lat is None:
                        status_queue.put({"event": "gps", "message": "GPS пока молчит", "coords": "-"})
                    else:
                        status_queue.put({"event": "gps", "message": f"{lat:.5f}, {lng:.5f}", "coords": f"{lat:.5f},{lng:.5f}", "acc": f"{acc:.0f}"})
        except queue.Empty:
            pass
        if shutdown:
            break
        if p_delegate.connection_approved and not p_delegate.accept_acked and p_delegate.has_subscriber and p_delegate.accept_tries < ACCEPT_RETRY_LIMIT and time.time() >= p_delegate.next_accept_at:
            try:
                p_delegate.send_accept()
            except Exception:
                pass
        if c_delegate.characteristic and not c_delegate.peer_approved and c_delegate.connect_tries < 3 and time.time() >= getattr(c_delegate, "next_connect_at", 0):
            try:
                if not getattr(c_delegate, "write_busy", False):
                    c_delegate.write_protocol(CONNECT_REQUEST_PREFIX + c_delegate.local_name)
                    c_delegate.connect_tries = int(getattr(c_delegate, "connect_tries", 0) or 0) + 1
                    c_delegate.next_connect_at = time.time() + 0.8
            except Exception:
                pass
        try:
            p_delegate.flush_notify_queue()
        except Exception:
            pass
        try:
            c_delegate.flush_pending_writes()
        except Exception:
            pass
        if p_delegate.sos_active and time.time() >= next_sos_at:
            lat, lng, _acc = read_gps()
            write_outgoing_packet(pack_sos(p_delegate.local_name, lat, lng, ""))
            next_sos_at = time.time() + 8
        pump(0.05)

