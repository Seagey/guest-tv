' guest-tv's welcome screen on a Roku.
'
' Roku channels are not web pages, so this draws the TV page (web/index.html) again natively, from
' GET <computer>/api/tv/native?home=<id> (server.py native_screen): the home's photo full screen under a
' soft shade, the clock and the date with the weather, the eyebrow, the big welcome and the line under it,
' then a row of cards: "1 · Join the Wi-Fi" (QR, network, password), "2 · Guest remote" (QR), the weather,
' and the door codes only when the computer includes them. Under that, the apps the guest may open, which
' open through the computer (POST /api/tv/app). It asks again every 60 seconds. While the computer does
' not answer it shows "Welcome, Waiting for the house computer" and asks every 10 seconds, as the Samsung
' and LG app does (tv-apps/boot.html).
'
' The computer's address and the home are baked into pkg:/config.json by tv_roku.build; a launch
' parameter (launch/dev?home=<id>) may change the home. Nothing a guest types is shown or sent from here.
'
' Checked against a BrightScript linter only, not yet on a real Roku (docs/ROKU.md).

sub init()
    m.cfg = readJson("pkg:/config.json")
    if m.cfg = invalid then m.cfg = {}
    m.base = ""
    if type(m.cfg.url) = "roString" or type(m.cfg.url) = "String" then m.base = m.cfg.url
    m.homeId = ""
    if type(m.cfg.home) = "roString" or type(m.cfg.home) = "String" then m.homeId = m.cfg.home
    m.fonts = {}
    m.tasks = []
    m.data = invalid
    m.up = false
    m.offset = invalid      ' seconds between this Roku's clock and the house's, once the computer said
    m.clockText = ""
    m.apps = []
    m.focus = 0
    m.pills = []
    m.loads = 0

    m.top.findNode("clock").font = font("Antonio-Light", 320)
    m.top.findNode("clock").color = "0xFFFFFFD8"
    m.top.findNode("date").font = font("Inter-Medium", 32)
    m.top.findNode("date").color = "0xF7F6F3FF"
    m.top.findNode("eyebrow").font = font("Inter-Medium", 24)
    m.top.findNode("eyebrow").color = "0xFFFFFFC8"
    m.top.findNode("title").font = font("Inter-Medium", 60)
    m.top.findNode("title").color = "0xF7F6F3FF"
    m.top.findNode("sub").font = font("Inter-Regular", 30)
    m.top.findNode("sub").color = "0xFFFFFFDC"
    m.top.findNode("waitBig").font = font("Inter-Medium", 44)
    m.top.findNode("waitBig").color = "0xF7F6F3FF"
    m.top.findNode("waitSmall").font = font("Inter-Regular", 28)
    m.top.findNode("waitSmall").color = "0xF7F6F399"
    m.top.findNode("toastText").font = font("Inter-Medium", 26)
    m.top.findNode("toastText").color = "0xF7F6F3FF"

    m.top.findNode("tick").observeField("fire", "onTick")
    m.top.findNode("refresh").observeField("fire", "onRefresh")
    m.top.findNode("toastTimer").observeField("fire", "onToastDone")
    m.top.findNode("tick").control = "start"
    m.top.findNode("refresh").control = "start"

    if m.base = ""
        waiting("Guest TV", "Build this channel with the computer's address (tools/tv_app.py install)")
    else
        waiting("Welcome", "Waiting for the house computer")
        load()
    end if
    onTick()
end sub

' The home from a launch parameter (main.brs checks it is a plain id).
sub onHome()
    h = m.top.home
    if h = "" or h = m.homeId then return
    m.homeId = h
    m.apps = []
    drawApps()
    if m.base <> "" then load()
end sub

' ---------- small helpers ----------
function readJson(path as String) as Dynamic
    text = ReadAsciiFile(path)
    if text = "" then return invalid
    return ParseJson(text)
end function

function font(name as String, size as Integer) as Object
    key = name + "-" + size.toStr()
    if not m.fonts.doesExist(key)
        f = CreateObject("roSGNode", "Font")
        f.uri = "pkg:/fonts/" + name + ".ttf"
        f.size = size
        m.fonts[key] = f
    end if
    return m.fonts[key]
end function

function label(text as String, fontName as String, size as Integer, color as String, x as Integer, y as Integer, w as Integer) as Object
    l = CreateObject("roSGNode", "Label")
    l.font = font(fontName, size)
    l.color = color
    l.text = text
    l.wrap = false
    l.translation = [x, y]
    if w > 0 then l.width = w
    return l
end function

function poster(uri as String, x as Integer, y as Integer, w as Integer, h as Integer) as Object
    p = CreateObject("roSGNode", "Poster")
    p.uri = uri
    p.translation = [x, y]
    p.width = w
    p.height = h
    return p
end function

function textWidth(text as String, fontName as String, size as Integer) as Integer
    l = label(text, fontName, size, "0xFFFFFFFF", 0, 0, 0)
    return Int(l.boundingRect().width)
end function

' Any JSON value as text: "" for null or anything that is not a string or a number.
function txt(v as Dynamic) as String
    if v = invalid then return ""
    if type(v) = "roString" or type(v) = "String" then return v
    if GetInterface(v, "ifToStr") <> invalid then return v.toStr()
    return ""
end function

function isText(v as Dynamic) as Boolean
    return (type(v) = "roString" or type(v) = "String") and v <> ""
end function

sub clearGroup(g as Object)
    g.removeChildrenIndex(g.getChildCount(), 0)
end sub

' A web request. onFetched() sorts the answers by their tag.
sub fetch(tag as String, url as String, method = "GET" as String, body = "" as String)
    t = CreateObject("roSGNode", "Fetch")
    t.tag = tag
    t.url = url
    t.method = method
    t.body = body
    t.observeField("done", "onFetched")
    m.tasks.push(t)
    t.control = "run"
end sub

function api(path as String) as String
    return m.base + path + "?home=" + m.homeId
end function

sub say(text as String)
    t = m.top.findNode("toastText")
    t.text = text
    w = textWidth(text, "Inter-Medium", 26) + 64
    t.width = w
    t.height = 64
    bg = m.top.findNode("toastBg")
    bg.width = w
    bg.height = 64
    m.top.findNode("toast").translation = [1840 - w, 58]
    m.top.findNode("toast").visible = text <> ""
    m.top.findNode("toastTimer").control = "stop"
    if text <> "" then m.top.findNode("toastTimer").control = "start"
end sub

sub onToastDone()
    m.top.findNode("toast").visible = false
end sub

' ---------- loading ----------
sub load()
    if m.homeId = "" then return
    fetch("native", api("/api/tv/native"))
    ' the app row asks the TV what is installed, so not every minute: at the start and every 10 minutes
    if m.loads mod 10 = 0 or m.apps.count() = 0 then fetch("apps", api("/api/tv/apps"))
    m.loads = m.loads + 1
end sub

sub onRefresh()
    if m.base <> "" then load()
end sub

sub onFetched(event as Object)
    t = event.getRoSGNode()
    keep = []
    for each x in m.tasks
        if not x.isSameNode(t) then keep.push(x)
    end for
    m.tasks = keep
    j = invalid
    if t.status = 200 and t.response <> "" then j = ParseJson(t.response)
    if type(j) <> "roAssociativeArray" then j = invalid
    if t.tag = "native"
        if j <> invalid and j.title <> invalid
            m.data = j
            setUp(true)
            draw()
        else if t.status = 404
            setUp(false)
            waiting("Welcome", "The house computer does not know this home. Install the channel again with the right home (tools/tv_app.py install --home <id>)")
        else
            setUp(false)
            waiting("Welcome", "Waiting for the house computer")
        end if
    else if t.tag = "apps"
        if j <> invalid and type(j.apps) = "roArray"
            m.apps = j.apps
            if m.focus >= m.apps.count() then m.focus = 0
            drawApps()
        end if
    else if t.tag = "open"
        if j <> invalid and j.ok = true
            say("")
        else
            msg = "That did not open."
            if j <> invalid and isText(j.error) then msg = j.error
            say(msg)
        end if
    end if
end sub

' Up: ask every 60 seconds. Down: hide the screen and ask every 10 seconds, as tv-apps/boot.html does.
sub setUp(up as Boolean)
    m.up = up
    m.top.findNode("screen").visible = up
    m.top.findNode("wait").visible = not up
    if not up
        m.top.findNode("photo").uri = ""
        m.top.findNode("scrim").visible = false
    end if
    r = m.top.findNode("refresh")
    want = 10
    if up then want = 60
    if r.duration <> want
        r.control = "stop"
        r.duration = want
        r.control = "start"
    end if
end sub

sub waiting(big as String, small as String)
    m.top.findNode("waitBig").text = big
    m.top.findNode("waitSmall").text = small
end sub

' ---------- the clock and the date ----------
' The clock shows the house's time: the computer sends its own local time, and the difference from this
' Roku's clock is kept, rounded to a quarter hour, so a Roku set to another time zone still shows the right
' time. Until the computer has answered, the Roku's own time.
sub keepOffset(houseTime as Dynamic)
    if not isText(houseTime) then return
    house = CreateObject("roDateTime")
    house.FromISO8601String(houseTime)
    now = CreateObject("roDateTime")
    diff = house.AsSeconds() - now.AsSeconds()
    m.offset = Int((diff + 450) / 900) * 900
end sub

function houseNow() as Object
    dt = CreateObject("roDateTime")
    if m.offset = invalid
        dt.toLocalTime()
    else
        dt.FromSeconds(dt.AsSeconds() + m.offset)
    end if
    return dt
end function

sub onTick()
    dt = houseNow()
    h = dt.getHours() mod 12
    if h = 0 then h = 12
    mi = dt.getMinutes()
    mm = mi.toStr()
    if mi < 10 then mm = "0" + mm
    text = h.toStr() + ":" + mm
    if text <> m.clockText
        m.clockText = text
        m.top.findNode("clock").text = text
        drawDate()
    end if
end sub

sub drawDate()
    dt = houseNow()
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    line = dt.getWeekday() + " " + dt.getDayOfMonth().toStr() + " " + months[dt.getMonth() - 1]
    if m.data <> invalid and type(m.data.weather) = "roAssociativeArray"
        w = m.data.weather
        line = line + "     " + txt(w.temp) + "° " + txt(w.place)
    end if
    m.top.findNode("date").text = line
end sub

' ---------- the screen ----------
sub draw()
    d = m.data
    keepOffset(d.time)
    photo = m.top.findNode("photo")
    if isText(d.photo)
        if photo.uri <> d.photo then photo.uri = d.photo
    else
        photo.uri = ""
    end if
    m.top.findNode("scrim").visible = true
    m.top.findNode("eyebrow").text = UCase(txt(d.eyebrow))
    m.top.findNode("title").text = txt(d.title)
    m.top.findNode("sub").text = txt(d.sub)
    m.clockText = ""
    onTick()
    drawCards()
end sub

' The QR pictures keep their address while the stay is the same, so the Roku is not asked to fetch them
' every minute; a new phase, mode or quarter hour asks for them again (a new stay brings a new remote).
function qrUri(url as Dynamic) as String
    if not isText(url) then return ""
    v = txt(m.data.phase) + "-" + txt(m.data.mode) + "-" + Int(CreateObject("roDateTime").AsSeconds() / 900).toStr()
    return url + "&v=" + v
end function

function card(x as Integer, w as Integer) as Object
    g = CreateObject("roSGNode", "Group")
    g.translation = [x, 0]
    g.appendChild(poster("pkg:/images/ui/panel.9.png", 0, 0, w, 248))
    return g
end function

sub qrBox(g as Object, uri as String)
    g.appendChild(poster("pkg:/images/ui/qr.9.png", 28, 32, 184, 184))
    p = poster(uri, 36, 40, 168, 168)
    p.loadDisplayMode = "scaleToFit"
    g.appendChild(p)
end sub

sub drawCards()
    d = m.data
    g = m.top.findNode("cards")
    clearGroup(g)
    x = 0
    remoteLabel = txt(d.remote_label)
    if type(d.wifi) = "roAssociativeArray" and isText(d.wifi_qr)
        c = card(x, 560)
        qrBox(c, qrUri(d.wifi_qr))
        c.appendChild(label("1 · Join the Wi-Fi", "Inter-Medium", 28, "0xF7F6F3FF", 240, 34, 292))
        c.appendChild(label("Network", "Inter-Regular", 22, "0xF7F6F399", 240, 88, 292))
        c.appendChild(label(txt(d.wifi.ssid), "Inter-Medium", 30, "0xF7F6F3FF", 240, 114, 292))
        c.appendChild(label("Password", "Inter-Regular", 22, "0xF7F6F399", 240, 160, 292))
        c.appendChild(label(txt(d.wifi.password), "Inter-Medium", 30, "0xF7F6F3FF", 240, 186, 292))
        g.appendChild(c)
        x = x + 580
        remoteLabel = "2 · " + remoteLabel
    end if
    if isText(d.remote_qr)
        c = card(x, 520)
        qrBox(c, qrUri(d.remote_qr))
        c.appendChild(label(remoteLabel, "Inter-Medium", 28, "0xF7F6F3FF", 240, 34, 252))
        hint = label("Scan with your phone's camera", "Inter-Regular", 24, "0xF7F6F3B8", 240, 88, 252)
        hint.wrap = true
        hint.maxLines = 3
        c.appendChild(hint)
        g.appendChild(c)
        x = x + 540
    end if
    if type(d.weather) = "roAssociativeArray"
        wx = d.weather
        c = card(x, 280)
        c.appendChild(label(txt(wx.place), "Inter-Regular", 22, "0xF7F6F399", 28, 32, 224))
        c.appendChild(label(txt(wx.temp) + "°", "Inter-Medium", 72, "0xF7F6F3FF", 28, 62, 224))
        c.appendChild(label(sky(wx.code), "Inter-Regular", 26, "0xF7F6F3DC", 28, 156, 224))
        more = ""
        if wx.hi <> invalid and wx.lo <> invalid then more = txt(wx.hi) + "° / " + txt(wx.lo) + "°"
        if wx.rain <> invalid and wx.rain > 0 then more = more + " · Rain " + txt(wx.rain) + "%"
        c.appendChild(label(more, "Inter-Regular", 22, "0xF7F6F399", 28, 196, 224))
        g.appendChild(c)
        x = x + 300
    end if
    if type(d.access) = "roArray" and d.access.count() > 0 and x <= 1760 - 280
        cw = 1760 - x
        c = card(x, cw)
        c.appendChild(label("Door codes", "Inter-Regular", 22, "0xF7F6F399", 28, 32, cw - 56))
        y = 76
        for i = 0 to d.access.count() - 1
            if i > 2 then exit for
            a = d.access[i]
            c.appendChild(label(txt(a.label), "Inter-Regular", 24, "0xF7F6F3DC", 28, y + 8, cw - 196))
            code = label(txt(a.code), "Inter-Medium", 34, "0xF7F6F3FF", cw - 168, y, 140)
            code.horizAlign = "right"
            c.appendChild(code)
            y = y + 54
        end for
        g.appendChild(c)
    end if
end sub

' The words for Open-Meteo's weather codes (WMO), as the TV page's icons group them.
function sky(code as Dynamic) as String
    if code = invalid then return ""
    c = Int(code)
    if c <= 1 then return "Clear"
    if c = 2 then return "Partly cloudy"
    if c = 3 then return "Cloudy"
    if c = 45 or c = 48 then return "Fog"
    if c >= 95 then return "Storms"
    if (c >= 71 and c <= 77) or c = 85 or c = 86 then return "Snow"
    if c >= 51 and c <= 57 then return "Drizzle"
    if c >= 80 and c <= 82 then return "Showers"
    return "Rain"
end function

' ---------- the app row ----------
sub drawApps()
    g = m.top.findNode("apps")
    clearGroup(g)
    m.pills = []
    x = 0
    for i = 0 to m.apps.count() - 1
        a = m.apps[i]
        name = txt(a.name)
        w = textWidth(name, "Inter-Medium", 26) + 64
        if x + w > 1760 then exit for
        pill = CreateObject("roSGNode", "Group")
        pill.translation = [x, 0]
        bg = poster("pkg:/images/ui/pill.9.png", 0, 0, w, 64)
        pill.appendChild(bg)
        l = label(name, "Inter-Medium", 26, "0xF7F6F3FF", 0, 0, w)
        l.height = 64
        l.horizAlign = "center"
        l.vertAlign = "center"
        pill.appendChild(l)
        g.appendChild(pill)
        m.pills.push({ bg: bg, text: l, app: a })
        x = x + w + 16
    end for
    showFocus()
end sub

sub showFocus()
    for i = 0 to m.pills.count() - 1
        p = m.pills[i]
        if i = m.focus
            p.bg.uri = "pkg:/images/ui/pill-on.9.png"
            p.text.color = "0x16161CFF"
        else
            p.bg.uri = "pkg:/images/ui/pill.9.png"
            p.text.color = "0xF7F6F3FF"
        end if
    end for
end sub

function onKeyEvent(key as String, press as Boolean) as Boolean
    if not press or not m.up or m.pills.count() = 0 then return false
    if key = "left"
        if m.focus > 0 then m.focus = m.focus - 1
        showFocus()
        return true
    else if key = "right"
        if m.focus < m.pills.count() - 1 then m.focus = m.focus + 1
        showFocus()
        return true
    else if key = "OK"
        a = m.pills[m.focus].app
        say("Opening " + txt(a.name) + "...")
        fetch("open", api("/api/tv/app"), "POST", FormatJson({ app: txt(a.id) }))
        return true
    end if
    ' Back and Home are left to the Roku: Back closes the channel, Home opens Roku's home.
    return false
end function
