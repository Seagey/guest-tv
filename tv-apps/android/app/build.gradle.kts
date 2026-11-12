plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "app.guesttv.home"
    compileSdk = 34
    defaultConfig {
        // Its own id, so it can sit beside couch-tv's app (app.couchtv.launcher) on the same TV.
        applicationId = "app.guesttv.home"
        minSdk = 23          // the same as couch-tv's app: Android 6 and newer, so Fire OS 6 (Android 7.1) too
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
        // The port guest-tv answers on: 5410, as server.py. A test build can use another
        // (./gradlew assembleRelease -Pport=5499), so it never finds a real guest-tv.
        val port = (project.findProperty("port") as String? ?: "5410").trim().toIntOrNull()?.takeIf { it in 1..65535 } ?: 5410
        buildConfigField("int", "PORT", port.toString())
    }
    buildFeatures { buildConfig = true }
    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            // The same key as couch-tv's releases: Android's debug key in ~/.android/debug.keystore.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    lint {
        checkReleaseBuilds = false
        abortOnError = false
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}
