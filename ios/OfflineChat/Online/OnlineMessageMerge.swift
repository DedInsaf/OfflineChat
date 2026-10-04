import Foundation

enum OnlineMessageMerge {
    static func inserting(_ incoming: OnlineMessage, into existing: [OnlineMessage]) -> [OnlineMessage] {
        var list = existing
        var needsSort = false
        if let index = list.firstIndex(where: {
            $0.clientID == incoming.clientID || ($0.serverID != nil && $0.serverID == incoming.serverID)
        }) {
            // A failed send can finish after sync has already accepted it.
            if list[index].serverID != nil && incoming.serverID == nil { return existing }
            var merged = incoming
            // Local upload/send failures are not delivery receipts: expose them
            // so Retry is available, instead of leaving a spinner forever.
            if list[index].status.rank > incoming.status.rank && (incoming.status != .failed || list[index].serverID != nil) {
                merged.status = list[index].status
            }
            if list[index] == merged { return existing }
            needsSort = list[index].createdAt != merged.createdAt
            list[index] = merged
        } else {
            list.append(incoming)
            needsSort = true
        }
        if needsSort {
            list.sort {
                if $0.createdAt == $1.createdAt { return $0.clientID.uuidString < $1.clientID.uuidString }
                return $0.createdAt < $1.createdAt
            }
        }
        return Array(list.suffix(500))
    }
}
