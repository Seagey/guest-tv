// What Guest TV shows, from the house computer: GET <computer>/api/tv/native?home=<id> (server.py
// native_screen) every 60 seconds, plus the home photo and the two QR codes it names. The computer's
// address and the home come from the build (tools/tv_app.py writes them into build/tvos/Home.xcconfig,
// which Info.plist reads as GuestTVComputer and GuestTVHome). Nothing here sends anything but GETs.
import Foundation
import SwiftUI

struct NativeScreen: Decodable, Equatable {
    struct Wifi: Decodable, Equatable { var ssid: String; var password: String }
    struct Access: Decodable, Equatable { var label: String; var code: String }
    struct Weather: Decodable, Equatable {
        var place: String?
        var temp: Double?
        var code: Double?
        var hi: Double?
        var lo: Double?
        var rain: Double?
    }

    var home: String?
    var mode: String?
    var phase: String?
    var eyebrow: String?
    var title: String?
    var sub: String?
    var welcome: String?
    var photo: String?
    var wifi: Wifi?
    var wifi_qr: String?
    var remote_qr: String?
    var remote_label: String?
    var access: [Access]?
    var weather: Weather?
    var time: String?
}

@MainActor
final class WelcomeModel: ObservableObject {
    @Published var screen: NativeScreen?
    @Published var photo: PlatformImage?
    @Published var wifiQR: PlatformImage?
    @Published var remoteQR: PlatformImage?
    @Published var answering = false          // the computer answered the last time it was asked
    /// The house computer's clock minus this Apple TV's, in whole minutes, so the clock shows the house's
    /// time even when the Apple TV is set to another time zone. Zero when they agree within two minutes.
    @Published var offset: TimeInterval = 0

    let computer: URL?
    let home: String
    private var photoURL: String?
    private var loop: Task<Void, Never>?
    private let session: URLSession

    init(computer: String? = nil, home: String? = nil) {
        let info = Bundle.main.infoDictionary ?? [:]
        self.computer = WelcomeModel.address(computer ?? info["GuestTVComputer"] as? String ?? "")
        self.home = WelcomeModel.homeId(home ?? info["GuestTVHome"] as? String ?? "") ?? "guest"
        let cfg = URLSessionConfiguration.ephemeral
        cfg.timeoutIntervalForRequest = 10
        cfg.requestCachePolicy = .reloadIgnoringLocalCacheData
        session = URLSession(configuration: cfg)
    }

    /// Only a plain http(s)://host[:port], as tools/tv_app.py writes it.
    static func address(_ s: String) -> URL? {
        let t = s.trimmingCharacters(in: .whitespaces)
        guard t.range(of: #"^https?://[A-Za-z0-9.\-:\[\]]+$"#, options: .regularExpression) != nil else { return nil }
        return URL(string: t)
    }

    static func homeId(_ s: String) -> String? {
        s.range(of: #"^[a-z0-9-]+$"#, options: .regularExpression) != nil ? s : nil
    }

    var addressText: String { computer?.absoluteString ?? "no address set" }

    func start() {
        guard loop == nil else { return }
        loop = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refresh()
                try? await Task.sleep(nanoseconds: 60 * 1_000_000_000)
            }
        }
    }

    func refresh() async {
        guard let computer, var parts = URLComponents(url: computer, resolvingAgainstBaseURL: false) else {
            answering = false
            return
        }
        parts.path = "/api/tv/native"
        parts.queryItems = [URLQueryItem(name: "home", value: home)]
        guard let url = parts.url,
              let (data, resp) = try? await session.data(from: url),
              (resp as? HTTPURLResponse)?.statusCode == 200,
              let s = try? JSONDecoder().decode(NativeScreen.self, from: data) else {
            answering = false
            return
        }
        answering = true
        screen = s
        offset = WelcomeModel.offset(s.time)
        if s.photo != photoURL {
            if let p = await image(s.photo) { photo = p; photoURL = s.photo }
            else if s.photo == nil { photo = nil; photoURL = nil }
        }
        wifiQR = s.wifi_qr == nil ? nil : await image(s.wifi_qr)
        remoteQR = s.remote_qr == nil ? nil : await image(s.remote_qr)
    }

    /// A picture the computer named, only from the computer itself.
    func image(_ link: String?) async -> PlatformImage? {
        guard let link, let url = URL(string: link), let computer,
              url.host == computer.host, url.scheme == "http" || url.scheme == "https",
              let (data, resp) = try? await session.data(from: url),
              (resp as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        return PlatformImage(data: data)
    }

    static func offset(_ time: String?) -> TimeInterval {
        guard let time else { return 0 }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        f.timeZone = .current
        guard let house = f.date(from: time) else { return 0 }
        let d = house.timeIntervalSinceNow
        return abs(d) < 120 ? 0 : (d / 60).rounded() * 60
    }
}
