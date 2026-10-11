// The Mac's gamepads, for the "Force XInput" list in the window. Wine only shows Microsoft pads to the game's
// XInput by itself; for the rest, the choice for each pad is stored in the Wine prefix's registry just before the
// game starts (Launcher.applyGamepadOverrides, using LauncherCore.applyWineBusOverrides).
import Foundation
import IOKit
import IOKit.hid

struct GamepadInfo: Identifiable, Equatable {
    let id: String        // Wine's key for the pad's settings ("057E/2009"; see wineBusOverrideKey)
    let name: String
    let vid: Int
    let pid: Int
    let bluetooth: Bool
}

/// Watches for gamepads and joysticks (HID Generic Desktop "gamepad" and "joystick", the same devices Wine's
/// winebus sees) coming and going. Wired up by Launcher.start; delivers on the main actor.
final class GamepadMonitor {
    var onUpdate: (@MainActor ([GamepadInfo]) -> Void)?
    private var manager: IOHIDManager?
    private var pads: [GamepadInfo] = []

    func start() {
        let joystick: CFDictionary = [kIOHIDDeviceUsagePageKey as String: kHIDPage_GenericDesktop,
                                     kIOHIDDeviceUsageKey as String: kHIDUsage_GD_Joystick] as NSDictionary
        let gamepad: CFDictionary = [kIOHIDDeviceUsagePageKey as String: kHIDPage_GenericDesktop,
                                     kIOHIDDeviceUsageKey as String: kHIDUsage_GD_GamePad] as NSDictionary
        let m = IOHIDManagerCreate(kCFAllocatorDefault, IOOptionBits(0))
        IOHIDManagerSetDeviceMatchingMultiple(m, [joystick, gamepad] as CFArray)
        let context = Unmanaged.passUnretained(self).toOpaque()
        IOHIDManagerRegisterDeviceMatchingCallback(m, { context, _, _, device in
            Unmanaged<GamepadMonitor>.fromOpaque(context!).takeUnretainedValue().add(device)
        }, context)
        IOHIDManagerRegisterDeviceRemovalCallback(m, { context, _, _, device in
            Unmanaged<GamepadMonitor>.fromOpaque(context!).takeUnretainedValue().remove(device)
        }, context)
        IOHIDManagerScheduleWithRunLoop(m, CFRunLoopGetMain(), CFRunLoopMode.defaultMode!.rawValue)
        IOHIDManagerOpen(m, 0)
        manager = m
    }

    private func add(_ device: IOHIDDevice) {
        if let info = Self.info(from: device), !pads.contains(info) { pads.append(info) }
        deliver()
    }

    private func remove(_ device: IOHIDDevice) {
        if let info = Self.info(from: device), let i = pads.firstIndex(of: info) { pads.remove(at: i) }
        deliver()
    }

    /// Two identical pads share one Wine setting, so they share one row too.
    private func deliver() {
        var seen = Set<String>()
        let list = pads.sorted { ($0.name, $0.id) < ($1.name, $1.id) }.filter { seen.insert($0.id).inserted }
        DispatchQueue.main.async { [weak self] in
            guard let self, let onUpdate = self.onUpdate else { return }
            MainActor.assumeIsolated { onUpdate(list) }
        }
    }

    static func info(from device: IOHIDDevice) -> GamepadInfo? {
        func number(_ key: String) -> Int? { (IOHIDDeviceGetProperty(device, key as CFString) as? NSNumber)?.intValue }
        guard let vid = number(kIOHIDVendorIDKey), let pid = number(kIOHIDProductIDKey), vid != 0x845e else { return nil }
        let name = (IOHIDDeviceGetProperty(device, kIOHIDProductKey as CFString) as? String) ?? "Controller"
        let transport = (IOHIDDeviceGetProperty(device, kIOHIDTransportKey as CFString) as? String) ?? ""
        return GamepadInfo(id: wineBusOverrideKey(vid: vid, pid: pid), name: name, vid: vid, pid: pid,
                           bluetooth: transport.caseInsensitiveCompare("bluetooth") == .orderedSame)
    }
}
