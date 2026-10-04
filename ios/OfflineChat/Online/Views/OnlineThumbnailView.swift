import SwiftUI
import UIKit
import ImageIO

enum OnlineThumbnailCache {
    private static let cache: NSCache<NSString, UIImage> = {
        let value = NSCache<NSString, UIImage>()
        value.countLimit = 64
        value.totalCostLimit = 32 * 1024 * 1024
        return value
    }()

    static func image(key: String, source: () -> CGImageSource?) -> UIImage? {
        if let cached = cache.object(forKey: key as NSString) { return cached }
        guard let source = source(), let cg = CGImageSourceCreateThumbnailAtIndex(source, 0, [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: 720,
            kCGImageSourceShouldCacheImmediately: true
        ] as CFDictionary) else { return nil }
        let image = UIImage(cgImage: cg)
        cache.setObject(image, forKey: key as NSString, cost: cg.bytesPerRow * cg.height)
        return image
    }
}

struct OnlineThumbnailView: View {
    let url: URL
    @State private var image: UIImage?

    var body: some View {
        Group {
            if let image { Image(uiImage: image).resizable().scaledToFill() }
            else { ProgressView() }
        }
        .frame(width: 246, height: 184)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .task(id: url) {
            image = nil
            let result = await Task.detached(priority: .utility) {
                OnlineThumbnailCache.image(key: url.absoluteString) {
                    CGImageSourceCreateWithURL(url as CFURL, nil)
                }
            }.value
            guard !Task.isCancelled else { return }
            image = result
        }
    }
}
