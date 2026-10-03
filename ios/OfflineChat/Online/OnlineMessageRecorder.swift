import SwiftUI
import AVFoundation

/// Owns capture independently of the composer and keeps blocking camera work off the UI thread.
final class OnlineMessageRecorder: NSObject, ObservableObject, AVCaptureFileOutputRecordingDelegate {
    @Published var recording = false
    @Published var error = ""
    let session = AVCaptureSession()
    private let queue = DispatchQueue(label: "chat.recording")
    private let output = AVCaptureMovieFileOutput()
    private var audio: AVAudioRecorder?
    private var held = false
    private var completion: ((URL?) -> Void)?
    private var url: URL?

    @MainActor func start(video: Bool, completion: @escaping (URL?) -> Void) {
        held = true
        self.completion = completion
        Task {
            let microphone = await AVCaptureDevice.requestAccess(for: .audio)
            let camera = video ? await AVCaptureDevice.requestAccess(for: .video) : true
            guard held else { return }
            guard microphone && camera else {
                error = "Разрешите микрофон и камеру в настройках iPhone."
                held = false
                return
            }
            do {
                let audioSession = AVAudioSession.sharedInstance()
                try audioSession.setCategory(.playAndRecord, mode: video ? .videoRecording : .default, options: [.defaultToSpeaker])
                try audioSession.setActive(true)
                let path = FileManager.default.temporaryDirectory.appendingPathComponent("oc-\(video ? "circle" : "voice")-\(UUID().uuidString).\(video ? "mov" : "m4a")")
                url = path
                recording = true
                if video {
                    queue.async { [self] in
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
                            if !session.outputs.contains(output) { session.addOutput(output) }
                            if let connection = output.connection(with: .video) {
                                output.setOutputSettings([AVVideoCodecKey: AVVideoCodecType.h264,
                                    AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: 350000]], for: connection)
                            }
                            output.maxRecordedDuration = CMTime(seconds: 60, preferredTimescale: 600)
                            session.commitConfiguration()
                            session.startRunning()
                            DispatchQueue.main.async {
                                if self.held { self.output.startRecording(to: path, recordingDelegate: self) }
                                else { self.cancel() }
                            }
                        } catch {
                            session.commitConfiguration()
                            DispatchQueue.main.async { self.error = error.localizedDescription; self.cancel() }
                        }
                    }
                } else {
                    audio = try AVAudioRecorder(url: path, settings: [AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 24000, AVNumberOfChannelsKey: 1, AVEncoderBitRateKey: 48000])
                    guard audio?.record(forDuration: 60) == true else { throw NSError(domain: "Recording", code: 3) }
                }
            } catch { self.error = error.localizedDescription; cancel() }
        }
    }

    @MainActor func finish() {
        held = false
        if output.isRecording { output.stopRecording(); return }
        guard let audio else { return }
        let duration = audio.currentTime
        audio.stop()
        self.audio = nil
        deliver(duration >= 0.5 ? url : nil)
    }

    @MainActor func cancel() {
        held = false
        completion = nil
        if output.isRecording { output.stopRecording() }
        audio?.stop(); audio = nil
        deliver(nil)
    }

    private func deliver(_ result: URL?) {
        recording = false
        queue.async { if self.session.isRunning { self.session.stopRunning() } }
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        completion?(result)
        if result == nil, let url { try? FileManager.default.removeItem(at: url) }
        completion = nil
    }

    func fileOutput(_ output: AVCaptureFileOutput, didFinishRecordingTo outputFileURL: URL, from connections: [AVCaptureConnection], error: Error?) {
        DispatchQueue.main.async {
            let succeeded = error == nil || (error as NSError?)?.userInfo[AVErrorRecordingSuccessfullyFinishedKey] as? Bool == true
            self.deliver(succeeded ? outputFileURL : nil)
        }
    }
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
