// make_icon.swift <out.png>: the disk image app's icon (original artwork; the installed app uses MCC's own art).
// Then: iconutil from an .iconset of sizes 16-1024 -> launcher/Resources/AppIcon.icns
// Draws the disk image app's icon: a dark rounded square with a green ring and visor-like arc (original artwork).
import AppKit
let size = 1024.0
let img = NSImage(size: NSSize(width: size, height: size))
img.lockFocus()
let rect = NSRect(x: 80, y: 80, width: size - 160, height: size - 160)
let bg = NSBezierPath(roundedRect: rect, xRadius: 190, yRadius: 190)
NSGradient(starting: NSColor(calibratedRed: 0.12, green: 0.16, blue: 0.14, alpha: 1),
           ending: NSColor(calibratedRed: 0.04, green: 0.06, blue: 0.05, alpha: 1))!.draw(in: bg, angle: -90)
let green = NSColor(calibratedRed: 0.40, green: 0.70, blue: 0.30, alpha: 1)
let ring = NSBezierPath(ovalIn: NSRect(x: 262, y: 262, width: 500, height: 500))
ring.lineWidth = 56
green.setStroke(); ring.stroke()
let visor = NSBezierPath()
visor.appendArc(withCenter: NSPoint(x: 512, y: 440), radius: 190, startAngle: 35, endAngle: 145)
visor.lineWidth = 70; visor.lineCapStyle = .round
NSColor(calibratedRed: 0.95, green: 0.75, blue: 0.25, alpha: 1).setStroke(); visor.stroke()
img.unlockFocus()
let rep = NSBitmapImageRep(data: img.tiffRepresentation!)!
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
