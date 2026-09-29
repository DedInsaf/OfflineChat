//
//  OfflineChatTests.swift
//  OfflineChatTests
//
//  Created by Инсаф Нуртдинов on 26.08.2026.
//

import Foundation
import Testing
@testable import OfflineChat

struct OfflineChatTests {

    @Test func usernameNormalization() {
        #expect(UsernameRules.normalized("  @Anna_K-42  ") == "anna_k42")
        #expect(UsernameRules.validate("@anna_42") == "anna_42")
    }

    @Test func usernameValidationRejectsInvalidNames() {
        #expect(UsernameRules.validate("ab") == nil)
        #expect(UsernameRules.validate("42anna") == nil)
    }

    @Test func receiptStatusProgressesForward() {
        #expect(OnlineMessageStatus.sent.rank < OnlineMessageStatus.delivered.rank)
        #expect(OnlineMessageStatus.delivered.rank < OnlineMessageStatus.read.rank)
    }

    @Test func messageResolvesConversationPeer() {
        let message = OnlineMessage(
            clientID: UUID(), serverID: 1, sender: "anna", recipient: "boris",
            text: "Привет", createdAt: Date(), status: .sent
        )
        #expect(message.peer(for: "anna") == "boris")
        #expect(message.peer(for: "boris") == "anna")
    }

    @Test func attachmentSurvivesServerJSONRoundtrip() throws {
        let json = """
        {"client_id":"B5EE594A-7D2A-4A21-B15E-320D40CC4A8D","id":42,
        "sender":"anna","recipient":"boris","body":"","status":"sent",
        "created_at":"2026-09-28T10:00:00Z",
        "attachment":{"name":"Документ.pdf","size":1234,"sha256":"abcd"}}
        """.data(using: .utf8)!
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let message = try decoder.decode(OnlineMessage.self, from: json)
        #expect(message.attachment?.name == "Документ.pdf")
        #expect(message.previewText == "📎 Документ.pdf")
        #expect(message.serverID == 42)
    }

    @Test func textMessageWithoutAttachmentRemainsCompatible() throws {
        let json = """
        {"client_id":"B5EE594A-7D2A-4A21-B15E-320D40CC4A8D","id":43,
        "sender":"anna","recipient":"boris","body":"Привет","status":"delivered",
        "created_at":"2026-09-28T10:00:00Z","attachment":null}
        """.data(using: .utf8)!
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let message = try decoder.decode(OnlineMessage.self, from: json)
        #expect(message.attachment == nil)
        #expect(message.previewText == "Привет")
    }

    @Test func unsafeAttachmentNamesAreRejected() {
        #expect(OnlineFiles.safeName("Документ.pdf"))
        #expect(!OnlineFiles.safeName("../secret.txt"))
        #expect(!OnlineFiles.safeName("folder/file.txt"))
        #expect(!OnlineFiles.safeName("bad\nname"))
    }

    @Test func attachmentKindsChooseUsefulCards() {
        let photo = OnlineAttachment(name: "cat.HEIC", size: 1, sha256: "x")
        let video = OnlineAttachment(name: "clip.mp4", size: 1, sha256: "x")
        #expect(photo.kind == "photo")
        #expect(video.kind == "video")
        #expect(OnlineAttachment(name: "archive.zip", size: 1, sha256: "x").kind == "file")
        #expect(OnlineMessage(clientID: UUID(), sender: "anna", recipient: "boris", text: "",
                              createdAt: Date(), status: .sent, attachment: photo).previewText == "Фото")
        #expect(OnlineMessage(clientID: UUID(), sender: "anna", recipient: "boris", text: "",
                              createdAt: Date(), status: .sent, attachment: video).previewText == "Видео")
    }

    @Test func pickedMediaCanBeStagedAndEncoded() async throws {
        let id = UUID()
        let original = Data([0, 1, 2, 3, 254, 255])
        let attachment = try await OnlineFiles.stage(original, name: "Фото-test.jpg", id: id)
        let encoded = try await OnlineFiles.encoded(attachment, id: id)
        #expect(Data(base64Encoded: encoded) == original)
        #expect(attachment.size == original.count)
        await OnlineFiles.removeStaged(id)
    }
}
