import Foundation
import Security

enum OnlineCredentials {
    private static let service = "com.offlinechat.online-profile"
    private static let account = "owner-token-v3"
    private static let legacyDefaultsKey = "onlinechat.ownerToken.v3"

    static func ownerToken() -> String {
        let lookup: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: CFTypeRef?
        if SecItemCopyMatching(lookup as CFDictionary, &result) == errSecSuccess,
           let data = result as? Data,
           let value = String(data: data, encoding: .utf8), !value.isEmpty {
            return value
        }

        let defaults = UserDefaults.standard
        let value = defaults.string(forKey: legacyDefaultsKey).flatMap { $0.isEmpty ? nil : $0 }
            ?? (UUID().uuidString + UUID().uuidString)
        let data = Data(value.utf8)
        let insert: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
            kSecValueData as String: data
        ]
        SecItemAdd(insert as CFDictionary, nil)
        defaults.removeObject(forKey: legacyDefaultsKey)
        return value
    }
}
