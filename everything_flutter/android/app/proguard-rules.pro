# Syncfusion PDF uses reflection in places; keep its classes intact.
-keep class com.syncfusion.** { *; }
-dontwarn com.syncfusion.**

# PDFium bindings used by pdfrx.
-keep class org.pdfrx.** { *; }
-dontwarn org.pdfrx.**

# Flutter plugin registrants.
-keep class io.flutter.** { *; }
-dontwarn io.flutter.**
