' guest-tv for Roku: the welcome screen as a channel. Everything is drawn in components/WelcomeScene.brs.
'
' The computer launches this channel (it is "dev", the sideloaded one) with launch/dev?home=<id>. The
' home given there wins over the one baked into pkg:/config.json. When the channel is already open, the
' Roku hands a new launch to it as an input event (supports_input_launch in the manifest).
sub Main(args as Dynamic)
    screen = CreateObject("roSGScreen")
    port = CreateObject("roMessagePort")
    screen.setMessagePort(port)
    scene = screen.CreateScene("WelcomeScene")
    screen.show()
    useHome(scene, args)
    scene.setFocus(true)
    input = CreateObject("roInput")
    input.setMessagePort(port)
    while true
        msg = wait(0, port)
        if type(msg) = "roSGScreenEvent"
            if msg.isScreenClosed() then return
        else if type(msg) = "roInputEvent"
            if msg.isInput() then useHome(scene, msg.getInfo())
        end if
    end while
end sub

' Only a plain home id goes through: lower case letters, numbers and dashes, as guest-tv names homes.
sub useHome(scene as Object, args as Dynamic)
    if type(args) <> "roAssociativeArray" then return
    home = args.home
    if type(home) <> "roString" and type(home) <> "String" then return
    ok = CreateObject("roRegex", "^[a-z0-9-]{1,40}$", "")
    if ok.isMatch(home) then scene.home = home
end sub
