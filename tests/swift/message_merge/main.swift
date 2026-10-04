import Foundation

let start = Date(timeIntervalSince1970: 1_700_000_000)
func message(_ seconds: Double = 0, status: OnlineMessageStatus = .sent, serverID: Int64? = 1) -> OnlineMessage {
    OnlineMessage(clientID: UUID(), serverID: serverID, sender: "alice", recipient: "bob",
                  text: "test", createdAt: start.addingTimeInterval(seconds), status: status)
}

let original = message()
assert(OnlineMessageMerge.inserting(original, into: [original]) == [original], "unchanged poll")
var read = original
read.status = .read
assert(OnlineMessageMerge.inserting(original, into: [read]) == [read], "receipt regression")
assert(OnlineMessageMerge.inserting(read, into: [original]) == [read], "new receipt")
var failure = original
failure.serverID = nil
failure.status = .failed
assert(OnlineMessageMerge.inserting(failure, into: [read]) == [read], "late timeout")
var pending = original
pending.serverID = nil
pending.status = .sending
assert(OnlineMessageMerge.inserting(failure, into: [pending]) == [failure], "local failure must show Retry")
assert(OnlineMessageMerge.inserting(pending, into: [failure]) == [pending], "retry must show Sending")
let earlier = message(-10, serverID: 2)
assert(OnlineMessageMerge.inserting(earlier, into: [original]) == [earlier, original], "history ordering")
var retimed = original
retimed = OnlineMessage(clientID: original.clientID, serverID: 1, sender: "alice", recipient: "bob",
                       text: "test", createdAt: start.addingTimeInterval(-20), status: .delivered)
assert(OnlineMessageMerge.inserting(retimed, into: [earlier, original]) == [retimed, earlier], "server timestamp ordering")
let history = (0..<500).map { message(Double($0), serverID: Int64($0 + 1)) }
let bounded = OnlineMessageMerge.inserting(message(500, serverID: 501), into: history)
assert(bounded.count == 500 && bounded.first?.serverID == 2 && bounded.last?.serverID == 501, "cache bound")
print("9 Swift message merge checks passed")
