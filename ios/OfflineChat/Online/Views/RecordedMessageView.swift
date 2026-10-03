import SwiftUI
import AVKit

struct RecordedMessageView: View {
    let url: URL
    let circle: Bool
    @State private var player: AVPlayer?
    @State private var playing = false
    var body: some View {
        Group {
            if circle, let player {
                VideoPlayer(player: player).frame(width: 210, height: 210).clipShape(Circle())
            } else {
                Button {
                    guard let player else { return }
                    if playing { player.pause() } else { player.seek(to: .zero); player.play() }
                    playing.toggle()
                } label: {
                    Label(playing ? "Пауза" : "Голосовое сообщение", systemImage: playing ? "pause.fill" : "play.fill")
                        .frame(minWidth: 200, minHeight: 44)
                }
            }
        }
        .onAppear { player = AVPlayer(url: url) }
        .onDisappear { player?.pause(); player = nil }
    }
}
