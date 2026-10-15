/// Output folder, safe file naming, scratch space. Mirrors core/util.py.
library;
import 'dart:io';

import 'package:path/path.dart' as pp;
import 'package:path_provider/path_provider.dart';
import 'package:permission_handler/permission_handler.dart';

class Fs {
  static late Directory _docs;
  static late Directory _cache;
  static String outDir = '';

  /// Pick the best output folder we can actually write to.
  ///
  /// Shared Downloads is the nicest place for a user to find their files, but
  /// since Android 11 a direct write there fails unless the app holds
  /// MANAGE_EXTERNAL_STORAGE. Checking `existsSync()` is not enough — the
  /// directory is visible but not writable — so each candidate is probed with a
  /// real file before being accepted. Otherwise every single job would fail at
  /// the point it tries to save.
  static Future<void> init() async {
    // If path_provider fails we must still end up with usable directories:
    // these are `late`, and leaving them unset turns every later file
    // operation into a LateInitializationError instead of a clear message.
    try {
      _docs = await getApplicationDocumentsDirectory();
    } catch (_) {
      _docs = Directory.systemTemp.createTempSync('ec_docs');
    }
    try {
      _cache = await getTemporaryDirectory();
    } catch (_) {
      _cache = Directory.systemTemp.createTempSync('ec_cache');
    }

    final candidates = <String>[
      '/storage/emulated/0/Download/Everything Converter',
      '/storage/emulated/0/Documents/Everything Converter',
    ];
    try {
      final ext = await getExternalStorageDirectory();
      // Always writable, no permission needed, and visible to file managers
      // under Android/data/<package>/files.
      if (ext != null) candidates.add(pp.join(ext.path, 'Everything Converter'));
    } catch (_) {
      // Not available on this device; the app-private folder still works.
    }
    candidates.add(pp.join(_docs.path, 'Everything Converter'));

    for (final path in candidates) {
      if (await isWritable(path)) {
        outDir = path;
        return;
      }
    }
    // Last resort: documents itself, which is always ours.
    outDir = _docs.path;
  }

  /// Create [path] and prove we can write a file into it.
  static Future<bool> isWritable(String path) async {
    try {
      final dir = Directory(path);
      if (!dir.existsSync()) dir.createSync(recursive: true);
      final probe = File(pp.join(path, '.ec_write_test'));
      await probe.writeAsString('ok', flush: true);
      await probe.delete();
      return true;
    } catch (_) {
      return false;
    }
  }

  static Directory get cacheDir => _cache;
  static Directory get docsDir => _docs;

  /// Point the engine at throwaway directories. Used by [AppState.initForTest]
  /// so widget tests can drive the UI without touching real storage.
  static void initWith({required Directory root}) {
    _docs = Directory(pp.join(root.path, 'docs'))..createSync(recursive: true);
    _cache = Directory(pp.join(root.path, 'cache'))..createSync(recursive: true);
    outDir = _docs.path;
  }

  /// Scratch space, wiped after each job like %LOCALAPPDATA%\EverythingConverter.
  static Directory scratch() {
    final d = Directory(pp.join(
        _cache.path, 'scratch', DateTime.now().microsecondsSinceEpoch.toString()));
    d.createSync(recursive: true);
    return d;
  }

  static Future<void> wipeScratch() async {
    final d = Directory(pp.join(_cache.path, 'scratch'));
    if (d.existsSync()) {
      try {
        await d.delete(recursive: true);
      } catch (_) {
        // Something still has a handle on it; it'll go on the next pass.
      }
    }
  }

  static Future<int> cacheSize() async {
    var total = 0;
    for (final dir in [Directory(pp.join(_cache.path, 'scratch')), _cache]) {
      if (!dir.existsSync()) continue;
      await for (final e in dir.list(recursive: true, followLinks: false)) {
        if (e is File) {
          try {
            total += await e.length();
          } catch (_) {
            // Vanished mid-scan.
          }
        }
      }
      break;
    }
    return total;
  }

  /// Never overwrite: foo.pdf, foo (2).pdf, foo (3).pdf …
  static File uniq(String dir, String name) {
    Directory(dir).createSync(recursive: true);
    final stem = pp.basenameWithoutExtension(name);
    final ext = pp.extension(name);
    var f = File(pp.join(dir, '$stem$ext'));
    var n = 2;
    while (f.existsSync()) {
      f = File(pp.join(dir, '$stem ($n)$ext'));
      n++;
    }
    return f;
  }

  static String safeStem(String name) {
    final stem = pp.basenameWithoutExtension(name);
    return stem.replaceAll(RegExp(r'[\/:*?"<>|]'), '_');
  }

  /// Android 13+ splits media permission; older needs plain storage.
  static Future<bool> ensureStorage() async {
    if (!Platform.isAndroid) return true;
    if (await Permission.photos.request().isGranted) return true;
    if (await Permission.storage.request().isGranted) return true;
    return false;
  }

  /// Common places worth scanning for clutter. Only the ones that exist are
  /// offered.
  static List<String> commonFolders() {
    const roots = [
      '/storage/emulated/0/Download',
      '/storage/emulated/0/DCIM',
      '/storage/emulated/0/Pictures',
      '/storage/emulated/0/Documents',
      '/storage/emulated/0/Movies',
      '/storage/emulated/0/Music',
      '/storage/emulated/0/WhatsApp',
    ];
    return [
      for (final r in roots)
        if (Directory(r).existsSync()) r,
    ];
  }

  /// "All files access" (MANAGE_EXTERNAL_STORAGE).
  ///
  /// Android's folder picker refuses to hand out Download or the root of
  /// internal storage ("To protect your privacy, choose another folder"), so
  /// scanning those for duplicates is only possible with this permission.
  static Future<bool> hasAllFilesAccess() async {
    if (!Platform.isAndroid) return true;
    return Permission.manageExternalStorage.isGranted;
  }

  /// Sends the user to the system settings screen for the permission.
  static Future<bool> requestAllFilesAccess() async {
    if (!Platform.isAndroid) return true;
    final status = await Permission.manageExternalStorage.request();
    return status.isGranted;
  }

  static Future<bool> ensureCamera() async =>
      Platform.isAndroid ? (await Permission.camera.request()).isGranted : true;
}
