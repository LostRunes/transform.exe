/// App-wide state: the current view, the file lists, the output folder and the
/// theme. Stands in for the `S` object and localStorage shim in web/app.js.
library;

import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fs.dart';
import 'models.dart';
import 'registry.dart';

/// The nav entries, in sidebar order: id, icon, label, window title, buddy line.
const views = <List<String>>[
  ['convert', '⇄', 'Convert', 'convert.exe', "drop anything on me ✦ I'll turn it into anything"],
  ['tools:Compress', '⇲', 'Compress', 'compress.exe', "too big? tell me how small and I'll squish it ✧"],
  ['scan', '📷', 'Scan → PDF', 'scanner.exe', 'snap some pages, get a PDF ✧'],
  ['tools:PDF', '▤', 'PDF tools', 'pdf_tools.exe', 'merge, split, squish… pick a tool!'],
  ['editor', '✎', 'PDF editor', 'paint_a_pdf.exe', "let's scribble on a PDF ✎"],
  ['tools:Image', '▧', 'Image tools', 'image_tools.exe', "photos too big? I'll make them tiny~"],
  ['tools:Video & Audio', '▶', 'Video & audio', 'video_audio.exe', 'squish videos and songs ♪'],
  ['tools:Data', '▦', 'Spreadsheets', 'spreadsheets.exe', 'rows and columns, my favourite'],
  ['cleanup', '✦', 'Clean up', 'clean_up.exe', "let's tidy your phone ✧"],
];

const quips = [
  'hehe that tickles',
  'boop!',
  '✦ sparkle mode ✦',
  "I don't need the internet, only you",
  'no file too big!',
  '*floats happily*',
  'converting is my cardio',
];

class AppState extends ChangeNotifier {
  AppState._();
  static final AppState instance = AppState._();

  late SharedPreferences _prefs;

  String view = 'convert';
  ToolDef? currentTool;
  bool dark = false;
  bool jobsOpen = false;
  String outDir = '';

  /// Convert view queue.
  final List<FileItem> convertFiles = [];

  /// toolId -> its queued files.
  final Map<String, List<FileItem>> toolFiles = {};

  /// Pages waiting in the scanner.
  final List<FileItem> scanPages = [];

  String buddyLine = views.first[4];

  Future<void> init() async {
    _prefs = await SharedPreferences.getInstance();
    await Fs.init();
    buildGraph();
    outDir = _prefs.getString('outDir') ?? Fs.outDir;
    dark = _prefs.getBool('dark') ?? false;
    view = _prefs.getString('view') ?? 'convert';
    if (views.every((v) => v[0] != view)) view = 'convert';
    buddyLine = lineFor(view);
    notifyListeners();
  }

  /// Same wiring as [init] but without touching the real filesystem, so widget
  /// tests can drive the shell.
  @visibleForTesting
  Future<void> initForTest({String? outDir}) async {
    _prefs = await SharedPreferences.getInstance();
    Fs.initWith(root: Directory.systemTemp.createTempSync('ec_test'));
    buildGraph();
    this.outDir = outDir ?? Fs.outDir;
    dark = false;
    view = 'convert';
    currentTool = null;
    jobsOpen = false;
    convertFiles.clear();
    toolFiles.clear();
    scanPages.clear();
    buddyLine = lineFor(view);
  }

  /// Re-pick the default output folder. Granting all-files access can make a
  /// better location (shared Downloads) writable for the first time.
  Future<void> refreshDefaultOutDir() async {
    if (_prefs.getString('outDir') != null) return;
    await Fs.init();
    outDir = Fs.outDir;
    notifyListeners();
  }

  /// Just the folder name, for the cramped phone top bar.
  String get outDirLabel {
    final parts = outDir.split(RegExp(r'[\\/]'))..removeWhere((p) => p.isEmpty);
    return parts.isEmpty ? outDir : parts.last;
  }

  String lineFor(String v) =>
      views.firstWhere((e) => e[0] == v, orElse: () => views.first)[4];

  String titleFor(String v) =>
      views.firstWhere((e) => e[0] == v, orElse: () => views.first)[3];

  void route(String v) {
    view = v;
    currentTool = null;
    buddyLine = lineFor(v);
    _prefs.setString('view', v);
    notifyListeners();
  }

  void openTool(ToolDef? t) {
    currentTool = t;
    notifyListeners();
  }

  void toggleTheme() {
    dark = !dark;
    _prefs.setBool('dark', dark);
    say(dark ? 'good night~ ☾ the stars are out' : 'good morning! ☀');
  }

  void setOutDir(String path) {
    outDir = path;
    _prefs.setString('outDir', path);
    notifyListeners();
  }

  void setJobsOpen(bool open) {
    jobsOpen = open;
    notifyListeners();
  }

  /// Remember the last target picked for each input type.
  String? lastTarget(String ext) => _prefs.getString('lastTarget.$ext');
  void rememberTarget(String ext, String target) =>
      _prefs.setString('lastTarget.$ext', target);

  String? getString(String key) => _prefs.getString(key);
  void putString(String key, String value) => _prefs.setString(key, value);

  void say(String text) {
    buddyLine = text;
    notifyListeners();
  }

  void resetSay() {
    buddyLine = lineFor(view);
    notifyListeners();
  }

  /// Add files to whichever list the current view is showing.
  void addFiles(List<FileItem> files) {
    if (view == 'convert') {
      for (final f in files) {
        final targets = targetsFor(f.ext);
        final last = lastTarget(f.ext);
        f.target = targets.contains(last)
            ? last!
            : targets.contains(defaultTarget[norm(f.ext)])
                ? defaultTarget[norm(f.ext)]!
                : (targets.isEmpty ? '' : targets.first);
        f.bad = targets.isEmpty;
        convertFiles.add(f);
      }
    } else if (view == 'scan') {
      scanPages.addAll(files);
    } else if (currentTool != null) {
      final t = currentTool!;
      toolFiles.putIfAbsent(t.id, () => []).addAll(
          files.where((f) => t.inputs.contains(f.ext) || t.inputs.contains(norm(f.ext))));
    }
    notifyListeners();
  }

  void touch() => notifyListeners();
}
