/// Core data shapes. Mirrors the dicts core/registry.py hands to the web UI.
library;
import 'dart:typed_data';

String humanSize(num n) {
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  var v = n.toDouble();
  var i = 0;
  while (v >= 1024 && i < 4) {
    v /= 1024;
    i++;
  }
  return '${i == 0 ? v.toStringAsFixed(0) : v.toStringAsFixed(1)} ${u[i]}';
}

/// A file queued for work. [path] is a real on-disk path; [bytes] is only set
/// for things we captured in-app (camera shots) before they hit disk.
class FileItem {
  FileItem({
    required this.path,
    required this.name,
    required this.ext,
    required this.size,
    this.bytes,
    this.target = '',
    this.bad = false,
  });

  final String path;
  final String name;
  final String ext;
  final int size;
  final Uint8List? bytes;

  /// Convert view: the chosen output format.
  String target;

  /// No conversion route exists for this type.
  bool bad;

  String get sizeH => humanSize(size);

  static String extOf(String name) {
    final i = name.lastIndexOf('.');
    return i < 0 ? '' : name.substring(i + 1).toLowerCase();
  }
}

enum ParamType { text, number, select, checkbox, range, color, password }

/// One form field. `showIf` hides the field until another field has a value,
/// same as the show_if dict in registry.py. A value may be a String, or a
/// list of strings meaning "any of these".
class ParamDef {
  const ParamDef(
    this.name,
    this.label,
    this.type,
    this.defaultValue, {
    this.options = const [],
    this.min = 0,
    this.max = 100,
    this.step = 1,
    this.showIf,
  });

  final String name;
  final String label;
  final ParamType type;
  final Object? defaultValue;

  /// [value, label] pairs for a select.
  final List<List<String>> options;
  final num min, max, step;
  final Map<String, Object>? showIf;
}

/// Shorthand matching registry.py's P().
ParamDef p(
  String name,
  String label, [
  ParamType type = ParamType.text,
  Object? def,
  List<List<String>> options = const [],
  num min = 0,
  num max = 100,
  num step = 1,
  Map<String, Object>? showIf,
]) =>
    ParamDef(name, label, type, def,
        options: options, min: min, max: max, step: step, showIf: showIf);

typedef ToolRun = Future<List<String>> Function(ToolCall call);

/// A tool as shown on the grid and run from its page.
class ToolDef {
  const ToolDef({
    required this.id,
    required this.cat,
    required this.name,
    required this.icon,
    required this.inputs,
    required this.run,
    this.desc = '',
    this.params = const [],
    this.multi = false,
    this.outExt,
    this.available = true,
    this.unavailableNote = '',
  });

  final String id;
  final String cat;
  final String name;
  final String icon;
  final List<String> inputs;
  final String desc;
  final List<ParamDef> params;

  /// Takes many files and produces one output (merge, join, images->pdf).
  final bool multi;
  final String? outExt;
  final ToolRun run;

  /// False greys the card out instead of pretending it works.
  final bool available;
  final String unavailableNote;
}

/// Everything a tool needs to do its job, plus the hooks to report back.
class ToolCall {
  ToolCall({
    required this.files,
    required this.params,
    required this.outDir,
    required this.progress,
    required this.isCancelled,
    void Function(String)? note,
  }) : note = note ?? ((_) {});

  final List<FileItem> files;
  final Map<String, Object?> params;
  final String outDir;

  /// 0..1, plus a line of status text.
  final void Function(double, String) progress;
  final bool Function() isCancelled;

  /// A line for the jobs window, e.g. "photo.jpg: 4.2 MB → 980 KB (−77%)".
  final void Function(String) note;

  int intP(String k, [int d = 0]) {
    final v = params[k];
    if (v is num) return v.toInt();
    if (v is String && v.trim().isNotEmpty) return int.tryParse(v.trim()) ?? d;
    return d;
  }

  double dblP(String k, [double d = 0]) {
    final v = params[k];
    if (v is num) return v.toDouble();
    if (v is String && v.trim().isNotEmpty) return double.tryParse(v.trim()) ?? d;
    return d;
  }

  String strP(String k, [String d = '']) {
    final v = params[k];
    return v == null ? d : v.toString();
  }

  bool boolP(String k, [bool d = false]) {
    final v = params[k];
    return v is bool ? v : d;
  }
}

enum JobStatus { queued, running, done, error, cancelled }

class Job {
  Job({required this.id, required this.title});

  final int id;
  final String title;
  JobStatus status = JobStatus.queued;
  String message = 'waiting…';
  double progress = 0;
  final List<String> outputs = [];
  final List<String> errors = [];
  final List<String> notes = [];

  bool get active => status == JobStatus.queued || status == JobStatus.running;

  String get statusLabel => switch (status) {
        JobStatus.queued => 'queued',
        JobStatus.running => 'running',
        JobStatus.done => 'done',
        JobStatus.error => 'error',
        JobStatus.cancelled => 'cancelled',
      };
}
