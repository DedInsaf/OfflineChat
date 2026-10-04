import SwiftUI
import AVFoundation

/// Owns capture independently of the composer and keeps blocking camera work off the UI thread.
final class OnlineMessageRecorder: NSObject, ObservableObject, AVCaptureFileOutputRecordingDelegate {
    @Published var recording = false
    @Published var error = ""
    @Published var finishing = false
    @Published private(set) var preparing = false
    @Published private(set) var paused = false
    let session = AVCaptureSession()
    private let queue = DispatchQueue(label: "chat.recording")
    private let output = AVCaptureMovieFileOutput()
    private var audio: AVAudioRecorder?
    private var held = false
    private var completion: ((URL?) -> Void)?
    private var url: URL?
    private var startedAt: Date?
    private var generation = UUID()
    private var video = false
    private var elapsed: TimeInterval = 0
    private var segments: [URL] = []
    private var pauseRequested = false
    private var limitTimer: Timer?
    var busy: Bool { preparing || recording || finishing }
    var duration: TimeInterval { min(60, elapsed + (startedAt.map { Date().timeIntervalSince($0) } ?? 0)) }
    var level: CGFloat {
        guard recording && !paused, let audio else { return 0 }
        audio.updateMeters()
        return CGFloat(max(0, min(1, (audio.averagePower(forChannel: 0) + 60) / 60)))
    }
    var durationText: String {
        let seconds = max(0, Int(duration))
        return String(format: "%02d:%02d", seconds / 60, seconds % 60)
    }

    @MainActor func start(video: Bool, completion: @escaping (URL?) -> Void) {
        guard !held && !recording && !finishing else { return }
        RecordedPlayback.stopActive()
        let currentGeneration = UUID()
        generation = currentGeneration
        held = true
        preparing = true
        self.video = video
        elapsed = 0
        segments = []
        paused = false
        self.completion = completion
        Task {
            let microphone = await AVCaptureDevice.requestAccess(for: .audio)
            guard held && generation == currentGeneration else { return }
            let camera = video ? await AVCaptureDevice.requestAccess(for: .video) : true
            guard held && generation == currentGeneration else { return }
            guard microphone && camera else {
                error = "Разрешите микрофон и камеру в настройках iPhone."
                cancel()
                return
            }
            do {
                try await activateAudioSession(video: video)
                guard held && generation == currentGeneration else { return }
                let path = FileManager.default.temporaryDirectory.appendingPathComponent("oc-\(video ? "circle" : "voice")-\(UUID().uuidString).\(video ? "mov" : "m4a")")
                url = path
                if video {
                    queue.async { [self] in
                        session.automaticallyConfiguresApplicationAudioSession = false
                        session.beginConfiguration()
                        session.sessionPreset = .medium
                        session.inputs.forEach { session.removeInput($0) }
                        do {
                            guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .front),
                                  let mic = AVCaptureDevice.default(for: .audio) else { throw NSError(domain: "Recording", code: 1) }
                            for device in [camera, mic] {
                                let input = try AVCaptureDeviceInput(device: device)
                                guard session.canAddInput(input) else { throw NSError(domain: "Recording", code: 2) }
                                session.addInput(input)
                            }
                            if !session.outputs.contains(output) {
                                guard session.canAddOutput(output) else { throw NSError(domain: "Recording", code: 4) }
                                session.addOutput(output)
                            }
                            if let connection = output.connection(with: .video) {
                                output.setOutputSettings([AVVideoCodecKey: AVVideoCodecType.h264,
                                    AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: 350000]], for: connection)
                                if connection.isVideoStabilizationSupported { connection.preferredVideoStabilizationMode = .standard }
                            }
                            output.maxRecordedDuration = CMTime(seconds: 60, preferredTimescale: 600)
                            session.commitConfiguration()
                            session.startRunning()
                            DispatchQueue.main.async {
                                guard self.held && self.generation == currentGeneration else { return }
                                self.queue.async { self.output.startRecording(to: path, recordingDelegate: self) }
                            }
                        } catch {
                            session.commitConfiguration()
                            DispatchQueue.main.async {
                                guard self.generation == currentGeneration else { return }
                                self.error = error.localizedDescription; self.cancel()
                            }
                        }
                    }
                } else {
                    audio = try AVAudioRecorder(url: path, settings: [AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 24000, AVNumberOfChannelsKey: 1, AVEncoderBitRateKey: 48000])
                    audio?.isMeteringEnabled = true
                    guard audio?.record() == true else { throw NSError(domain: "Recording", code: 3) }
                    began()
                }
            } catch {
                guard generation == currentGeneration else { return }
                self.error = error.localizedDescription; cancel()
            }
        }
    }

    private func activateAudioSession(video: Bool) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            queue.async {
                do {
                    let session = AVAudioSession.sharedInstance()
                    try session.setCategory(.playAndRecord, mode: video ? .videoRecording : .default, options: [.defaultToSpeaker])
                    try session.setActive(true)
                    continuation.resume()
                } catch { continuation.resume(throwing: error) }
            }
        }
    }

    @MainActor func finish() {
        guard !finishing else { return }
        if preparing {
            if !segments.isEmpty {
                // Keep earlier paused segments if Resume is immediately stopped.
                url = nil
                held = false
                preparing = false
                finishing = true
                queue.async { if self.output.isRecording { self.output.stopRecording() } }
                assembleVideo()
            } else { cancel() }
            return
        }
        guard recording else { return }
        held = false
        freezeTime()
        pauseRequested = false
        if video {
            finishing = true
            if paused { assembleVideo() }
            else { queue.async { self.output.stopRecording() } }
            return
        }
        guard let audio else { return }
        let duration = audio.currentTime
        audio.stop()
        self.audio = nil
        deliver(duration >= 0.5 ? url : nil)
    }

    @MainActor func cancel() {
        generation = UUID()
        held = false
        completion = nil
        pauseRequested = false
        audio?.stop(); audio = nil
        queue.async { if self.output.isRecording { self.output.stopRecording() } }
        deliver(nil)
    }

    @MainActor private func began() {
        preparing = false
        recording = true
        paused = false
        startedAt = Date()
        limitTimer?.invalidate()
        limitTimer = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { [weak self] _ in
            guard let self, self.duration >= 60 else { return }
            Task { @MainActor in self.finish() }
        }
    }

    @MainActor private func freezeTime() {
        elapsed = duration
        startedAt = nil
        limitTimer?.invalidate()
        limitTimer = nil
    }

    @MainActor func pause() {
        if preparing && paused && recording {
            url = nil
            preparing = false
            queue.async { if self.output.isRecording { self.output.stopRecording() } }
            return
        }
        guard recording && !paused && !finishing else { return }
        freezeTime()
        paused = true
        if video {
            finishing = true
            pauseRequested = true
            queue.async { self.output.stopRecording() }
        } else { audio?.pause() }
    }

    @MainActor func resume() {
        guard recording && paused && !finishing && !preparing else { return }
        if duration >= 60 { finish(); return }
        RecordedPlayback.stopActive()
        do {
            try AVAudioSession.sharedInstance().setActive(true)
            if video {
                let path = FileManager.default.temporaryDirectory.appendingPathComponent("oc-circle-\(UUID().uuidString).mov")
                url = path
                preparing = true
                let remaining = max(0.1, 60 - elapsed)
                queue.async {
                    if !self.session.isRunning { self.session.startRunning() }
                    self.output.maxRecordedDuration = CMTime(seconds: remaining, preferredTimescale: 600)
                    self.output.startRecording(to: path, recordingDelegate: self)
                }
            } else {
                guard audio?.record() == true else { throw NSError(domain: "Recording", code: 5) }
                began()
            }
        } catch { self.error = error.localizedDescription }
    }

    @MainActor private func assembleVideo() {
        let token = generation
        let paths = segments
        Task {
            do {
                let result = try await RecordingSegments.combine(paths)
                guard generation == token else {
                    try? FileManager.default.removeItem(at: result)
                    return
                }
                deliver(elapsed >= 0.5 ? result : nil)
            } catch {
                guard generation == token else { return }
                // Preserve original segments for retry instead of deleting a draft.
                held = true
                recording = true
                paused = true
                finishing = false
                self.error = "Не удалось сохранить запись: \(error.localizedDescription)"
            }
        }
    }

    @MainActor private func deliver(_ result: URL?) {
        freezeTime()
        held = false
        preparing = false
        paused = false
        recording = false
        finishing = false
        queue.async {
            if self.session.isRunning { self.session.stopRunning() }
            let audioSession = AVAudioSession.sharedInstance()
            // A preview player may already have switched to playback by now.
            if audioSession.category == .playAndRecord {
                try? audioSession.setActive(false, options: .notifyOthersOnDeactivation)
            }
        }
        let callback = completion
        completion = nil
        (segments + (url.map { [$0] } ?? [])).filter { $0 != result }.forEach { try? FileManager.default.removeItem(at: $0) }
        segments = []
        url = nil
        callback?(result)
    }

    func fileOutput(_ output: AVCaptureFileOutput, didStartRecordingTo fileURL: URL, from connections: [AVCaptureConnection]) {
        DispatchQueue.main.async {
            guard self.held && self.url == fileURL else { return }
            self.began()
        }
    }

    func fileOutput(_ output: AVCaptureFileOutput, didFinishRecordingTo outputFileURL: URL, from connections: [AVCaptureConnection], error: Error?) {
        DispatchQueue.main.async {
            guard self.url == outputFileURL && self.completion != nil else {
                try? FileManager.default.removeItem(at: outputFileURL)
                return
            }
            let succeeded = error == nil || (error as NSError?)?.userInfo[AVErrorRecordingSuccessfullyFinishedKey] as? Bool == true
            guard succeeded else {
                self.deliver(nil)
                self.error = "Не удалось записать видео. Проверьте доступ к камере и свободное место."
                return
            }
            self.freezeTime()
            self.segments.append(outputFileURL)
            if self.pauseRequested {
                self.finishing = false
                self.pauseRequested = false
                self.queue.async { if self.session.isRunning { self.session.stopRunning() } }
            } else {
                self.finishing = true
                self.assembleVideo()
            }
        }
    }

    deinit { limitTimer?.invalidate() }
}

struct RecordingPreview: UIViewRepresentable {
    let session: AVCaptureSession
    final class Preview: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
    }
    func makeUIView(context: Context) -> Preview {
        let view = Preview()
        let layer = view.layer as! AVCaptureVideoPreviewLayer
        layer.session = session
        layer.videoGravity = .resizeAspectFill
        return view
    }
    func updateUIView(_ uiView: Preview, context: Context) {}
}
