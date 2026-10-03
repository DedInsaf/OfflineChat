import SwiftUI
import AVFoundation

@MainActor
final class RecordedPlayback: ObservableObject {
    private static weak var active: RecordedPlayback?
    @Published var playing = false
    @Published var elapsed: Double = 0
    @Published var duration: Double = 0
    @Published var waveform: [Float] = []
    @Published var speed: Float = 1
    let player: AVPlayer
    private var observer: Any?
    init(url: URL) {
        player = AVPlayer(url: url)
        observer = player.addPeriodicTimeObserver(forInterval: CMTime(seconds: 0.1, preferredTimescale: 600), queue: .main) { [weak self] time in
            Task { @MainActor in
                guard let self else { return }
                self.elapsed = max(0, time.seconds)
                if let seconds = self.player.currentItem?.duration.seconds, seconds.isFinite { self.duration = seconds }
                if self.duration > 0 && self.elapsed >= self.duration - 0.1 { self.playing = false }
            }
        }
        Task {
            let values = await Task.detached(priority: .utility) {
                guard let file = try? AVAudioFile(forReading: url),
                      let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: AVAudioFrameCount(min(file.length, 3_000_000))),
                      (try? file.read(into: buffer)) != nil, let samples = buffer.floatChannelData?[0] else { return [Float]() }
                let count = Int(buffer.frameLength)
                guard count > 0 else { return [Float]() }
                return (0..<48).map { bar in
                    let start = bar * count / 48
                    let end = max(start + 1, (bar + 1) * count / 48)
                    var peak: Float = 0
                    for index in start..<min(end, count) { peak = max(peak, abs(samples[index])) }
                    return peak
                }
            }.value
            waveform = values
        }
    }
    func toggle() {
        if Self.active !== self { Self.active?.stop(); Self.active = self }
        if playing { player.pause() }
        else {
            try? AVAudioSession.sharedInstance().setCategory(.playback)
            try? AVAudioSession.sharedInstance().setActive(true)
            if duration > 0 && elapsed >= duration - 0.1 { player.seek(to: .zero) }
            player.play()
            player.rate = speed
        }
        playing.toggle()
    }
    func stop() { player.pause(); playing = false }
    static func stopActive() { active?.stop() }
    func seek(fraction: Double) {
        player.seek(to: CMTime(seconds: max(0, min(1, fraction)) * duration, preferredTimescale: 600))
    }
    func changeSpeed() {
        speed = speed == 1 ? 1.5 : (speed == 1.5 ? 2 : 1)
        if playing { player.rate = speed }
    }
    deinit { if let observer { player.removeTimeObserver(observer) } }
}

/// AVPlayerLayer avoids the system video controls and full-screen player.
struct CircleVideoSurface: UIViewRepresentable {
    let player: AVPlayer
    final class Surface: UIView { override class var layerClass: AnyClass { AVPlayerLayer.self } }
    func makeUIView(context: Context) -> Surface {
        let view = Surface()
        let layer = view.layer as! AVPlayerLayer
        layer.player = player
        layer.videoGravity = .resizeAspectFill
        return view
    }
    func updateUIView(_ uiView: Surface, context: Context) {}
}

struct RecordedMessageView: View {
    let circle: Bool
    @StateObject private var playback: RecordedPlayback
    init(url: URL, circle: Bool) {
        self.circle = circle
        _playback = StateObject(wrappedValue: RecordedPlayback(url: url))
    }
    private var time: String {
        let seconds = Int(playback.playing || playback.elapsed > 0 ? playback.elapsed : playback.duration)
        return String(format: "%02d:%02d", seconds / 60, seconds % 60)
    }
    var body: some View {
        Group {
            if circle {
                ZStack(alignment: .bottom) {
                    CircleVideoSurface(player: playback.player)
                    if !playback.playing {
                        Image(systemName: "play.fill").font(.system(size: 26)).foregroundStyle(.white)
                            .padding(18).background(.black.opacity(0.3), in: Circle()).frame(maxHeight: .infinity)
                    }
                    Text(time).font(.caption.monospacedDigit()).foregroundStyle(.white)
                        .padding(6).background(.black.opacity(0.4), in: Capsule()).padding(.bottom, 15)
                }
                .frame(width: playback.playing ? 270 : 200, height: playback.playing ? 270 : 200)
                .clipShape(Circle())
                .contentShape(Circle())
                .onTapGesture { withAnimation(.easeInOut(duration: 0.22)) { playback.toggle() } }
            } else {
                HStack(spacing: 12) {
                    Button { playback.toggle() } label: {
                        Image(systemName: playback.playing ? "pause.fill" : "play.fill")
                            .font(.system(size: 20)).foregroundStyle(.white)
                            .frame(width: 50, height: 50).background(Color(red: 0.42, green: 0.23, blue: 1), in: Circle())
                    }.buttonStyle(.plain)
                    VStack(alignment: .leading, spacing: 5) {
                        Canvas { context, size in
                            let peak = max(playback.waveform.max() ?? 1, 0.01)
                            for index in 0..<48 {
                                let value = index < playback.waveform.count ? playback.waveform[index] / peak : 0
                                let height = max(3, CGFloat(value) * size.height)
                                let rect = CGRect(x: CGFloat(index) * size.width / 48, y: size.height - height, width: max(2, size.width / 48 - 2), height: height)
                                context.fill(Path(roundedRect: rect, cornerRadius: 1), with: .color(Double(index) / 48 < playback.elapsed / max(playback.duration, 1) ? .purple : Color.ocMuted))
                            }
                        }.frame(height: 25)
                        .gesture(DragGesture(minimumDistance: 0).onChanged { gesture in
                            playback.seek(fraction: gesture.location.x / 183)
                        })
                        HStack {
                            Text(time).font(.system(size: 14).monospacedDigit()).foregroundStyle(Color.ocMuted)
                            Spacer()
                            Button(String(format: "%g×", playback.speed)) { playback.changeSpeed() }
                                .font(.caption.bold()).buttonStyle(.plain)
                        }
                    }
                }.frame(width: 245).padding(.vertical, 5)
            }
        }
        .onDisappear { playback.stop() }
    }
}
