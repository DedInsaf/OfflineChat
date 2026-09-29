import Foundation
import Security

enum OnlineCredentials {
    private static let service = "com.offlinechat.online-profile"
    private static let account = "session-token-v4"

    static func sessionToken() -> String {
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

        return ""
    }

    static func saveSessionToken(_ value: String) {
        clearSessionToken()
        guard !value.isEmpty else { return }
        let data = Data(value.utf8)
        let insert: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
            kSecValueData as String: data
        ]
        SecItemAdd(insert as CFDictionary, nil)
    }

    static func clearSessionToken() {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        SecItemDelete(query as CFDictionary)
    }
}
