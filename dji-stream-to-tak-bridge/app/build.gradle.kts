import java.util.Properties

plugins {
    id("com.android.application")
}

val localProperties = Properties()
val localPropertiesFile = rootProject.file("local.properties")
if (localPropertiesFile.exists()) {
    localPropertiesFile.inputStream().use(localProperties::load)
}

val djiSdkAppKey = localProperties.getProperty("DJI_SDK_APP_KEY")
    ?: "PASTE_DJI_APP_KEY_HERE"
val djiNativeBootstrap = localProperties.getProperty("DJI_ENABLE_NATIVE_BOOTSTRAP")
    ?.toBooleanStrictOrNull()
    ?: false

android {
    namespace = "org.skysentinel.djitakbridge"
    compileSdk = 36

    defaultConfig {
        applicationId = "org.skysentinel.djitakbridge"
        minSdk = 23
        // DJI Mobile SDK V4 uses a legacy protected runtime loader. Target 33
        // avoids Android 14+ dynamic-code-loading restrictions for this hackathon build.
        targetSdk = 33
        versionCode = 1
        versionName = "0.1.0"
        multiDexEnabled = true

        ndk {
            abiFilters += listOf("armeabi-v7a", "arm64-v8a")
        }

        manifestPlaceholders["DJI_SDK_APP_KEY"] = djiSdkAppKey
        manifestPlaceholders["DJI_ENABLE_NATIVE_BOOTSTRAP"] = djiNativeBootstrap.toString()
    }

    useLibrary("org.apache.http.legacy")

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        jniLibs {
            useLegacyPackaging = true
            keepDebugSymbols += listOf(
                "**/libdjivideo.so",
                "**/libSDKRelativeJNI.so",
                "**/libFlyForbid.so",
                "**/libduml_vision_bokeh.so",
                "**/libyuv2.so",
                "**/libGroudStation.so",
                "**/libFRCorkscrew.so",
                "**/libUpgradeVerify.so",
                "**/libFR.so",
                "**/libDJIFlySafeCore.so",
                "**/libdjifs_jni.so",
                "**/libsfjni.so",
                "**/libDJICommonJNI.so",
                "**/libDJICSDKCommon.so",
                "**/libDJIUpgradeCore.so",
                "**/libDJIUpgradeJNI.so",
                "**/libDJIWaypointV2Core.so",
                "**/libAMapSDK_MAP_v6_9_2.so",
                "**/libDJIMOP.so",
                "**/libDJISDKLOGJNI.so",
            )
        }
        resources {
            excludes += setOf(
                "META-INF/rxjava.properties",
                "META-INF/DEPENDENCIES",
                "META-INF/LICENSE",
                "META-INF/LICENSE.txt",
                "META-INF/NOTICE",
                "META-INF/NOTICE.txt",
                "assets/location_map_gps_locked.png",
                "assets/location_map_gps_3d.png",
            )
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.appcompat:appcompat:1.7.1")
    implementation("androidx.constraintlayout:constraintlayout:2.2.1")
    implementation("org.apache.httpcomponents:httpclient:4.5.14")

    implementation("com.dji:dji-sdk:4.18") {
        exclude(module = "library-anti-distortion")
    }
    compileOnly("com.dji:dji-sdk-provided:4.18")
}
