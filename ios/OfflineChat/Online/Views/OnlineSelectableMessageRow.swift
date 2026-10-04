import SwiftUI

/// A fixed gutter keeps bubbles in place when selection starts or ends.
struct OnlineSelectableMessageRow<Content: View>: View {
    let selecting: Bool
    let selected: Bool
    let onSelect: () -> Void
    @ViewBuilder let content: () -> Content

    var body: some View {
        HStack(alignment: .center, spacing: 4) {
            Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                .font(.system(size: 22, weight: .regular))
                .foregroundStyle(selected ? Color.ocPrimary : Color.ocMuted.opacity(0.55))
                .frame(width: 28).opacity(selecting ? 1 : 0)
                .accessibilityHidden(true)
            content().allowsHitTesting(!selecting).accessibilityHidden(selecting)
        }
        .padding(.vertical, 2)
        .background(selected && selecting ? Color.ocPrimary.opacity(0.08) : Color.clear,
                    in: RoundedRectangle(cornerRadius: 12))
        .overlay {
            if selecting {
                Button(action: onSelect) { Color.clear.contentShape(Rectangle()) }
                    .buttonStyle(.plain)
                    .accessibilityLabel(selected ? "Сообщение выбрано. Снять выделение" : "Выбрать сообщение")
                    .accessibilityAddTraits(selected ? .isSelected : [])
            }
        }
    }
}
