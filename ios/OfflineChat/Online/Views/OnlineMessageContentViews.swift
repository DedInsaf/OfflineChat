import SwiftUI
import MapKit
import UIKit

struct OnlineLinkedText: View {
    let text: String
    var linked: AttributedString {
        var value = AttributedString(text)
        let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue)
        for match in detector?.matches(in: text, range: NSRange(text.startIndex..., in: text)) ?? [] {
            guard let url = match.url, ["http", "https", "mailto"].contains(url.scheme?.lowercased() ?? ""),
                  let range = Range(match.range, in: text), let target = Range(range, in: value) else { continue }
            value[target].link = url
            value[target].underlineStyle = .single
        }
        return value
    }
    var body: some View { Text(linked) }
}

struct OnlineLocationCard: View {
    private static let cache = NSCache<NSString, UIImage>()
    let location: OnlineLocation
    @State private var image: UIImage?
    @Environment(\.openURL) private var openURL
    var body: some View {
        Button { openYandexLocation(location) } label: {
            VStack(alignment: .leading, spacing: 6) {
                ZStack {
                    Color.ocSurfaceAlt
                    if let image { Image(uiImage: image).resizable().scaledToFit() }
                    else { Label("Местоположение", systemImage: "mappin.circle.fill").foregroundStyle(Color.ocText) }
                }
                .frame(width: 246, height: 150)
                .clipShape(RoundedRectangle(cornerRadius: 12))
                Text("📍 Местоположение").font(.subheadline.weight(.semibold))
                Text("Яндекс Карты ↗").font(.caption)
            }
        }
        .buttonStyle(.plain)
        .task(id: location) {
            let key = "\(location.latitude),\(location.longitude)" as NSString
            if let saved = Self.cache.object(forKey: key) { image = saved; return }
            let options = MKMapSnapshotter.Options()
            let coordinate = CLLocationCoordinate2D(latitude: location.latitude, longitude: location.longitude)
            options.region = MKCoordinateRegion(center: coordinate, span: MKCoordinateSpan(latitudeDelta: 0.008, longitudeDelta: 0.008))
            options.size = CGSize(width: 246, height: 150)
            options.scale = UIScreen.main.scale
            let snapshotter = MKMapSnapshotter(options: options)
            do {
                let snapshot = try await withTaskCancellationHandler {
                    try await snapshotter.start()
                } onCancel: { snapshotter.cancel() }
                guard !Task.isCancelled else { return }
                let point = snapshot.point(for: coordinate)
                image = UIGraphicsImageRenderer(size: options.size).image { _ in
                    snapshot.image.draw(at: .zero)
                    let pin = UIImage(systemName: "mappin.circle.fill")?.withTintColor(.systemRed, renderingMode: .alwaysOriginal)
                    pin?.draw(in: CGRect(x: point.x - 13, y: point.y - 26, width: 26, height: 26))
                }
                Self.cache.countLimit = 64
                if let image { Self.cache.setObject(image, forKey: key) }
            } catch { /* Coordinate card stays usable when map loading is unavailable. */ }
        }
    }
}

@MainActor
func openYandexLocation(_ location: OnlineLocation) {
    var components = URLComponents(url: location.yandexURL, resolvingAgainstBaseURL: false)!
    components.scheme = "yandexmaps"
    components.host = "maps.yandex.ru"
    guard let appURL = components.url else { return }
    UIApplication.shared.open(appURL, options: [:]) { success in
        if !success { UIApplication.shared.open(location.yandexURL) }
    }
}

struct OnlineForwardPicker: View {
    @ObservedObject var store: OnlineChatStore
    let onSelect: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    var body: some View {
        NavigationStack {
            List {
                ForEach(store.conversations) { chat in
                    Button(chat.title) { onSelect(chat.username); dismiss() }
                }
                ForEach(store.searchResults.filter { $0.username != store.username }) { profile in
                    Button("@" + profile.username) { onSelect(profile.username); dismiss() }
                }
            }
            .navigationTitle("Переслать")
            .searchable(text: $query, prompt: "Найти @username")
            .onSubmit(of: .search) { Task { await store.search(query) } }
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Отмена") { dismiss() } } }
        }
    }
}
