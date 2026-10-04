import AVFoundation

/// Join paused camera segments without decoding or re-encoding their frames.
enum RecordingSegments {
    static func combine(_ urls: [URL]) async throws -> URL {
        guard let first = urls.first else { throw NSError(domain: "Recording", code: 10) }
        if urls.count == 1 { return first }
        let composition = AVMutableComposition()
        let video = composition.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid)
        let audio = composition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid)
        var cursor = CMTime.zero
        for url in urls {
            let asset = AVURLAsset(url: url)
            let duration = try await asset.load(.duration)
            let range = CMTimeRange(start: .zero, duration: duration)
            if let track = try await asset.loadTracks(withMediaType: .video).first {
                try video?.insertTimeRange(range, of: track, at: cursor)
                if cursor == .zero { video?.preferredTransform = try await track.load(.preferredTransform) }
            }
            if let track = try await asset.loadTracks(withMediaType: .audio).first {
                try audio?.insertTimeRange(range, of: track, at: cursor)
            }
            cursor = CMTimeAdd(cursor, duration)
        }
        guard let exporter = AVAssetExportSession(asset: composition, presetName: AVAssetExportPresetPassthrough) else { throw NSError(domain: "Recording", code: 11) }
        let output = FileManager.default.temporaryDirectory.appendingPathComponent("oc-circle-\(UUID().uuidString).mov")
        exporter.shouldOptimizeForNetworkUse = true
        do {
            try await exporter.export(to: output, as: .mov)
        } catch {
            try? FileManager.default.removeItem(at: output)
            throw error
        }
        return output
    }
}
