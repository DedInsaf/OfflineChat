import SwiftUI
import AVFoundation
import UIKit

/// Gesture/timer updates stay inside the composer, not the message list.
struct OnlineRecordingComposer<Content: View>: View {
    let showRecordButton: Bool
    let disabled: Bool
    let onBegan: () -> Void
    let onSend: (URL) -> Void
    @ViewBuilder let content: () -> Content
    @StateObject private var recorder = OnlineMessageRecorder()
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase
    @State private var video = false
    @State private var pressedAt: Date?
    @State private var holdJob: DispatchWorkItem?
    @State private var locked = false
    @State private var cancelled = false
    @State private var translation = CGSize.zero
    @State private var recordedDraft: URL?
    @State private var review = false
    @State private var modeHint = false
    @State private var hintJob: DispatchWorkItem?

    private var animation: Animation? { reduceMotion ? nil : .easeOut(duration: 0.2) }
    private var active: Bool { recorder.busy || recordedDraft != nil }
    private var cancelProgress: CGFloat { min(1, max(0, -translation.width / 96)) }
    private var lockProgress: CGFloat { min(1, max(0, -translation.height / 80)) }

    var body: some View {
        VStack(spacing: 8) {
            if video && recorder.busy {
                RecordingPreview(session: recorder.session)
                    .frame(width: 204, height: 204)
                    .clipShape(Circle())
                    .overlay(Circle().stroke(Color.ocPrimary.opacity(0.5), lineWidth: 2))
                    .overlay {
                        if recorder.preparing { ProgressView().tint(Color.ocText).padding(12).background(Color.ocSurface.opacity(0.8), in: Circle()) }
                    }
                    .padding(.top, 12)
                    .transition(.opacity.combined(with: .scale(scale: 0.92)))
            }
            if let recordedDraft {
                RecordedMessageView(url: recordedDraft, circle: video)
                    .padding(.horizontal, 10)
                    .transition(.opacity)
            }
            if recorder.recording && !video && locked {
                RecordingWaveform(recorder: recorder).frame(height: 28).padding(.horizontal, 16)
                    .transition(.opacity)
            }
            HStack(alignment: .center, spacing: 8) {
                // Keep the same geometry and gesture target throughout a hold.
                content()
                    .opacity(active ? 0 : 1)
                    .allowsHitTesting(!active)
                    .accessibilityHidden(active)
                    .overlay { if active { status } }
                    .frame(maxWidth: .infinity)
                if showRecordButton || active {
                    recordControl
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .background(Color.ocSurface)
            .overlay(alignment: .topTrailing) {
                if modeHint && !active {
                    Text(video ? "Видеокружок · удерживайте для записи" : "Голосовое · удерживайте для записи")
                        .font(.caption).foregroundStyle(Color.ocText)
                        .padding(.horizontal, 12).padding(.vertical, 9)
                        .background(Color.ocSurfaceAlt, in: Capsule())
                        .padding(.trailing, 10).offset(y: -44)
                        .transition(.opacity)
                        .allowsHitTesting(false)
                }
            }
        }
        .animation(animation, value: recorder.recording)
        .animation(animation, value: recorder.preparing)
        .animation(animation, value: recordedDraft != nil)
        .animation(animation, value: locked)
        .onDisappear { discard() }
        .onChange(of: recorder.busy) { _, busy in
            if !busy { locked = false }
        }
        .onChange(of: recorder.paused) { _, paused in
            if paused { locked = true }
        }
        .onChange(of: scenePhase) { _, phase in
            // Permission prompts temporarily make the app inactive, not backgrounded.
            guard phase == .background else { return }
            if recorder.preparing && !recorder.recording { discard() }
            else if recorder.recording { locked = true; recorder.pause() }
        }
        .onReceive(NotificationCenter.default.publisher(for: AVAudioSession.interruptionNotification)) { note in
            guard (note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt) == AVAudioSession.InterruptionType.began.rawValue else { return }
            if recorder.preparing && !recorder.recording { discard() }
            else if recorder.recording { locked = true; recorder.pause() }
        }
        .alert("Запись", isPresented: Binding(get: { !recorder.error.isEmpty }, set: { if !$0 { recorder.error = "" } })) {
            Button("ОК") { recorder.error = "" }
        } message: { Text(recorder.error) }
    }

    private var status: some View {
        HStack(spacing: 8) {
            if recordedDraft != nil {
                Button(role: .destructive, action: discard) { Image(systemName: "trash").font(.system(size: 20)).frame(width: 44, height: 44) }
                    .accessibilityLabel("Удалить запись")
                Text("Готово к отправке").font(.footnote).foregroundStyle(Color.ocMuted)
                Spacer(minLength: 0)
            } else {
                RecordingClock(recorder: recorder)
                Spacer(minLength: 0)
                if recorder.finishing {
                    ProgressView().controlSize(.small)
                } else if locked {
                    Button("Отмена", role: .destructive, action: discard).font(.system(size: 17))
                    Spacer(minLength: 0)
                    Button {
                        if recorder.paused { review = true; recorder.finish() }
                        else { recorder.pause() }
                    } label: {
                        Image(systemName: recorder.paused ? "play.fill" : "pause.fill")
                            .font(.system(size: 20)).frame(width: 44, height: 44)
                    }.accessibilityLabel(recorder.paused ? "Просмотреть запись" : "Приостановить запись")
                } else {
                    HStack(spacing: 5) {
                        Image(systemName: "chevron.left").font(.system(size: 13, weight: .medium))
                        Text("Смахните для отмены").font(.system(size: 14)).lineLimit(1).minimumScaleFactor(0.75)
                    }
                    .foregroundStyle(cancelProgress > 0.65 ? Color.ocDanger : Color.ocMuted)
                    .offset(x: max(-36, translation.width * 0.35))
                    .opacity(Double(1 - cancelProgress * 0.6))
                    .accessibilityLabel("Смахните влево, чтобы отменить; вверх, чтобы закрепить запись")
                    Spacer(minLength: 0)
                }
            }
        }
    }

    private var recordControl: some View {
        ZStack {
            // Static rings follow the finger; no endlessly-running chat animation.
            if recorder.recording && !locked {
                RecordingPulse(recorder: recorder)
            }
            Image(systemName: recordedDraft != nil || (locked && !recorder.paused) ? "arrow.up" : (video ? "video.fill" : "mic.fill"))
                .font(.system(size: 20, weight: .semibold))
                .foregroundStyle(Color.ocPrimaryFg)
                .frame(width: 44, height: 44)
                .background(Color.ocPrimary, in: Circle())
                .scaleEffect(recorder.recording && !locked ? 1.35 : 1)
                .offset(x: locked ? 0 : max(-30, translation.width * 0.25), y: locked ? 0 : max(-24, translation.height * 0.25))
        }
        .frame(width: 44, height: 44)
        .contentShape(Rectangle())
        .overlay(alignment: .bottom) {
            if recorder.busy && !locked && !recorder.finishing {
                VStack(spacing: 12) {
                    Image(systemName: lockProgress > 0.7 ? "lock.fill" : "lock.open")
                    Image(systemName: "chevron.up").opacity(Double(1 - lockProgress))
                }
                .font(.system(size: 17, weight: .medium))
                .foregroundStyle(lockProgress > 0.6 ? Color.ocPrimary : Color.ocMuted)
                .frame(width: 38, height: 76 - lockProgress * 22)
                .background(Color.ocSurfaceAlt, in: Capsule())
                .offset(y: -64 - lockProgress * 18)
                .transition(.opacity.combined(with: .scale(scale: 0.9, anchor: .bottom)))
                .allowsHitTesting(false)
            }
        }
        .gesture(DragGesture(minimumDistance: 0).onChanged(changed).onEnded(ended))
        .accessibilityLabel(recordedDraft != nil ? "Отправить запись" : (locked ? (recorder.paused ? "Продолжить запись" : "Отправить запись") : (video ? "Видеокружок" : "Голосовое")))
        .accessibilityHint("Нажатие меняет режим. Удержание записывает. Вверх — закрепить, влево — отменить.")
        .accessibilityAddTraits(.isButton)
        .accessibilityAction {
            if recordedDraft != nil || locked { activate() }
            else { locked = true; begin() }
        }
    }

    private func changed(_ value: DragGesture.Value) {
        guard !disabled && !recorder.finishing && recordedDraft == nil && !locked && !cancelled else { return }
        if pressedAt == nil {
            pressedAt = Date()
            let job = DispatchWorkItem { begin() }
            holdJob = job
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.25, execute: job)
        }
        translation = value.translation
        if value.translation.width <= -96 {
            cancelled = true
            holdJob?.cancel()
            recorder.cancel()
            translation = .zero
            if !reduceMotion { UIImpactFeedbackGenerator(style: .light).impactOccurred() }
        } else if value.translation.height <= -80 {
            locked = true
            translation = .zero
            if !recorder.busy { holdJob?.cancel(); begin() }
            if !reduceMotion { UIImpactFeedbackGenerator(style: .light).impactOccurred() }
        }
    }

    private func ended(_ value: DragGesture.Value) {
        holdJob?.cancel()
        holdJob = nil
        defer { pressedAt = nil; translation = .zero; cancelled = false }
        if cancelled || disabled { return }
        if recordedDraft != nil || (locked && pressedAt == nil) { activate(); return }
        if locked { return }
        if let pressedAt, Date().timeIntervalSince(pressedAt) < 0.25 && !recorder.busy {
            withAnimation(animation) { video.toggle(); modeHint = true }
            hintJob?.cancel()
            let job = DispatchWorkItem { withAnimation(animation) { modeHint = false } }
            hintJob = job
            DispatchQueue.main.asyncAfter(deadline: .now() + 2, execute: job)
        } else { recorder.finish() }
    }

    private func begin() {
        guard !cancelled && !disabled && !recorder.busy else { return }
        hintJob?.cancel()
        modeHint = false
        review = false
        onBegan()
        recorder.start(video: video) { url in
            guard let url else { locked = false; return }
            if review || locked {
                withAnimation(animation) { recordedDraft = url; locked = false }
            } else { onSend(url) }
        }
    }

    private func activate() {
        if let recordedDraft {
            self.recordedDraft = nil
            onSend(recordedDraft)
        } else if recorder.paused { recorder.resume() }
        else { review = false; locked = false; recorder.finish() }
    }

    private func discard() {
        holdJob?.cancel(); hintJob?.cancel()
        holdJob = nil; pressedAt = nil
        locked = false; translation = .zero
        recorder.cancel()
        if let recordedDraft { try? FileManager.default.removeItem(at: recordedDraft) }
        recordedDraft = nil
    }
}

private struct RecordingClock: View {
    @ObservedObject var recorder: OnlineMessageRecorder
    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.2)) { _ in
            HStack(spacing: 6) {
                Circle().fill(recorder.paused ? Color.ocMuted : Color.ocDanger).frame(width: 7, height: 7)
                Text(recorder.preparing ? "Запуск…" : recorder.durationText)
                    .font(.system(size: 15)).monospacedDigit().foregroundStyle(Color.ocText)
            }.accessibilityLabel(recorder.paused ? "Запись на паузе" : "Идёт запись")
        }
    }
}

private struct RecordingPulse: View {
    @ObservedObject var recorder: OnlineMessageRecorder
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.09)) { _ in
            let level = reduceMotion ? CGFloat.zero : recorder.level
            ZStack {
                Circle().fill(Color.ocPrimary.opacity(0.12)).frame(width: 72 + level * 12, height: 72 + level * 12)
                Circle().fill(Color.ocPrimary.opacity(0.08)).frame(width: 82 + level * 14, height: 82 + level * 14)
            }
            .animation(reduceMotion ? nil : .linear(duration: 0.09), value: level)
        }.allowsHitTesting(false).accessibilityHidden(true)
    }
}

private struct RecordingWaveform: View {
    @ObservedObject var recorder: OnlineMessageRecorder
    @State private var levels = Array(repeating: CGFloat.zero, count: 42)
    private let timer = Timer.publish(every: 0.09, on: .main, in: .common).autoconnect()
    var body: some View {
        Canvas { context, size in
            let step = size.width / CGFloat(levels.count)
            for (index, level) in levels.enumerated() {
                let height = max(2, level * size.height)
                let rect = CGRect(x: CGFloat(index) * step, y: (size.height - height) / 2, width: min(3, step - 1), height: height)
                context.fill(Path(roundedRect: rect, cornerRadius: 1.5), with: .color(.ocPrimary))
            }
        }
        .onReceive(timer) { _ in
            guard !recorder.paused else { return }
            levels.removeFirst(); levels.append(recorder.level)
        }
        .accessibilityHidden(true)
    }
}
