/// Video & audio compression on Android, with no FFmpeg: the platform's own
/// hardware encoders driven through Media3 Transformer (see MediaCompressor.kt).
/// Dart works out the bitrate for a size budget; Kotlin does the encoding.
library;
import 'dart:async';
import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/services.dart';

import '../core/fs.dart';
import '../core/models.dart';
import '../core/shrink.dart';

class MediaEngine {
  static const _channel = MethodChannel('everything/media');

  static const videoIn = ['mp4', 'mov', 'm4v', '3gp', 'webm', 'mkv', 'ts'];
  static const audioIn = ['mp3', 'm4a', 'aac', 'wav', 'flac', 'ogg', 'opus', 'amr', '3ga'];

  static final _progress = <int, void Function(double)>{};
  static var _nextId = 1;
  static var _wired = false;

  static void _wire() {
    if (_wired) return;
    _wired = true;
    _channel.setMethodCallHandler((call) async {
      if (call.method == 'progress') {
        final args = call.arguments as Map;
        _progress[args['id'] as int]?.call((args['p'] as num).toDouble());
      }
    });
  }

  /// Duration (ms), size, frame rate and whether there is audio/video.
  static Future<Map<String, Object?>> probe(String path) async {
    final r = await _channel.invokeMapMethod<String, Object?>('probe', {'path': path});
    return r ?? {};
  }

  /// One encode. Polls cancel while it runs, so the Cancel button works.
  static Future<void> _transcode(Map<String, Object?> args, ToolCall c,
      void Function(double) onProgress) async {
    _wire();
    final id = _nextId++;
    _progress[id] = onProgress;
    final watch = Timer.periodic(const Duration(milliseconds: 300), (_) {
      if (c.isCancelled()) _channel.invokeMethod('cancel', {'id': id});
    });
    try {
      await _channel.invokeMethod('transcode', {...args, 'id': id});
    } on PlatformException catch (e) {
      if (c.isCancelled()) return;
      throw Exception(e.message ?? 'The phone\'s encoder refused this file');
    } finally {
      watch.cancel();
      _progress.remove(id);
    }
  }

  // ---------------------------------------------------------------- video

  /// Short side of the picture, best first.
  static const _shortSides = [2160, 1440, 1080, 720, 540, 480, 360, 240];

  /// Largest short side (never upscaling) where the bitrate still gives each
  /// pixel enough bits to look like video rather than mush.
  static int? _autoShortSide(int w, int h, double fps, int videoBps, bool h265) {
    if (w <= 0 || h <= 0) return null;
    final short = math.min(w, h), long = math.max(w, h);
    final need = h265 ? 0.035 : 0.05;
    for (final side in _shortSides) {
      if (side > short) continue;
      final pixels = side * side * long / short;
      if (videoBps / (fps * pixels) >= need) return side < short ? side : null;
    }
    return short > _shortSides.last ? _shortSides.last : null;
  }

  static Future<List<String>> toolCompressVideo(ToolCall c) async {
    final outs = <String>[];
    for (var i = 0; i < c.files.length; i++) {
      if (c.isCancelled()) break;
      final f = c.files[i];
      final share = 1 / c.files.length;
      c.progress(i * share, 'Reading ${f.name}');
      final size = await File(f.path).length();
      final limit = Shrink.budget(size, c);
      final copied = await Shrink.alreadyFits(f, limit, c);
      if (copied != null) {
        outs.add(copied);
        continue;
      }
      final info = await probe(f.path);
      final durS = ((info['durationMs'] as num?) ?? 0) / 1000;
      if (durS <= 0) throw Exception("Couldn't read how long ${f.name} is");
      final w = (info['width'] as num?)?.toInt() ?? 0;
      final h = (info['height'] as num?)?.toInt() ?? 0;
      final fps = ((info['fps'] as num?) ?? 30).toDouble().clamp(1, 240).toDouble();
      final hasAudio = info['hasAudio'] == true;
      final h265 = c.strP('codec', 'h264') == 'h265';

      int videoBps, audioBps;
      int? shortSide = c.intP('max_height', 0) > 0 ? c.intP('max_height', 0) : null;
      if (limit == null) {
        // Quality mode: a bitrate per pixel, from the quality slider.
        final q = c.intP('quality', 60).clamp(10, 100);
        final side = shortSide ?? math.min(w, h);
        final pixels = side * side * math.max(w, h) / math.max(1, math.min(w, h));
        videoBps = math.max(150000, (pixels * fps * (0.02 + 0.13 * q / 100)).round());
        audioBps = 128000;
      } else {
        final totalBps = limit * 8 / durS * 0.96; // ~4% for the MP4 container
        audioBps = hasAudio ? (totalBps * 0.12).clamp(24000, 128000).round() : 0;
        videoBps = (totalBps - audioBps).round();
        if (videoBps < 30000) {
          throw Exception('${humanSize(limit)} is too small for a ${durS.round()}s video: the '
              'picture would get under 30 kbps. Try a bigger target.');
        }
        if (shortSide == null && c.boolP('auto_res', true)) {
          shortSide = _autoShortSide(w, h, fps, videoBps, h265);
          if (shortSide != null) {
            c.note('${f.name}: lowered to ${shortSide}p so '
                '${(videoBps / 1000).round()} kbps still looks clean');
          }
        }
      }

      final out = Fs.uniq(c.outDir, '${Fs.safeStem(f.name)} compressed.mp4');
      for (var attempt = 0; attempt < 3; attempt++) {
        if (c.isCancelled()) break;
        await _transcode({
          'input': f.path,
          'output': out.path,
          'videoBitrate': videoBps,
          'audioBitrate': hasAudio ? audioBps : 0,
          'shortSide': shortSide ?? 0,
          'h265': h265,
          'mono': audioBps < 48000,
        }, c, (p) => c.progress(
            i * share + share * p, 'Encoding ${f.name} ${(p * 100).round()}%'
            '${attempt > 0 ? ' (try ${attempt + 1})' : ''}'));
        // Phone encoders treat the bitrate as a hint; check, and aim lower on overshoot.
        final got = await out.length();
        if (limit == null || got <= limit || videoBps <= 30000) break;
        videoBps = math.max(30000, (videoBps * limit / got * 0.95).round());
      }
      if (c.isCancelled()) break;
      Shrink.report(c, f.name, size, await out.length(), limit);
      outs.add(out.path);
    }
    return outs;
  }

  // ---------------------------------------------------------------- audio

  static Future<List<String>> toolCompressAudio(ToolCall c) async {
    final outs = <String>[];
    for (var i = 0; i < c.files.length; i++) {
      if (c.isCancelled()) break;
      final f = c.files[i];
      final share = 1 / c.files.length;
      final size = await File(f.path).length();
      final limit = Shrink.budget(size, c);
      final copied = await Shrink.alreadyFits(f, limit, c);
      if (copied != null) {
        outs.add(copied);
        continue;
      }
      final info = await probe(f.path);
      final durS = ((info['durationMs'] as num?) ?? 0) / 1000;
      if (durS <= 0) throw Exception("Couldn't read how long ${f.name} is");
      var bps = limit == null
          ? c.intP('bitrate', 96) * 1000
          : (limit * 8 / durS * 0.96).round();
      if (bps < 8000) {
        throw Exception('${humanSize(limit ?? 0)} is too small for ${durS.round()}s of '
            'audio (it would need under 8 kbps)');
      }
      final channels = c.strP('channels', 'auto');
      final rate = c.intP('sample_rate', 0);
      if (f.ext != 'm4a') {
        c.note('${f.name}: saved as .m4a (AAC), the format Android can encode to any size');
      }
      final out = Fs.uniq(c.outDir, '${Fs.safeStem(f.name)} compressed.m4a');
      for (var attempt = 0; attempt < 3; attempt++) {
        if (c.isCancelled()) break;
        await _transcode({
          'input': f.path,
          'output': out.path,
          'videoBitrate': 0,
          'audioBitrate': bps,
          'shortSide': 0,
          'h265': false,
          'mono': channels == 'mono' || (channels == 'auto' && bps < 40000),
          'sampleRate': rate > 0 ? rate : (bps < 24000 ? 22050 : 0),
        }, c, (p) => c.progress(
            i * share + share * p, 'Encoding ${f.name} ${(p * 100).round()}%'));
        final got = await out.length();
        if (limit == null || got <= limit || bps <= 8000) break;
        bps = math.max(8000, (bps * limit / got * 0.95).round());
      }
      if (c.isCancelled()) break;
      Shrink.report(c, f.name, size, await out.length(), limit);
      outs.add(out.path);
    }
    return outs;
  }
}
