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
}
