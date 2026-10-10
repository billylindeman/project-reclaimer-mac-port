// Tools: the fixes and chores that would otherwise need Terminal or a trip into hidden folders. Each runs one
// tools.py command and says what happened in plain words.
import AppKit
import SwiftUI

struct ModItem: Decodable, Identifiable, Equatable {
    let id: String
    let title: String
    let bytes: Int64
}

@MainActor
final class ToolsModel: ObservableObject {
    @Published var busy: String?                    // the tool running now
    @Published var result: (text: String, ok: Bool)?
    @Published var mods: [ModItem] = []
    @Published var freeBytes: Int64 = 0
    @Published var repairProgress: Double?
    @Published var repairRemaining: String?
    @Published var repairQR: QRGrid?
    private var running: LineProcess?

    /// Run a tools.py command; `done` gets its last line.
    func run(_ title: String, _ args: [String], done: @escaping (String) -> Void = { _ in }) {
        stream(title, args, onLine: { _ in }, done: done)
    }

    /// Like run, also handing every line to `onLine` as it arrives (Repair's QR code and progress).
    func stream(_ title: String, _ args: [String], onLine: @escaping (String) -> Void,
                done: @escaping (String) -> Void) {
        busy = title
        result = nil
        var last = ""
        running = python("tools.py", args, onLine: { line in
            last = line
            onLine(line)
        }, onExit: { [self] _ in
            busy = nil
            running = nil
            done(last)
        })
        if running == nil { busy = nil; result = ("That tool couldn't start.", false) }
    }

    func say(_ text: String, ok: Bool = true) { result = (text, ok) }

    func error(in line: String) -> String? { line.hasPrefix("error: ") ? String(line.dropFirst(7)) : nil }

    func loadMods() {
        run("Looking at your mods…", ["mods"]) { [self] line in
            struct Listing: Decodable { let free_bytes: Int64; let mods: [ModItem] }
            if let data = line.data(using: .utf8), let l = try? JSONDecoder().decode(Listing.self, from: data) {
                mods = l.mods
                freeBytes = l.free_bytes
            }
            result = nil
        }
    }

    func repair() {
        var collector = QRCollector()
        var estimator = RateEstimator()
        repairProgress = nil
        stream("Checking Halo 3's files against Steam…", ["repair"], onLine: { [self] line in
            switch SetupEvent(line: line) {
            case .steam(let e):
                collector.handle(e)
                if e == .qrEnd { repairQR = collector.current }
            case .progress(let v):
                repairQR = nil
                repairProgress = v
                repairRemaining = estimator.remaining(fraction: v)
            default: break
            }
        }, done: { [self] last in
            repairQR = nil
            repairProgress = nil
            repairRemaining = nil
            if let e = error(in: last) { say(e, ok: false) }
            else { say("Halo 3's files are all there and match Steam.") }
        })
    }
}

struct ToolsSheet: View {
    @ObservedObject var launcher: Launcher
    @ObservedObject var t: ToolsModel
    @Environment(\.dismiss) private var dismiss
    @State private var confirm: Confirm?

    enum Confirm: Identifiable {
        case removeMod(ModItem), resetGraphics, switchSteam, uninstall
        var id: String {
            switch self {
            case .removeMod(let m): return "mod-\(m.id)"
            case .resetGraphics: return "graphics"
            case .switchSteam: return "steam"
            case .uninstall: return "uninstall"
            }
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("Tools").font(.title2.bold())
                Spacer()
                Button("Done") { dismiss() }.keyboardShortcut(.cancelAction)
            }
            if let busy = t.busy {
                HStack(spacing: 10) { ProgressView().controlSize(.small); Text(busy).font(.callout) }
            }
            if let r = t.result {
                Label(r.text, systemImage: r.ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .font(.callout).foregroundStyle(r.ok ? accent : .orange)
                    .fixedSize(horizontal: false, vertical: true)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    section("The game") {
                        tool("Force quit the game", "Force Quit",
                             "For a frozen game window that won't close, even with Force Quit.") {
                            t.run("Stopping the game…", ["force-quit"]) { _ in
                                launcher.gameForceQuit()
                                t.say("The game was stopped.")
                            }
                        }
                        tool("Repair game files", "Repair",
                             "Checks Halo 3's files against Steam and downloads anything missing or damaged. Quit the game first.") {
                            t.repair()
                        }
                        if t.repairQR != nil { SignInCard(qr: t.repairQR) }
                        if let p = t.repairProgress {
                            ProgressView(value: p).tint(accent)
                            Text("\(Int(p * 100))%" + (t.repairRemaining.map { " · \($0)" } ?? ""))
                                .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                        }
                    }
                    section("Mods and disk space") {
                        Text("\(gigabytes(Double(t.freeBytes))) free on this Mac. Mods download again by themselves when a server needs them.")
                            .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                        if t.mods.isEmpty {
                            Text("No Workshop mods downloaded yet.").font(.callout).foregroundStyle(.secondary)
                        }
                        ForEach(t.mods) { mod in
                            HStack {
                                Text(mod.title).font(.callout).lineLimit(1)
                                Spacer()
                                Text(gigabytes(Double(mod.bytes))).font(.callout.monospacedDigit()).foregroundStyle(.secondary)
                                Button("Remove") { confirm = .removeMod(mod) }.disabled(t.busy != nil)
                            }
                        }
                    }
                    section("Settings") {
                        tool("Restore recommended graphics", "Restore",
                             "Puts back the graphics settings tuned for Macs (windowed, 60 fps). Quit the game first.") {
                            confirm = .resetGraphics
                        }
                        tool("Use a different Steam account", "Switch…",
                             "Forgets the Steam account used for mods and shows a new QR code.") {
                            confirm = .switchSteam
                        }
                    }
                    section("Help") {
                        tool("Send a report", "Make Report",
                             "Puts the logs in a zip file on your Desktop to send to whoever set this up for you. It doesn't include your Steam account.") {
                            t.run("Making the report…", ["report"]) { last in
                                if last.hasPrefix("ok ") {
                                    let url = URL(fileURLWithPath: String(last.dropFirst(3)))
                                    NSWorkspace.shared.activateFileViewerSelecting([url])
                                    t.say("The report is on your Desktop: \(url.lastPathComponent)")
                                } else { t.say(t.error(in: last) ?? "The report couldn't be made.", ok: false) }
                            }
                        }
                    }
                    section("Remove") {
                        tool("Uninstall Project Reclaimer", "Uninstall…",
                             "Removes the app, Halo 3's files, mods and the network setting from this Mac. Your Steam account isn't affected.",
                             role: .destructive) {
                            confirm = .uninstall
                        }
                    }
                }
            }
            .frame(maxHeight: 520)
        }
        .padding(22)
        .frame(width: 480)
        .disabled(t.busy != nil && t.repairQR == nil)
        .onAppear { if launcher.logging { t.loadMods() } }  // (not in --render-states snapshots)
        .alert(item: $confirm) { c in alert(for: c) }
    }

    private func alert(for c: Confirm) -> Alert {
        switch c {
        case .removeMod(let mod):
            return Alert(title: Text("Remove \(mod.title)?"),
                         message: Text("Frees \(gigabytes(Double(mod.bytes))). It downloads again if a server needs it."),
                         primaryButton: .destructive(Text("Remove")) {
                             t.run("Removing \(mod.title)…", ["remove-mod", mod.id]) { last in
                                 if let e = t.error(in: last) { t.say(e, ok: false) } else { t.loadMods(); t.say("\(mod.title) was removed.") }
                             }
                         }, secondaryButton: .cancel())
        case .resetGraphics:
            return Alert(title: Text("Restore recommended graphics?"),
                         message: Text("Your graphics settings are replaced; other settings stay."),
                         primaryButton: .default(Text("Restore")) {
                             t.run("Restoring graphics settings…", ["reset-graphics"]) { last in
                                 t.say(t.error(in: last) ?? "Done. The game uses them the next time it starts.", ok: t.error(in: last) == nil)
                             }
                         }, secondaryButton: .cancel())
        case .switchSteam:
            return Alert(title: Text("Use a different Steam account?"),
                         message: Text("A QR code appears in the main window: scan it with the Steam app of the account you want."),
                         primaryButton: .default(Text("Continue")) {
                             t.run("Forgetting the Steam account…", ["forget-steam"]) { _ in
                                 dismiss()
                                 launcher.signIn()
                             }
                         }, secondaryButton: .cancel())
        case .uninstall:
            return Alert(title: Text("Uninstall Project Reclaimer?"),
                         message: Text("This deletes Halo 3's files (about 35 GB), your downloaded mods and the app. The game closes if it's running, and macOS asks for your password to remove the network setting."),
                         primaryButton: .destructive(Text("Uninstall")) {
                             t.run("Uninstalling…", ["uninstall"]) { last in
                                 if let e = t.error(in: last) { t.say(e, ok: false); return }
                                 let done = NSAlert()
                                 done.messageText = "Project Reclaimer was removed."
                                 done.informativeText = "Thanks for playing!"
                                 done.runModal()
                                 NSApp.terminate(nil)
                             }
                         }, secondaryButton: .cancel())
        }
    }

    private func section<Content: View>(_ title: String, @ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).font(.headline)
            content()
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(.background.secondary))
    }

    private func tool(_ title: String, _ button: String, _ detail: String, role: ButtonRole? = nil,
                      action: @escaping () -> Void) -> some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.callout.weight(.semibold))
                Text(detail).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            Button(button, role: role, action: action).controlSize(.large).fixedSize()
        }
    }
}
