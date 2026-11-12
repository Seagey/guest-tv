// guest-tv's welcome screen drawn natively (tvOS has no web view), laid out like the TV page
// (web/index.html, web/tv.css): the home's photo full screen under a soft scrim, the date and weather
// line, the big clock, the eyebrow, title and sub line low on the left, and a row of glass cards:
// 1 Join the Wi-Fi (QR, network, password), 2 Guest remote (QR), the weather, and the door codes only
// when the computer gives them. Nothing on it takes focus: it is a screen to read, and the Siri remote's
// Back button leaves it for Apple's home.
import SwiftUI

struct WelcomeView: View {
    @EnvironmentObject var model: WelcomeModel
    /// The preview renderer draws one fixed moment; the app ticks with the clock.
    var fixedNow: Date? = nil

    var body: some View {
        Group {
            if let fixedNow {
                screen(fixedNow)
            } else {
                TimelineView(.everyMinute) { ctx in screen(ctx.date) }
            }
        }
        .frame(width: 1920, height: 1080)
        .background(Color(red: 11 / 255, green: 11 / 255, blue: 14 / 255))
        .ignoresSafeArea()
    }

    private func screen(_ date: Date) -> some View {
        let now = date.addingTimeInterval(model.offset)
        let hour = Calendar.current.component(.hour, from: now)
        let late = hour >= 21 || hour < 5
        return ZStack(alignment: .topLeading) {
            backdrop(late: late)
            dateLine(now)
                .frame(width: 1920)
                .padding(.top, 64)
            clock(now, late: late)
                .frame(width: 1920)
                .padding(.top, 38)
            if let s = model.screen {
                // the welcome sits low on the left, just above the cards (tv.css .hello)
                hello(s)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
                    .padding(.leading, Look.safeX)
                    .padding(.bottom, Look.safeY + 260 + 36)
                cards(s)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
                    .padding(.horizontal, Look.safeX)
                    .padding(.bottom, Look.safeY)
                if !model.answering {
                    Text("Waiting for the house computer")
                        .font(Look.inter(23, .semibold))
                        .foregroundStyle(Look.text)
                        .padding(.horizontal, 22).padding(.vertical, 12)
                        .glass(24)
                        .padding(.leading, Look.safeX).padding(.top, Look.safeY)
                }
            } else {
                waiting
            }
        }
        .frame(width: 1920, height: 1080, alignment: .topLeading)
        .clipped()
    }

    // ---------- the photo and the scrim (tv.css .scene .shade) ----------
    @ViewBuilder private func backdrop(late: Bool) -> some View {
        ZStack {
            if let p = model.photo {
                Image(platform: p).resizable().scaledToFill()
                    .frame(width: 1920, height: 1080).clipped()
                    .scaleEffect(1.02)
            } else {
                LinearGradient(colors: [Color(red: 28 / 255, green: 30 / 255, blue: 38 / 255),
                                        Color(red: 11 / 255, green: 11 / 255, blue: 14 / 255)],
                               startPoint: .top, endPoint: .bottom)
            }
            LinearGradient(stops: [.init(color: .black.opacity(0.36), location: 0), .init(color: .clear, location: 0.24)],
                           startPoint: .top, endPoint: .bottom)
            LinearGradient(stops: [.init(color: .clear, location: 0.46), .init(color: .black.opacity(0.42), location: 0.66),
                                   .init(color: .black.opacity(0.78), location: 1)],
                           startPoint: .top, endPoint: .bottom)
            if late { Color.black.opacity(0.26) }
        }
        .frame(width: 1920, height: 1080)
        .clipped()
    }

    // ---------- the date, the weather and the clock ----------
    private static let dayFormat: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_AU")
        f.dateFormat = "EEEE d MMMM"
        return f
    }()

    private func dateLine(_ now: Date) -> some View {
        HStack(spacing: 0) {
            Text(WelcomeView.dayFormat.string(from: now)).font(Look.inter(32, .medium))
            if let w = model.screen?.weather, let t = w.temp {
                Image(systemName: WeatherSymbol.name(w.code.map { Int($0) }))
                    .font(.system(size: 28, weight: .regular))
                    .padding(.leading, 18).padding(.trailing, 8)
                Text("\(Int(t.rounded()))° \(w.place ?? "")").font(Look.inter(32)).foregroundStyle(.white.opacity(0.82))
            }
        }
        .foregroundStyle(Look.text)
        .shadow(color: .black.opacity(0.3), radius: 9, y: 2)
    }

    private func clock(_ now: Date, late: Bool) -> some View {
        let c = Calendar.current.dateComponents([.hour, .minute], from: now)
        let h = (c.hour ?? 0) % 12 == 0 ? 12 : (c.hour ?? 0) % 12
        let hm = "\(h):" + String(format: "%02d", c.minute ?? 0)
        return Text(hm)
            .font(Look.clock(310))
            .kerning(-6)
            .foregroundStyle(LinearGradient(colors: [.white.opacity(0.92), .white.opacity(0.68)],
                                            startPoint: .topLeading, endPoint: .bottomTrailing))
            .opacity(late ? 0.8 : 1)
            .shadow(color: .black.opacity(0.22), radius: 2)
            .shadow(color: .black.opacity(0.18), radius: 14, y: 6)
    }

    // ---------- the welcome, low on the left like a title on Apple TV ----------
    private func hello(_ s: NativeScreen) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            if let e = s.eyebrow, !e.isEmpty {
                Text(e.uppercased()).font(Look.inter(23, .semibold)).kerning(3.2).foregroundStyle(.white.opacity(0.78))
            }
            Text(s.title ?? "Welcome").font(Look.inter(56, .semibold)).kerning(-1.2).foregroundStyle(Look.text)
                .lineLimit(1).minimumScaleFactor(0.6)
            if let sub = s.sub, !sub.isEmpty {
                Text(sub).font(Look.inter(28)).foregroundStyle(.white.opacity(0.86)).lineLimit(1)
            }
            if let w = s.welcome?.trimmingCharacters(in: .whitespacesAndNewlines), !w.isEmpty {
                Text(w).font(Look.inter(24)).foregroundStyle(Look.text2).lineLimit(2).padding(.top, 4)
            }
        }
        .frame(maxWidth: 1180, alignment: .leading)
        .shadow(color: .black.opacity(0.45), radius: 12, y: 2)
    }

    // ---------- the cards ----------
    private func cards(_ s: NativeScreen) -> some View {
        let wifi = s.wifi.flatMap { $0.ssid.isEmpty ? nil : $0 }
        let codes = (s.access ?? []).filter { !$0.code.isEmpty }
        return HStack(alignment: .top, spacing: 20) {
            if let wifi {
                Card(title: "1 · Join the Wi-Fi", symbol: "wifi", width: 600) {
                    HStack(alignment: .center, spacing: 26) {
                        QR(image: model.wifiQR)
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Network").font(Look.inter(23)).foregroundStyle(Look.text3)
                            Text(wifi.ssid).font(Look.inter(30, .semibold)).lineLimit(1).minimumScaleFactor(0.5)
                            Text("Password").font(Look.inter(23)).foregroundStyle(Look.text3).padding(.top, 10)
                            Text(wifi.password.isEmpty ? "None" : wifi.password)
                                .font(Look.inter(34, .semibold)).lineLimit(1).minimumScaleFactor(0.45)
                        }
                    }
                }
            }
            let label = s.remote_label ?? "Guest remote"
            Card(title: (wifi != nil ? "2 · " : "") + label, symbol: "iphone", width: 500) {
                HStack(alignment: .center, spacing: 26) {
                    QR(image: model.remoteQR)
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Scan with your phone's camera").font(Look.inter(28, .semibold)).lineLimit(3)
                        Text(label == "Guest remote" ? "The remote for this TV, on your phone." : "The house guide, on your phone.")
                            .font(Look.inter(23)).foregroundStyle(Look.text2).lineLimit(3)
                    }
                }
            }
            if let w = s.weather, let t = w.temp {
                Card(title: w.place ?? "Weather", symbol: WeatherSymbol.name(w.code.map { Int($0) }), width: 300) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("\(Int(t.rounded()))°").font(Look.inter(72, .semibold)).kerning(-2)
                        if let hi = w.hi, let lo = w.lo {
                            Text("High \(Int(hi.rounded()))° · Low \(Int(lo.rounded()))°").font(Look.inter(23)).foregroundStyle(Look.text2)
                        }
                        if let r = w.rain, r > 0 {
                            Text("Rain \(Int(r.rounded()))%").font(Look.inter(23)).foregroundStyle(Look.text2)
                        }
                    }
                }
            }
            if !codes.isEmpty {
                Card(title: "Door codes", symbol: "key", width: 300) {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(Array(codes.prefix(3).enumerated()), id: \.offset) { _, a in
                            VStack(alignment: .leading, spacing: 0) {
                                Text(a.label.isEmpty ? "Code" : a.label).font(Look.inter(23)).foregroundStyle(Look.text2).lineLimit(1)
                                Text(a.code).font(Look.inter(34, .semibold)).monospacedDigit().lineLimit(1).minimumScaleFactor(0.5)
                            }
                        }
                    }
                }
            }
        }
        .foregroundStyle(Look.text)
    }

    // ---------- before the computer has ever answered ----------
    private var waiting: some View {
        VStack(spacing: 18) {
            Text("Waiting for the house computer").font(Look.inter(44, .semibold)).foregroundStyle(Look.text)
            Text(model.computer == nil
                 ? "This copy of Guest TV was built without the house computer's address. Run tools/tv_app.py install again."
                 : "Guest TV asks \(model.addressText) every minute. Is the computer on, and on this Wi-Fi?")
                .font(Look.inter(26)).foregroundStyle(Look.text2).multilineTextAlignment(.center).frame(maxWidth: 1100)
        }
        .padding(.horizontal, 56).padding(.vertical, 40)
        .glass(32)
        .frame(width: 1920, height: 1080)
        .offset(y: 160)
    }
}

/// One glass card: a small heading with its symbol, then what it holds.
struct Card<Content: View>: View {
    let title: String
    let symbol: String?
    let width: CGFloat
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                if let symbol { Image(systemName: symbol).font(.system(size: 24, weight: .medium)) }
                Text(title).font(Look.inter(23, .semibold)).lineLimit(1)
            }
            .foregroundStyle(Look.text2)
            content()
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 26).padding(.vertical, 22)
        .frame(width: width, height: 260, alignment: .topLeading)
        .glass(28)
    }
}

/// A QR code on white, drawn with hard pixels so a phone reads it from the couch.
struct QR: View {
    let image: PlatformImage?
    var size: CGFloat = 164

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 14, style: .continuous).fill(.white)
            if let image {
                Image(platform: image).interpolation(.none).resizable().scaledToFit().padding(8)
            } else {
                Image(systemName: "qrcode").font(.system(size: 64)).foregroundStyle(.black.opacity(0.2))
            }
        }
        .frame(width: size, height: size)
    }
}
