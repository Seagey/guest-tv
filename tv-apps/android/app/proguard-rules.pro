# The page calls these through window.TVOS.
-keepclassmembers class app.guesttv.home.MainActivity$Native {
    @android.webkit.JavascriptInterface <methods>;
}
