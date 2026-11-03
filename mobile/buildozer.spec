[app]
title = КорпМессенджер
package.name = corpmessenger
package.domain = org.corp
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 1.0
requirements = python3,kivy,urllib3,json
orientation = portrait
fullscreen = 0
android.api = 31
android.minapi = 21
android.permissions = INTERNET,READ_EXTERNAL_STORAGE
android.arch = armeabi-v7a
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 0
