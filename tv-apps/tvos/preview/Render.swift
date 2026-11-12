// Draws Guest TV's screen to PNG files on a Mac, from the app's own SwiftUI views, talking to a house
// computer (or the stand-in, preview/standin.py). For checking the look without an Apple TV or the tvOS
// Simulator. It is not the Simulator: there is no blur behind the glass cards. render.sh builds and runs it.
import AppKit
import SwiftUI

@main
struct Render {
    @MainActor
    static func main() async {
        let args = CommandLine.arguments
        guard args.count >= 4 else {
            print("usage: render <fonts folder> <computer address> <out folder> [home ...]")
            exit(2)
        }
        Look.fontFolders = [URL(fileURLWithPath: args[1])]
        Look.registerFonts()
        let out = URL(fileURLWithPath: args[3])
        try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
        let homes = args.count > 4 ? Array(args[4...]) : ["guest"]

        var when = DateComponents()
        (when.year, when.month, when.day, when.hour, when.minute) = (2026, 11, 2, 8, 47)
        let now = Calendar.current.date(from: when) ?? Date()

        func shot(_ name: String, _ model: WelcomeModel) {
            let v = WelcomeView(fixedNow: now).environmentObject(model).environment(\.flatGlass, true)
                .frame(width: 1920, height: 1080).environment(\.colorScheme, .dark)
            let r = ImageRenderer(content: v)
            r.scale = 1
            guard let cg = r.cgImage else { print("no picture for \(name)"); return }
            let url = out.appendingPathComponent(name + ".png")
            try? NSBitmapImageRep(cgImage: cg).representation(using: .png, properties: [:])?.write(to: url)
            print("wrote \(url.path)")
        }

        for home in homes {
            let model = WelcomeModel(computer: args[2], home: home)
            await model.refresh()
            print("\(home): answering \(model.answering), title \(model.screen?.title ?? "none"), photo \(model.photo != nil), qr \(model.wifiQR != nil)/\(model.remoteQR != nil)")
            shot("welcome-\(home)", model)
        }
        shot("waiting", WelcomeModel(computer: "http://127.0.0.1:9", home: "guest"))
    }
}
