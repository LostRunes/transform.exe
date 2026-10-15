/// Background jobs with live progress and cancel. Ported from core/jobs.py.
/// Work runs one job at a time so a big conversion can't starve the UI.
library;
import 'dart:async';
import 'dart:collection';

import 'package:flutter/foundation.dart';

import 'fs.dart';
import 'models.dart';

typedef JobBody = Future<List<String>> Function(ToolCall call);

class JobQueue extends ChangeNotifier {
  JobQueue._();
  static final JobQueue instance = JobQueue._();

  final List<Job> _jobs = [];
  final _cancelled = <int>{};
  final Queue<_Pending> _pending = Queue();
  var _busy = false;
  var _nextId = 1;

  /// Newest first, the order the jobs window shows them in.
  List<Job> get jobs => List.unmodifiable(_jobs.reversed);
  int get activeCount => _jobs.where((j) => j.active).length;

  Job submit({
    required String title,
    required List<FileItem> files,
    required Map<String, Object?> params,
    required String outDir,
    required JobBody body,
  }) {
    final job = Job(id: _nextId++, title: title);
    _jobs.add(job);
    _pending.add(_Pending(job, files, params, outDir, body));
    notifyListeners();
    unawaited(_drain());
    return job;
  }

  void cancel(int id) {
    _cancelled.add(id);
    final job = _jobs.firstWhere((j) => j.id == id, orElse: () => Job(id: -1, title: ''));
    if (job.id != -1 && job.status == JobStatus.queued) {
      job.status = JobStatus.cancelled;
      job.message = 'cancelled before it started';
      notifyListeners();
    }
  }

  void clearFinished() {
    _jobs.removeWhere((j) => !j.active);
    notifyListeners();
  }

  Future<void> _drain() async {
    if (_busy) return;
    _busy = true;
    try {
      while (_pending.isNotEmpty) {
        final p = _pending.removeFirst();
        final job = p.job;
        if (_cancelled.contains(job.id)) {
          job.status = JobStatus.cancelled;
          notifyListeners();
          continue;
        }
        job.status = JobStatus.running;
        job.message = 'starting…';
        notifyListeners();

        // Throttle repaints: progress can fire hundreds of times a second.
        var lastPaint = DateTime.fromMillisecondsSinceEpoch(0);
        void report(double value, String message) {
          job.progress = value.clamp(0, 1);
          job.message = message;
          final now = DateTime.now();
          if (now.difference(lastPaint).inMilliseconds > 120) {
            lastPaint = now;
            notifyListeners();
          }
        }

        try {
          final outputs = await p.body(ToolCall(
            files: p.files,
            params: p.params,
            outDir: p.outDir,
            progress: report,
            isCancelled: () => _cancelled.contains(job.id),
            note: (msg) {
              job.notes.add(msg);
              notifyListeners();
            },
          ));
          if (_cancelled.contains(job.id)) {
            job.status = JobStatus.cancelled;
            job.message = 'cancelled';
          } else {
            job.outputs.addAll(outputs);
            job.progress = 1;
            job.status = JobStatus.done;
            job.message = outputs.length == 1
                ? '1 file written'
                : '${outputs.length} files written';
          }
        } catch (e) {
          job.status = JobStatus.error;
          job.message = _clean(e);
          job.errors.add(_clean(e));
        }
        notifyListeners();
        await Fs.wipeScratch();
      }
    } finally {
      _busy = false;
    }
  }

  static String _clean(Object e) {
    var s = e.toString();
    if (s.startsWith('Exception: ')) s = s.substring(11);
    return s;
  }
}

class _Pending {
  _Pending(this.job, this.files, this.params, this.outDir, this.body);
  final Job job;
  final List<FileItem> files;
  final Map<String, Object?> params;
  final String outDir;
  final JobBody body;
}
