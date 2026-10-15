/// Image engine. Pure-Dart `image` for decode/transform, Android's native
/// codecs (flutter_image_compress) for WebP/HEIC output, which `image` can't encode.
library;
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;
import 'dart:ui' show Rect;

import 'package:flutter_image_compress/flutter_image_compress.dart';
import 'package:image/image.dart' as im;
import 'package:path/path.dart' as pp;
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;

import '../core/fs.dart';
import '../core/models.dart';
import '../core/shrink.dart';

/// Formats we can read.
const rasterIn = [
  'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'tiff', 'tif', 'ico', 'tga',
  'heic', 'heif', 'psd', 'pnm', 'exr',
];

/// Formats we can write. webp/heic go through the native encoder.
const rasterOut = ['jpg', 'png', 'webp', 'gif', 'bmp', 'tiff', 'ico', 'tga', 'heic'];

/// Needs Android's native decoder rather than the Dart one.
const _nativeOnlyIn = ['heic', 'heif'];

class ImgEngine {
  /// Decode to a Dart image. HEIC has no Dart decoder, so it goes through the
  /// platform codec instead.
  static Future<im.Image> decode(String path) async {
    final ext = FileItem.extOf(path);
    final bytes = await File(path).readAsBytes();
    if (_nativeOnlyIn.contains(ext)) return _decodeNative(bytes, path);

    final decoded = im.decodeNamedImage(path, bytes);
    if (decoded == null) {
      // Some files lie about their extension; let the platform have a go.
      return _decodeNative(bytes, path);
    }
    return decoded;
  }

  /// Decode via Flutter's own image codec, which on Android hands off to the
  /// system decoders (HEIC included, on API 28+). Deliberately not routed
  /// through flutter_image_compress: its minWidth/minHeight default to
  /// 1920x1080 and would quietly downscale a full-size photo.
  static Future<im.Image> _decodeNative(Uint8List bytes, String path) async {
    ui.Image frame;
    try {
      final codec = await ui.instantiateImageCodec(bytes);
      frame = (await codec.getNextFrame()).image;
    } catch (_) {
      throw Exception(
          'Could not read ${pp.basename(path)} - unsupported or damaged image');
    }
    final data = await frame.toByteData(format: ui.ImageByteFormat.rawRgba);
    final width = frame.width;
    final height = frame.height;
    frame.dispose();
    if (data == null) {
      throw Exception('Could not read ${pp.basename(path)}');
    }
    return im.Image.fromBytes(
      width: width,
      height: height,
      bytes: data.buffer,
      bytesOffset: data.offsetInBytes,
      numChannels: 4,
      order: im.ChannelOrder.rgba,
    );
  }

  /// Encode to [ext]. Returns bytes ready to write.
  static Future<Uint8List> encode(im.Image image, String ext,
      {int quality = 90, int pngColors = 0}) async {
    switch (ext) {
      case 'jpg':
      case 'jpeg':
        return im.encodeJpg(image, quality: quality);
      case 'png':
        final src =
            pngColors > 1 ? im.quantize(image, numberOfColors: pngColors) : image;
        return im.encodePng(src);
      case 'gif':
        return im.encodeGif(image);
      case 'bmp':
        return im.encodeBmp(image);
      case 'tiff':
      case 'tif':
        return im.encodeTiff(image);
      case 'ico':
        return im.encodeIco(image);
      case 'tga':
        return im.encodeTga(image);
      case 'webp':
      case 'heic':
        // No Dart encoder for these; hand the pixels to Android.
        final png = im.encodePng(image);
        final out = await FlutterImageCompress.compressWithList(
          png,
          format: ext == 'webp' ? CompressFormat.webp : CompressFormat.heic,
          quality: quality,
          minWidth: image.width,
          minHeight: image.height,
        );
        return Uint8List.fromList(out);
      default:
        throw Exception('Cannot write .$ext images');
    }
  }

  static bool canWrite(String ext) => rasterOut.contains(ext);

  /// Rotate by [quarterTurns] then keep only [frac] of the result.
  ///
  /// [frac] is in 0..1 of the *rotated* image, because that is what the user
  /// was looking at when they dragged the crop box.
  static im.Image cropRotate(im.Image src, Rect frac, {int quarterTurns = 0}) {
    var image = src;
    final turns = quarterTurns % 4;
    if (turns != 0) image = im.copyRotate(image, angle: turns * 90);

    final x = (frac.left * image.width).round().clamp(0, image.width - 1);
    final y = (frac.top * image.height).round().clamp(0, image.height - 1);
    final w = (frac.width * image.width).round().clamp(1, image.width - x);
    final h = (frac.height * image.height).round().clamp(1, image.height - y);
    if (x == 0 && y == 0 && w == image.width && h == image.height) return image;
    return im.copyCrop(image, x: x, y: y, width: w, height: h);
  }

  /// Convert view: image -> image.
  static Future<List<String>> rasterToRaster(
      FileItem f, String target, ToolCall c) async {
    final image = await decode(f.path);
    final bytes = await encode(image, target, quality: c.intP('quality', 90));
    final out = Fs.uniq(c.outDir, '${Fs.safeStem(f.name)}.$target');
    await out.writeAsBytes(bytes);
    return [out.path];
  }

  /// Convert view: image -> pdf (one image, one page).
  static Future<List<String>> rasterToPdf(
      FileItem f, String target, ToolCall c) async {
    final out = Fs.uniq(c.outDir, '${Fs.safeStem(f.name)}.pdf');
    await out.writeAsBytes(await buildPdf([f.path], pageSize: 'fit', quality: 92));
    return [out.path];
  }

  // ---------------------------------------------------------------- tools

  /// Image tools -> Compress images. With the size controls on, each image is
  /// fitted to a byte budget; otherwise the quality / max side settings apply.
  static Future<List<String>> toolCompress(ToolCall c) async {
    final outs = <String>[];
    final quality = c.intP('quality', 75);
    final maxSide = c.intP('max_side', 0);
    final fmt = c.strP('format', 'keep');
    final pngColors = c.intP('png_colors', 0);
    for (var i = 0; i < c.files.length; i++) {
      if (c.isCancelled()) break;
      final f = c.files[i];
      c.progress(i / c.files.length, 'Compressing ${f.name}');
      final size = await File(f.path).length();
      final limit = Shrink.budget(size, c);
      final copied = await Shrink.alreadyFits(f, limit, c);
      if (copied != null) {
        outs.add(copied);
        continue;
      }
      var image = await decode(f.path);
      if (maxSide > 0 && (image.width > maxSide || image.height > maxSide)) {
        image = image.width >= image.height
            ? im.copyResize(image, width: maxSide)
            : im.copyResize(image, height: maxSide);
      }
      var ext = fmt == 'keep' ? f.ext : fmt;
      if (ext == 'jpeg') ext = 'jpg';
      if (ext == 'tif') ext = 'tiff';
      if (!canWrite(ext)) ext = 'jpg';
      final bytes = limit == null
          ? await encode(image, ext, quality: quality, pngColors: pngColors)
          : await fitImage(image, ext, limit,
              pngColors: pngColors,
              onTry: (n) => c.progress(
                  (i + math.min(0.9, n * 0.12)) / c.files.length,
                  'Finding the best quality for ${f.name} (try $n)'));
      final out = Fs.uniq(c.outDir, '${Fs.safeStem(f.name)}.$ext');
      await out.writeAsBytes(bytes);
      Shrink.report(c, f.name, size, bytes.length, limit);
      outs.add(out.path);
    }
    return outs;
  }

  static const _lossy = ['jpg', 'webp', 'heic'];

  /// Best-looking encode of [image] as [ext] that fits in [limit] bytes.
  ///
  /// Lossy formats binary-search quality first; if even the lowest quality is
  /// too big (or the format is lossless) the picture is scaled down and the
  /// search repeats.
  static Future<Uint8List> fitImage(im.Image image, String ext, int limit,
      {int pngColors = 0, void Function(int)? onTry}) async {
    // On a device, JPEG goes through Android's codec too: it's many times
    // faster than the Dart encoder, which matters when trying several qualities.
    final native = Platform.isAndroid || Platform.isIOS;
    Uint8List? png; // the native codec takes encoded input, so make it once per size
    var tries = 0;
    Future<Uint8List> lossy(im.Image img, int q) async {
      onTry?.call(++tries);
      await Future<void>.delayed(Duration.zero); // let the progress paint
      if (ext == 'jpg' && !native) return im.encodeJpg(img, quality: q);
      png ??= im.encodePng(img, level: 1);
      final out = await FlutterImageCompress.compressWithList(
        png!,
        format: switch (ext) {
          'webp' => CompressFormat.webp,
          'heic' => CompressFormat.heic,
          _ => CompressFormat.jpeg,
        },
        quality: q,
        minWidth: img.width,
        minHeight: img.height,
      );
      return Uint8List.fromList(out);
    }

    Uint8List? smallest;
    var cur = image;
    for (var round = 0; round < 10; round++) {
      Uint8List? hit;
      Uint8List low;
      if (_lossy.contains(ext)) {
        final img = cur;
        png = null;
        (hit, low) = await Shrink.search((q) => lossy(img, q), 5, 95, limit);
      } else {
        onTry?.call(++tries);
        await Future<void>.delayed(Duration.zero);
        low = await encode(cur, ext, quality: 95, pngColors: pngColors);
        if (low.length <= limit) {
          hit = low;
        } else if (ext == 'png' && pngColors == 0) {
          final pal = await encode(cur, ext, pngColors: 256);
          if (pal.length < low.length) low = pal;
          if (pal.length <= limit) hit = pal;
        }
      }
      if (hit != null) return hit;
      if (smallest == null || low.length < smallest.length) smallest = low;
      // Pixels scale with area, so step the sides by the square root of what's
      // left to shed.
      final f = (math.sqrt(limit / low.length) * 0.95).clamp(0.35, 0.9);
      final w = (cur.width * f).round();
      final h = (cur.height * f).round();
      if (w < 8 || h < 8) break;
      cur = im.copyResize(cur,
          width: w, height: h, interpolation: im.Interpolation.average);
    }
    return smallest!;
  }

  /// Image tools -> Resize images.
  static Future<List<String>> toolResize(ToolCall c) async {
    final outs = <String>[];
    final mode = c.strP('mode', 'percent');
    for (var i = 0; i < c.files.length; i++) {
      if (c.isCancelled()) break;
      final f = c.files[i];
      c.progress(i / c.files.length, 'Resizing ${f.name}');
      final image = await decode(f.path);
      im.Image resized;
      if (mode == 'percent') {
        final pct = c.dblP('percent', 50) / 100;
        resized = im.copyResize(image,
            width: (image.width * pct).round().clamp(1, 65536),
            height: (image.height * pct).round().clamp(1, 65536));
      } else {
        final w = c.intP('width', 0);
        final h = c.intP('height', 0);
        if (w <= 0 && h <= 0) {
          throw Exception('Give a width or a height to resize to');
        }
        if (c.boolP('keep_ratio', true)) {
          // Fit inside the box, keeping proportions.
          resized = im.copyResize(image,
              width: w > 0 ? w : null, height: w > 0 ? null : h);
          if (w > 0 && h > 0 && resized.height > h) {
            resized = im.copyResize(image, height: h);
          }
        } else {
          resized = im.copyResize(image,
              width: w > 0 ? w : image.width, height: h > 0 ? h : image.height);
        }
      }
      final ext = canWrite(f.ext) ? f.ext : 'png';
      final out = Fs.uniq(c.outDir, '${Fs.safeStem(f.name)}.$ext');
      await out.writeAsBytes(await encode(resized, ext, quality: 92));
      outs.add(out.path);
    }
    return outs;
  }

  /// Image tools -> Rotate / flip / grayscale.
  static Future<List<String>> toolTransform(ToolCall c) async {
    final outs = <String>[];
    final rotate = c.intP('rotate', 0);
    for (var i = 0; i < c.files.length; i++) {
      if (c.isCancelled()) break;
      final f = c.files[i];
      c.progress(i / c.files.length, 'Editing ${f.name}');
      var image = await decode(f.path);
      if (rotate != 0) image = im.copyRotate(image, angle: rotate);
      if (c.boolP('flip_h')) image = im.flipHorizontal(image);
      if (c.boolP('flip_v')) image = im.flipVertical(image);
      if (c.boolP('grayscale')) image = im.grayscale(image);
      if (c.boolP('strip_metadata', true)) image.exif = im.ExifData();
      final ext = canWrite(f.ext) ? f.ext : 'png';
      final out = Fs.uniq(c.outDir, '${Fs.safeStem(f.name)}.$ext');
      await out.writeAsBytes(await encode(image, ext, quality: 92));
      outs.add(out.path);
    }
    return outs;
  }

  /// Image tools -> Images into one PDF. Also backs the scanner's export.
  static Future<List<String>> toolImagesToPdf(ToolCall c) async {
    c.progress(0.1, 'Laying out ${c.files.length} page(s)');
    final bytes = await buildPdf(
      c.files.map((f) => f.path).toList(),
      pageSize: c.strP('page_size', 'fit'),
      margin: c.dblP('margin', 0),
      quality: c.intP('quality', 92),
      onPage: (i, n) => c.progress(0.1 + 0.8 * i / n, 'Page ${i + 1} of $n'),
      cancelled: c.isCancelled,
    );
    final stem = c.files.length == 1
        ? Fs.safeStem(c.files.first.name)
        : '${Fs.safeStem(c.files.first.name)} +${c.files.length - 1}';
    final out = Fs.uniq(c.outDir, '$stem.pdf');
    await out.writeAsBytes(bytes);
    return [out.path];
  }

  /// Shared PDF builder: every image becomes one page, in list order.
  static Future<Uint8List> buildPdf(
    List<String> paths, {
    String pageSize = 'fit',
    double margin = 0,
    int quality = 92,
    void Function(int, int)? onPage,
    bool Function()? cancelled,
  }) async {
    final doc = pw.Document();
    var added = 0;
    for (var i = 0; i < paths.length; i++) {
      if (cancelled?.call() ?? false) break;
      onPage?.call(i, paths.length);
      final image = await decode(paths[i]);
      // Re-encode as JPEG so the PDF stays a sane size.
      final jpg = im.encodeJpg(image, quality: quality);
      final mem = pw.MemoryImage(jpg);
      final w = image.width.toDouble();
      final h = image.height.toDouble();
      final format = pageSize == 'a4'
          ? PdfPageFormat.a4
          : PdfPageFormat(w + margin * 2, h + margin * 2);
      doc.addPage(
        pw.Page(
          pageFormat: format,
          margin: pw.EdgeInsets.all(margin),
          build: (_) => pw.Center(child: pw.Image(mem, fit: pw.BoxFit.contain)),
        ),
      );
      added++;
    }
    if (added == 0) throw Exception('No pages to write');
    return doc.save();
  }
}
