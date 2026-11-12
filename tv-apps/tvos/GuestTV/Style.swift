// guest-tv's TV look in SwiftUI (web/tv.css): Inter for words, Antonio Light for the clock, glass
// cards with a fine light rim. Sizes are points on a 1920x1080 screen, which tvOS gives every Apple TV,
// and match the CSS (1rem = 16 points). The font files are couch-tv's (tvos/CouchTV/Fonts).
import CoreText
import SwiftUI

#if canImport(UIKit)
import UIKit
typealias PlatformImage = UIImage
#else
import AppKit
typealias PlatformImage = NSImage
#endif

enum Look {
    static let text = Color(red: 247 / 255, green: 246 / 255, blue: 243 / 255)
    static let text2 = text.opacity(0.72)
    static let text3 = text.opacity(0.5)
    static let warm = Color(red: 1, green: 216 / 255, blue: 154 / 255)
    static let safeX: CGFloat = 80
    static let safeY: CGFloat = 60

    static func inter(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        switch weight {
        case .semibold, .bold, .heavy, .black: return .custom("CouchInter-SemiBold", fixedSize: size)
        case .medium: return .custom("CouchInter-Medium", fixedSize: size)
        default: return .custom("CouchInter-Regular", fixedSize: size)
        }
    }

    static func clock(_ size: CGFloat) -> Font { .custom("CouchAntonio-Light", fixedSize: size) }

    /// Where the font files are: the app bundle; the preview renderer points it at the source folder.
    static var fontFolders: [URL] = [Bundle.main.resourceURL].compactMap { $0 }

    static func registerFonts() {
        for f in fontFolders {
            let urls = (try? FileManager.default.contentsOfDirectory(at: f, includingPropertiesForKeys: nil)) ?? []
            for u in urls where u.pathExtension == "ttf" {
                CTFontManagerRegisterFontsForURL(u as CFURL, .process, nil)
            }
        }
    }
}

extension Image {
    init(platform img: PlatformImage) {
        #if canImport(UIKit)
        self.init(uiImage: img)
        #else
        self.init(nsImage: img)
        #endif
    }
}

/// The preview renderer cannot draw the blur behind glass, so it asks for a flat tint instead.
private struct FlatGlassKey: EnvironmentKey { static let defaultValue = false }

extension EnvironmentValues {
    var flatGlass: Bool {
        get { self[FlatGlassKey.self] }
        set { self[FlatGlassKey.self] = newValue }
    }
}

/// The page's .glass: blurred, a dark tint, a fine light rim and a soft shadow.
struct Glass: ViewModifier {
    let radius: CGFloat
    @Environment(\.flatGlass) private var flat

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
        content
            .background {
                ZStack {
                    if flat {
                        shape.fill(Color(red: 22 / 255, green: 22 / 255, blue: 28 / 255).opacity(0.62))
                    } else {
                        shape.fill(.ultraThinMaterial)
                        shape.fill(Color(red: 22 / 255, green: 22 / 255, blue: 28 / 255).opacity(0.34))
                    }
                    shape.strokeBorder(Color.white.opacity(0.16), lineWidth: 1)
                }
                .shadow(color: .black.opacity(0.28), radius: 30, y: 24)
            }
    }
}

extension View {
    func glass(_ radius: CGFloat = 28) -> some View { modifier(Glass(radius: radius)) }
}

/// An SF Symbol for a WMO weather code (what Open-Meteo, and so the house computer, sends).
enum WeatherSymbol {
    static func name(_ code: Int?) -> String {
        switch code ?? -1 {
        case 0: return "sun.max"
        case 1, 2: return "cloud.sun"
        case 3: return "cloud"
        case 45, 48: return "cloud.fog"
        case 51...57: return "cloud.drizzle"
        case 61...67, 80...82: return "cloud.rain"
        case 71...77, 85, 86: return "cloud.snow"
        case 95...99: return "cloud.bolt.rain"
        default: return "thermometer.medium"
        }
    }
}
