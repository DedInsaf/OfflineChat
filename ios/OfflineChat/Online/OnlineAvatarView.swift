import SwiftUI
import UIKit
import ImageIO

struct OnlineAvatarView: View {
    let profile: OnlineProfile?
    let username: String
    var size: CGFloat = 48
    @State private var image: UIImage?

    var body: some View {
        Group {
            if let image = image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
            } else {
                Circle()
                    .fill(Color.ocPrimary.opacity(0.18))
                    .overlay {
                        Text(initials)
                            .font(.system(size: size * 0.34, weight: .bold))
                            .foregroundColor(.ocPrimary)
                    }
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
        .overlay(Circle().stroke(Color.ocLine.opacity(0.55), lineWidth: 0.5))
        .task(id: profile?.avatarBase64) {
            image = nil
            guard let encoded = profile?.avatarBase64 else { return }
            let result = await Task.detached(priority: .utility) {
                OnlineThumbnailCache.image(key: "avatar:" + encoded) {
                    guard let data = Data(base64Encoded: encoded) else { return nil }
                    return CGImageSourceCreateWithData(data as CFData, nil)
                }
            }.value
            guard !Task.isCancelled else { return }
            image = result
        }
    }

    private var initials: String {
        let source = profile?.displayName.isEmpty == false ? profile!.displayName : username
        let parts = source.split(separator: " ")
        if parts.count > 1 {
            return (String(parts[0].prefix(1)) + String(parts[1].prefix(1))).uppercased()
        }
        return String(source.prefix(2)).uppercased()
    }
}

enum AvatarEncoder {
    static func encode(_ data: Data) -> String? {
        guard let image = UIImage(data: data) else { return nil }
        let maximum: CGFloat = 512
        let scale = min(1, maximum / max(image.size.width, image.size.height))
        let size = CGSize(width: max(1, image.size.width * scale), height: max(1, image.size.height * scale))
        let renderer = UIGraphicsImageRenderer(size: size)
        let resized = renderer.image { _ in
            image.draw(in: CGRect(origin: .zero, size: size))
        }
        return resized.jpegData(compressionQuality: 0.72)?.base64EncodedString()
    }
}
