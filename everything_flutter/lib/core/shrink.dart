/// Size-targeted compression shared by every compress tool. Port of core/shrink.py.
///
/// The "How small?" controls become a byte budget here (shrink by a percentage,
/// or hit a typed-in size). Each engine then searches its own quality knob for
/// the best result that fits. This file also compresses Office files (by
/// recompressing the pictures inside them), zips anything else, and routes
/// "Compress anything".
library;
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:archive/archive.dart';
import 'package:image/image.dart' as im;

import '../engines/img.dart';
import '../engines/media.dart';
import '../engines/pdfeng.dart';
import 'fs.dart';
import 'models.dart';

const _units = {'KB': 1024, 'MB': 1024 * 1024, 'GB': 1024 * 1024 * 1024};

/// The shared "How small?" fields: a % slider, or a typed-in target size.
/// [qualityLabel] adds a third choice that falls back to the tool's own settings.
List<ParamDef> sizeParams({String? qualityLabel, String defaultMode = 'percent'}) => [
      ParamDef('size_mode', 'How small?', ParamType.select, defaultMode, options: [
        ['percent', 'Shrink by a percentage'],
        ['target', 'Hit a target size'],
        if (qualityLabel != null) ['quality', qualityLabel],
      ]),
      const ParamDef('reduce_pct', 'Make it smaller by (%)', ParamType.range, 50,
          min: 5, max: 95, step: 5, showIf: {'size_mode': 'percent'}),
      const ParamDef('target_size', 'Target size (at most)', ParamType.number, 1,
          showIf: {'size_mode': 'target'}),
      const ParamDef('target_unit', 'Unit', ParamType.select, 'MB',
          options: [
            ['KB', 'KB'],
            ['MB', 'MB'],
            ['GB', 'GB'],
          ],
          showIf: {'size_mode': 'target'}),
    ];

const qualityMode = {'size_mode': 'quality'};
const sizedMode = {
  'size_mode': ['percent', 'target']
};

class Shrink {
  /// Byte budget from the size controls, or null when the tool's own quality
  /// settings apply.
  static int? budget(int srcSize, ToolCall c) {
    final mode = c.strP('size_mode', 'quality');
    if (mode == 'percent') {
      final pct = c.dblP('reduce_pct', 50).clamp(1, 99);
      return math.max(1, (srcSize * (100 - pct) / 100).floor());
    }
    if (mode == 'target') {
      final n = c.dblP('target_size', 0);
      if (n <= 0) throw Exception('Enter a target size bigger than 0');
      return math.max(1, (n * (_units[c.strP('target_unit', 'MB')] ?? _units['MB']!)).floor());
    }
    return null;
  }

  /// Binary-search [lo]..[hi] (bigger = better and bigger) for the best output
  /// under [limit]. Returns (fitting bytes or null, smallest bytes seen).
  static Future<(Uint8List?, Uint8List)> search(
      Future<Uint8List> Function(int) encode, int lo, int hi, int limit) async {
    Uint8List? hit;
    Uint8List? smallest;
    while (lo <= hi) {
      final mid = (lo + hi) ~/ 2;
      final data = await encode(mid);
      if (smallest == null || data.length < smallest.length) smallest = data;
      if (data.length <= limit) {
        hit = data;
        lo = mid + 1;
      } else {
        hi = mid - 1;
      }
    }
    return (hit, smallest!);
  }

  /// Tell the user what happened, especially when the budget couldn't be met.
  static void report(ToolCall c, String name, int before, int after, [int? limit]) {
    var pct = before == 0 ? 0.0 : (1 - after / before) * 100;
    if (after > 0) pct = math.min(pct, 99); // "−100%" reads as "nothing left"
    var msg = '$name: ${humanSize(before)} → ${humanSize(after)} '
        '(${pct >= 0 ? '−' : '+'}${pct.abs().toStringAsFixed(0)}%)';
    if (limit != null && after > limit) {
      msg += " — couldn't get under ${humanSize(limit)}; this is as small as it goes";
    }
    c.note(msg);
  }

  /// A file already under the target is copied as-is instead of being
  /// re-encoded bigger. Returns the copy, or null if work is needed.
  static Future<String?> alreadyFits(FileItem f, int? limit, ToolCall c) async {
    final size = await File(f.path).length();
    if (limit == null || size > limit) return null;
    final out = Fs.uniq(c.outDir, '${Fs.safeStem(f.name)} compressed.${f.ext}');
    await File(f.path).copy(out.path);
    c.note('${f.name}: already ${humanSize(size)}, under the ${humanSize(limit)} '
        'target — copied unchanged');
    return out.path;
  }

  // -------------------------------------------------------------- Office documents

  static const office = [
    'docx', 'docm', 'dotx', 'xlsx', 'xlsm', 'pptx', 'pptm', 'ppsx', 'potx',
    'odt', 'ods', 'odp', 'odg', 'epub',
  ];
  static const _pics = ['jpg', 'jpeg', 'png', 'bmp'];

  /// (pixel scale, JPEG quality), gentlest first. Pictures keep their names and
  /// formats so the document's references stay valid; their on-page size comes
  /// from the layout, so fewer pixels means less detail, not a smaller picture.
  static const _rungs = [
    (1.0, 85), (1.0, 75), (0.85, 68), (0.75, 60), (0.6, 52), (0.5, 45),
    (0.4, 38), (0.3, 30), (0.22, 25),
  ];

  static Uint8List _shrinkPicture(Uint8List data, String ext, (double, int) rung) {
    final (scale, q) = rung;
    final image = im.decodeImage(data);
    if (image == null) return data;
    var img = image;
    if (scale < 1) {
      img = im.copyResize(img,
          width: math.max(1, (img.width * scale).round()),
          height: math.max(1, (img.height * scale).round()),
          interpolation: im.Interpolation.average);
    }
    final Uint8List out = switch (ext) {
      'jpg' || 'jpeg' => im.encodeJpg(img, quality: q),
      'png' => im.encodePng(q < 70 ? im.quantize(img, numberOfColors: 256) : img, level: 9),
      _ => im.encodeBmp(img),
    };
    return out.length < data.length ? out : data;
  }

  static Uint8List _repack(Archive src, (double, int)? rung) {
    final out = Archive();
    for (final f in src.files) {
      if (!f.isFile) continue;
      var data = Uint8List.fromList(f.content as List<int>);
      final dot = f.name.lastIndexOf('.');
      final ext = dot < 0 ? '' : f.name.substring(dot + 1).toLowerCase();
      if (rung != null && _pics.contains(ext)) data = _shrinkPicture(data, ext, rung);
      final entry = ArchiveFile(f.name, data.length, data);
      // ODF/EPUB: "mimetype" must stay first and uncompressed.
      entry.compress = f.name != 'mimetype';
      out.addFile(entry);
    }
    return Uint8List.fromList(ZipEncoder().encode(out, level: Deflate.BEST_COMPRESSION)!);
  }

  static Future<List<String>> toolCompressOffice(ToolCall c) async {
    final outs = <String>[];
    for (var i = 0; i < c.files.length; i++) {
      if (c.isCancelled()) break;
      final f = c.files[i];
      outs.add(await compressOffice(f, c, i));
    }
    return outs;
  }

  static Future<String> compressOffice(FileItem f, ToolCall c, [int index = 0]) async {
    final size = await File(f.path).length();
    final limit = budget(size, c) ?? (size * 0.6).floor();
    final done = await alreadyFits(f, limit, c);
    if (done != null) return done;
    Archive zip;
    try {
      zip = ZipDecoder().decodeBytes(await File(f.path).readAsBytes());
    } catch (_) {
      throw Exception('${f.name} looks like an old binary Office file (.doc/.xls). '
          'Save it as .docx/.xlsx first.');
    }
    final share = 1 / c.files.length;
    c.progress(index * share, 'Repacking ${f.name}');
    var data = _repack(zip, null);
    if (data.length > limit) {
      final rungs = _rungs.reversed.toList(); // search wants bigger = better
      var tries = 0;
      final (hit, smallest) = await search((k) async {
        tries++;
        c.progress(index * share + share * math.min(0.9, 0.15 * tries),
            'Shrinking pictures in ${f.name} (try $tries)');
        await Future<void>.delayed(Duration.zero); // let the progress paint
        return _repack(zip, rungs[k]);
      }, 0, rungs.length - 1, limit);
      data = hit ?? (smallest.length < data.length ? smallest : data);
    }
    final out = Fs.uniq(c.outDir, '${Fs.safeStem(f.name)} compressed.${f.ext}');
    await out.writeAsBytes(data);
    report(c, f.name, size, data.length, limit);
    return out.path;
  }

  // -------------------------------------------------------------- anything else

  static Future<String> zipOne(FileItem f, ToolCall c) async {
    final bytes = await File(f.path).readAsBytes();
    final archive = Archive()..addFile(ArchiveFile(f.name, bytes.length, bytes));
    final data = ZipEncoder().encode(archive, level: Deflate.BEST_COMPRESSION)!;
    final out = Fs.uniq(c.outDir, '${f.name}.zip');
    await out.writeAsBytes(data);
    report(c, '${f.name} → .zip', bytes.length, data.length, budget(bytes.length, c));
    return out.path;
  }

  // -------------------------------------------------------------- Compress anything

  /// Pick the right compressor for each file, one at a time.
  static Future<List<String>> toolCompressAny(ToolCall c) async {
    final outs = <String>[];
    for (var i = 0; i < c.files.length; i++) {
      if (c.isCancelled()) break;
      final f = c.files[i];
      final one = ToolCall(
        files: [f],
        params: c.params,
        outDir: c.outDir,
        progress: (p, m) => c.progress((i + p) / c.files.length, m),
        isCancelled: c.isCancelled,
        note: c.note,
      );
      final ext = f.ext == 'jpeg' ? 'jpg' : f.ext;
      try {
        if (ext == 'pdf') {
          outs.addAll(await PdfEngine.toolCompress(one));
        } else if (rasterIn.contains(ext)) {
          outs.addAll(await ImgEngine.toolCompress(one));
        } else if (MediaEngine.videoIn.contains(ext)) {
          outs.addAll(await MediaEngine.toolCompressVideo(one));
        } else if (MediaEngine.audioIn.contains(ext)) {
          outs.addAll(await MediaEngine.toolCompressAudio(one));
        } else if (office.contains(ext)) {
          outs.add(await compressOffice(f, one));
        } else {
          outs.add(await zipOne(f, one));
        }
      } catch (e) {
        if (c.files.length == 1) rethrow;
        c.note('${f.name}: failed — ${e.toString().replaceFirst('Exception: ', '')}');
      }
    }
    return outs;
  }
}
