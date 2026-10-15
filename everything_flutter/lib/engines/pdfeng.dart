/// PDF engine. Syncfusion (pure Dart) for structure and page surgery,
/// pdfrx/PDFium for rasterising pages. All of it runs offline on-device.
library;
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;
import 'dart:ui' show Color, Offset, Rect, Size;

import 'package:image/image.dart' as im;
import 'package:pdf/pdf.dart' show PdfPageFormat;
import 'package:pdf/widgets.dart' as pw;
import 'package:pdfrx/pdfrx.dart' as rx;
import 'package:syncfusion_flutter_pdf/pdf.dart' as sf;

import '../core/fs.dart';
import '../core/models.dart';
import '../core/shrink.dart';
import 'img.dart';

class PdfEngine {
  /// Parse "1-3, 5, 8-" into 0-based page indices. Blank means every page.
  static List<int> parsePages(String spec, int total) {
    final s = spec.trim();
    if (s.isEmpty) return List.generate(total, (i) => i);
    final out = <int>[];
    for (final part in s.split(RegExp(r'[,;]'))) {
      final chunk = part.trim();
      if (chunk.isEmpty) continue;
      final m = RegExp(r'^(\d*)\s*-\s*(\d*)$').firstMatch(chunk);
      if (m != null) {
        final a = int.tryParse(m.group(1)!) ?? 1;
        final b = int.tryParse(m.group(2)!) ?? total;
        for (var i = a; i <= b; i++) {
          if (i >= 1 && i <= total) out.add(i - 1);
        }
      } else {
        final n = int.tryParse(chunk);
        if (n != null && n >= 1 && n <= total) out.add(n - 1);
      }
    }
    return out;
  }

  static Future<sf.PdfDocument> _open(String path, [String? password]) async {
    final bytes = await File(path).readAsBytes();
    try {
      return password == null || password.isEmpty
          ? sf.PdfDocument(inputBytes: bytes)
          : sf.PdfDocument(inputBytes: bytes, password: password);
    } catch (e) {
      throw Exception(
          'Could not open this PDF. If it is password-protected, use "Remove password" first.');
    }
  }

  /// Copy [indices] of [src] into a fresh document, keeping each page's size.
  /// Syncfusion has no importPage, so each page is stamped as a template.
  static sf.PdfDocument _copyPages(sf.PdfDocument src, List<int> indices) {
    // A fresh document starts with no pages, so each page below is added
    // explicitly in its own section.
    final dst = sf.PdfDocument();
    for (final i in indices) {
      final template = src.pages[i].createTemplate();
      final section = dst.sections!.add();
      section.pageSettings.size = template.size;
      section.pageSettings.margins.all = 0;
      final page = section.pages.add();
      page.graphics.drawPdfTemplate(template, Offset.zero);
    }
    return dst;
  }

  static Future<File> _save(sf.PdfDocument doc, String dir, String name) async {
    final bytes = await doc.save();
    doc.dispose();
    final out = Fs.uniq(dir, name);
    await out.writeAsBytes(bytes);
    return out;
  }

  // ---------------------------------------------------------------- tools

  /// Merge PDFs and images into one PDF, in list order.
  static Future<List<String>> toolMerge(ToolCall c) async {
    final dst = sf.PdfDocument();
    for (var i = 0; i < c.files.length; i++) {
      if (c.isCancelled()) break;
      final f = c.files[i];
      c.progress(i / c.files.length, 'Adding ${f.name}');
      if (f.ext == 'pdf') {
        final src = await _open(f.path);
        for (var p = 0; p < src.pages.count; p++) {
          final template = src.pages[p].createTemplate();
          final section = dst.sections!.add();
          section.pageSettings.size = template.size;
          section.pageSettings.margins.all = 0;
          section.pages.add().graphics.drawPdfTemplate(template, Offset.zero);
        }
        src.dispose();
      } else {
        // An image becomes one page at its own pixel size.
        final bytes = await File(f.path).readAsBytes();
        final decoded = await ImgEngine.decode(f.path);
        final jpg = Uint8List.fromList(im.encodeJpg(decoded, quality: 92));
        final picture = sf.PdfBitmap(f.ext == 'jpg' ? bytes : jpg);
        final section = dst.sections!.add();
        section.pageSettings.size =
            Size(decoded.width.toDouble(), decoded.height.toDouble());
        section.pageSettings.margins.all = 0;
        section.pages.add().graphics.drawImage(picture,
            Rect.fromLTWH(0, 0, decoded.width.toDouble(), decoded.height.toDouble()));
      }
    }
    final stem = Fs.safeStem(c.files.first.name);
    final out = await _save(dst, c.outDir, '$stem merged.pdf');
    return [out.path];
  }

  /// Split into single pages, fixed chunks, or custom ranges.
  static Future<List<String>> toolSplit(ToolCall c) async {
    final outs = <String>[];
    final mode = c.strP('mode', 'every');
    for (final f in c.files) {
      if (c.isCancelled()) break;
      final src = await _open(f.path);
      final total = src.pages.count;
      final stem = Fs.safeStem(f.name);

      final batches = <List<int>>[];
      if (mode == 'every') {
        for (var i = 0; i < total; i++) {
          batches.add([i]);
        }
      } else if (mode == 'chunks') {
        final n = c.intP('chunk', 2).clamp(1, total == 0 ? 1 : total);
        for (var i = 0; i < total; i += n) {
          batches.add(List.generate(
              (i + n > total ? total : i + n) - i, (k) => i + k));
        }
      } else {
        for (final spec in c.strP('ranges').split(';')) {
          if (spec.trim().isEmpty) continue;
          final idx = parsePages(spec, total);
          if (idx.isNotEmpty) batches.add(idx);
        }
        if (batches.isEmpty) throw Exception('No valid ranges given');
      }

      for (var b = 0; b < batches.length; b++) {
        if (c.isCancelled()) break;
        c.progress(b / batches.length, 'Part ${b + 1} of ${batches.length}');
        final part = _copyPages(src, batches[b]);
        final label = batches[b].length == 1
            ? '${batches[b].first + 1}'
            : '${batches[b].first + 1}-${batches[b].last + 1}';
        outs.add((await _save(part, c.outDir, '$stem p$label.pdf')).path);
      }
      src.dispose();
    }
    return outs;
  }

  /// Keep / reorder, or delete, the listed pages.
  static Future<List<String>> toolSelectPages(ToolCall c) async {
    final outs = <String>[];
    final action = c.strP('action', 'extract');
    for (final f in c.files) {
      if (c.isCancelled()) break;
      c.progress(0.3, 'Rebuilding ${f.name}');
      final src = await _open(f.path);
      final total = src.pages.count;
      // "extract" keeps the order the user typed, so 3,1,2 really reorders.
      final listed = parsePages(c.strP('pages'), total);
      if (listed.isEmpty) throw Exception('No pages matched "${c.strP('pages')}"');
      final keep = action == 'delete'
          ? [for (var i = 0; i < total; i++) if (!listed.contains(i)) i]
          : listed;
      if (keep.isEmpty) throw Exception('That would delete every page');
      final dst = _copyPages(src, keep);
      src.dispose();
      outs.add((await _save(dst, c.outDir, '${Fs.safeStem(f.name)} pages.pdf')).path);
    }
    return outs;
  }

  /// Rotate pages in place, so nothing is re-rendered.
  static Future<List<String>> toolRotate(ToolCall c) async {
    final outs = <String>[];
    final angle = switch (c.strP('angle', '90')) {
      '180' => sf.PdfPageRotateAngle.rotateAngle180,
      '270' => sf.PdfPageRotateAngle.rotateAngle270,
      _ => sf.PdfPageRotateAngle.rotateAngle90,
    };
    for (final f in c.files) {
      if (c.isCancelled()) break;
      c.progress(0.3, 'Rotating ${f.name}');
      final doc = await _open(f.path);
      for (final i in parsePages(c.strP('pages'), doc.pages.count)) {
        doc.pages[i].rotation = angle;
      }
      outs.add((await _save(doc, c.outDir, '${Fs.safeStem(f.name)} rotated.pdf')).path);
    }
    return outs;
  }

  /// Shrink a PDF. Light/Balanced re-save with best compression; Strong/Extreme
  /// rasterise each page at a reduced DPI, which is what actually moves the needle
  /// on scan-heavy files. With the size controls on, it repacks first and only
  /// flattens pages (at the best DPI that fits) when that is allowed and needed.
  static Future<List<String>> toolCompress(ToolCall c) async {
    final outs = <String>[];
    final level = c.strP('level', 'medium');
    for (final f in c.files) {
      if (c.isCancelled()) break;
      final stem = Fs.safeStem(f.name);
      final size = await File(f.path).length();
      final limit = Shrink.budget(size, c);
      if (limit != null) {
        final copied = await Shrink.alreadyFits(f, limit, c);
        if (copied != null) {
          outs.add(copied);
          continue;
        }
        final data = await _fitPdf(f, limit, c);
        final out = Fs.uniq(c.outDir, '$stem compressed.pdf');
        await out.writeAsBytes(data);
        Shrink.report(c, f.name, size, data.length, limit);
        outs.add(out.path);
      } else if (level == 'low' || level == 'medium') {
        c.progress(0.3, 'Recompressing ${f.name}');
        final doc = await _open(f.path);
        doc.compressionLevel = level == 'low'
            ? sf.PdfCompressionLevel.normal
            : sf.PdfCompressionLevel.best;
        outs.add((await _save(doc, c.outDir, '$stem compressed.pdf')).path);
      } else {
        final dpi = level == 'high' ? 110.0 : 72.0;
        final quality = level == 'high' ? 70 : 45;
        c.progress(0.2, 'Rasterising ${f.name} at ${dpi.round()} DPI');
        final pages = await renderToImages(f.path,
            dpi: dpi,
            onPage: (i, n) => c.progress(0.2 + 0.6 * i / n, 'Page ${i + 1} of $n'),
            cancelled: c.isCancelled);
        final scratch = Fs.scratch();
        final paths = <String>[];
        for (var i = 0; i < pages.length; i++) {
          final p = File('${scratch.path}/p$i.jpg');
          await p.writeAsBytes(im.encodeJpg(pages[i], quality: quality));
          paths.add(p.path);
        }
        final bytes = await ImgEngine.buildPdf(paths, quality: quality);
        final out = Fs.uniq(c.outDir, '$stem compressed.pdf');
        await out.writeAsBytes(bytes);
        outs.add(out.path);
        await scratch.delete(recursive: true).catchError((_) => scratch);
      }
    }
    return outs;
  }

  /// Page resolution / JPEG quality for flattened pages, best first.
  static const _ladder = [
    (150.0, 80), (130.0, 72), (110.0, 64), (96.0, 56), (80.0, 48),
    (72.0, 40), (60.0, 34), (50.0, 28), (40.0, 22),
  ];

  static Future<Uint8List> _fitPdf(FileItem f, int limit, ToolCall c) async {
    c.progress(0.05, 'Repacking ${f.name}');
    final doc = await _open(f.path);
    doc.compressionLevel = sf.PdfCompressionLevel.best;
    var data = Uint8List.fromList(await doc.save());
    doc.dispose();
    if (data.length <= limit) return data;
    if (!c.boolP('flatten', true)) {
      c.note('${f.name}: repacking alone could not reach the target. Turn on '
          '"flatten pages" to go further.');
      return data;
    }
    final rungs = _ladder.reversed.toList(); // search wants bigger = better
    var tries = 0;
    final (hit, smallest) = await Shrink.search((k) {
      tries++;
      final (dpi, q) = rungs[k];
      return _flattened(f.path, dpi, q,
          onPage: (i, n) => c.progress(math.min(0.95, 0.1 + 0.15 * (tries - 1) + 0.15 * i / n),
              'Flattening ${f.name} at ${dpi.round()} DPI (try $tries)'),
          cancelled: c.isCancelled);
    }, 0, rungs.length - 1, limit);
    final best = hit ?? (smallest.length < data.length ? smallest : data);
    if (!identical(best, data)) {
      c.note('${f.name}: pages were flattened to images, so text is no longer selectable');
    }
    return best;
  }

  /// Every page becomes one JPEG at [dpi], one page at a time so a long
  /// document never sits in memory as raw pixels.
  static Future<Uint8List> _flattened(String path, double dpi, int quality,
      {void Function(int, int)? onPage, bool Function()? cancelled}) async {
    final src = await rx.PdfDocument.openFile(path);
    final out = pw.Document();
    try {
      for (var i = 0; i < src.pages.length; i++) {
        if (cancelled?.call() ?? false) break;
        onPage?.call(i, src.pages.length);
        final page = src.pages[i];
        final scale = dpi / 72.0;
        final w = (page.width * scale).round().clamp(1, 10000);
        final h = (page.height * scale).round().clamp(1, 10000);
        final rendered = await page.render(
          fullWidth: w.toDouble(),
          fullHeight: h.toDouble(),
          width: w,
          height: h,
          backgroundColor: const Color(0xFFFFFFFF),
        );
        if (rendered == null) continue;
        final jpg = im.encodeJpg(_toImage(rendered), quality: quality);
        rendered.dispose();
        final mem = pw.MemoryImage(jpg);
        out.addPage(pw.Page(
          pageFormat: PdfPageFormat(page.width, page.height),
          margin: pw.EdgeInsets.zero,
          build: (_) => pw.Image(mem, fit: pw.BoxFit.fill),
        ));
      }
    } finally {
      await src.dispose();
    }
    return out.save();
  }

  /// Stamp text across every page.
  static Future<List<String>> toolWatermark(ToolCall c) async {
    final outs = <String>[];
    final text = c.strP('text', 'CONFIDENTIAL');
    final size = c.dblP('size', 60);
    final opacity = c.dblP('opacity', 0.15);
    final diagonal = c.boolP('diagonal', true);
    final hex = c.strP('color', '#ff0000').replaceAll('#', '');
    final rgb = int.tryParse(hex, radix: 16) ?? 0xff0000;
    final color = sf.PdfColor((rgb >> 16) & 0xff, (rgb >> 8) & 0xff, rgb & 0xff);

    for (final f in c.files) {
      if (c.isCancelled()) break;
      final doc = await _open(f.path);
      final font = sf.PdfStandardFont(sf.PdfFontFamily.helvetica, size,
          style: sf.PdfFontStyle.bold);
      for (var i = 0; i < doc.pages.count; i++) {
        if (c.isCancelled()) break;
        c.progress(i / doc.pages.count, 'Page ${i + 1} of ${doc.pages.count}');
        final page = doc.pages[i];
        final g = page.graphics;
        final box = page.getClientSize();
        final tw = font.measureString(text).width;
        final state = g.save();
        g.setTransparency(opacity);
        g.translateTransform(box.width / 2, box.height / 2);
        if (diagonal) g.rotateTransform(-45);
        g.drawString(text, font,
            brush: sf.PdfSolidBrush(color),
            bounds: Rect.fromLTWH(-tw / 2, -size / 2, tw + 4, size * 1.4));
        g.restore(state);
      }
      outs.add((await _save(doc, c.outDir, '${Fs.safeStem(f.name)} watermarked.pdf')).path);
    }
    return outs;
  }

  /// Add "{n} / {total}" style page numbers.
  static Future<List<String>> toolPageNumbers(ToolCall c) async {
    final outs = <String>[];
    final fmt = c.strP('format', '{n} / {total}');
    final pos = c.strP('position', 'bottom-center');
    final size = c.dblP('size', 10);
    for (final f in c.files) {
      if (c.isCancelled()) break;
      final doc = await _open(f.path);
      final font = sf.PdfStandardFont(sf.PdfFontFamily.helvetica, size);
      final total = doc.pages.count;
      for (var i = 0; i < total; i++) {
        if (c.isCancelled()) break;
        c.progress(i / total, 'Page ${i + 1} of $total');
        final page = doc.pages[i];
        final box = page.getClientSize();
        final label = fmt
            .replaceAll('{n}', '${i + 1}')
            .replaceAll('{total}', '$total');
        final tw = font.measureString(label).width;
        const pad = 24.0;
        final x = switch (pos.split('-')[1]) {
          'left' => pad,
          'right' => box.width - tw - pad,
          _ => (box.width - tw) / 2,
        };
        final y = pos.startsWith('top') ? pad : box.height - size - pad;
        page.graphics.drawString(label, font,
            brush: sf.PdfSolidBrush(sf.PdfColor(80, 80, 110)),
            bounds: Rect.fromLTWH(x, y, tw + 4, size * 1.6));
      }
      outs.add((await _save(doc, c.outDir, '${Fs.safeStem(f.name)} numbered.pdf')).path);
    }
    return outs;
  }

  static Future<List<String>> toolProtect(ToolCall c) async {
    final pw = c.strP('password');
    if (pw.isEmpty) throw Exception('Type a password first');
    final outs = <String>[];
    for (final f in c.files) {
      if (c.isCancelled()) break;
      c.progress(0.4, 'Locking ${f.name}');
      final doc = await _open(f.path);
      doc.security
        ..algorithm = sf.PdfEncryptionAlgorithm.aesx256Bit
        ..userPassword = pw
        ..ownerPassword = pw;
      outs.add((await _save(doc, c.outDir, '${Fs.safeStem(f.name)} locked.pdf')).path);
    }
    return outs;
  }

  static Future<List<String>> toolUnlock(ToolCall c) async {
    final pw = c.strP('password');
    final outs = <String>[];
    for (final f in c.files) {
      if (c.isCancelled()) break;
      c.progress(0.4, 'Unlocking ${f.name}');
      final doc = await _open(f.path, pw);
      // Re-stamping every page into a clean document drops the encryption.
      final clean = _copyPages(doc, List.generate(doc.pages.count, (i) => i));
      doc.dispose();
      outs.add((await _save(clean, c.outDir, '${Fs.safeStem(f.name)} unlocked.pdf')).path);
    }
    return outs;
  }

  /// Save each page as an image file.
  static Future<List<String>> toolPageImages(ToolCall c) async {
    final outs = <String>[];
    final dpi = c.dblP('dpi', 150);
    final fmt = c.strP('format', 'png');
    for (final f in c.files) {
      if (c.isCancelled()) break;
      final stem = Fs.safeStem(f.name);
      final pages = await renderToImages(f.path,
          dpi: dpi,
          pages: c.strP('pages'),
          onPage: (i, n) => c.progress(i / n, 'Page ${i + 1} of $n'),
          cancelled: c.isCancelled);
      for (var i = 0; i < pages.length; i++) {
        final out = Fs.uniq(c.outDir, '$stem p${i + 1}.$fmt');
        await out.writeAsBytes(await ImgEngine.encode(pages[i], fmt, quality: 92));
        outs.add(out.path);
      }
    }
    return outs;
  }

  // ---------------------------------------------------------------- convert

  /// Convert view: pdf -> png/jpg/… (one file per page).
  static Future<List<String>> pdfToRaster(
      FileItem f, String target, ToolCall c) async {
    final pages = await renderToImages(f.path,
        dpi: c.dblP('dpi', 150),
        pages: c.strP('pages'),
        onPage: (i, n) => c.progress(i / n, 'Page ${i + 1} of $n'),
        cancelled: c.isCancelled);
    final outs = <String>[];
    final stem = Fs.safeStem(f.name);
    for (var i = 0; i < pages.length; i++) {
      final name = pages.length == 1 ? '$stem.$target' : '$stem p${i + 1}.$target';
      final out = Fs.uniq(c.outDir, name);
      await out.writeAsBytes(
          await ImgEngine.encode(pages[i], target, quality: c.intP('quality', 90)));
      outs.add(out.path);
    }
    return outs;
  }

  /// Pull text out as proper lines.
  ///
  /// `extractText()` is not good enough: for PDFs whose text is emitted one
  /// word at a time (anything produced by dart_pdf, among others) it returns
  /// a single word per line, which makes the .txt output unreadable.
  /// `extractTextLines()` reassembles the real lines.
  static String _extractLines(sf.PdfDocument doc, {int? page}) {
    final lines = sf.PdfTextExtractor(doc)
        .extractTextLines(startPageIndex: page, endPageIndex: page);
    return lines.map((l) => l.text.trimRight()).join('\n');
  }

  /// Convert view: pdf -> txt.
  static Future<List<String>> pdfToText(
      FileItem f, String target, ToolCall c) async {
    c.progress(0.4, 'Reading text from ${f.name}');
    final doc = await _open(f.path);
    final text = _extractLines(doc);
    doc.dispose();
    final out = Fs.uniq(c.outDir, '${Fs.safeStem(f.name)}.txt');
    await out.writeAsString(text);
    return [out.path];
  }

  /// Convert view: pdf -> md / html, built from the extracted text.
  static Future<List<String>> pdfToMarkup(
      FileItem f, String target, ToolCall c) async {
    c.progress(0.4, 'Reading text from ${f.name}');
    final doc = await _open(f.path);
    final buf = StringBuffer();
    if (target == 'html') {
      buf.writeln('<!doctype html><meta charset="utf-8">');
      buf.writeln('<title>${_esc(f.name)}</title>');
    }
    for (var i = 0; i < doc.pages.count; i++) {
      final text = _extractLines(doc, page: i);
      if (target == 'html') {
        buf.writeln('<section><h2>Page ${i + 1}</h2>');
        for (final line in text.split('\n')) {
          if (line.trim().isNotEmpty) buf.writeln('<p>${_esc(line)}</p>');
        }
        buf.writeln('</section>');
      } else {
        buf.writeln('## Page ${i + 1}\n');
        buf.writeln(text.trim());
        buf.writeln();
      }
    }
    doc.dispose();
    final out = Fs.uniq(c.outDir, '${Fs.safeStem(f.name)}.$target');
    await out.writeAsString(buf.toString());
    return [out.path];
  }

  static String _esc(String s) => s
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;');

  // ---------------------------------------------------------------- raster

  /// Render pages to Dart images via PDFium.
  static Future<List<im.Image>> renderToImages(
    String path, {
    double dpi = 150,
    String pages = '',
    void Function(int, int)? onPage,
    bool Function()? cancelled,
  }) async {
    final doc = await rx.PdfDocument.openFile(path);
    try {
      final want = parsePages(pages, doc.pages.length);
      final out = <im.Image>[];
      for (var k = 0; k < want.length; k++) {
        if (cancelled?.call() ?? false) break;
        onPage?.call(k, want.length);
        final page = doc.pages[want[k]];
        final scale = dpi / 72.0;
        final w = (page.width * scale).round().clamp(1, 10000);
        final h = (page.height * scale).round().clamp(1, 10000);
        final rendered = await page.render(
          fullWidth: w.toDouble(),
          fullHeight: h.toDouble(),
          width: w,
          height: h,
          backgroundColor: const Color(0xFFFFFFFF),
        );
        if (rendered == null) continue;
        out.add(_toImage(rendered));
        rendered.dispose();
      }
      return out;
    } finally {
      await doc.dispose();
    }
  }

  /// PDFium hands back raw RGBA/BGRA; wrap it without a re-encode round-trip.
  static im.Image _toImage(rx.PdfImage r) {
    final src = im.Image.fromBytes(
      width: r.width,
      height: r.height,
      bytes: r.pixels.buffer,
      // pixels may be a view into a larger buffer, so start where it starts.
      bytesOffset: r.pixels.offsetInBytes,
      numChannels: 4,
      order: r.format == ui.PixelFormat.bgra8888
          ? im.ChannelOrder.bgra
          : im.ChannelOrder.rgba,
    );
    // Copy, because the source buffer is disposed with the PdfImage.
    return src.clone();
  }

  /// First-page thumbnail for file rows and the editor.
  static Future<Uint8List?> thumbnail(String path, {int width = 120}) async {
    try {
      final doc = await rx.PdfDocument.openFile(path);
      try {
        if (doc.pages.isEmpty) return null;
        final page = doc.pages.first;
        final h = (width * page.height / page.width).round().clamp(1, 4000);
        final r = await page.render(
          fullWidth: width.toDouble(),
          fullHeight: h.toDouble(),
          width: width,
          height: h,
          backgroundColor: const Color(0xFFFFFFFF),
        );
        if (r == null) return null;
        final image = _toImage(r);
        r.dispose();
        return Uint8List.fromList(im.encodePng(image));
      } finally {
        await doc.dispose();
      }
    } catch (_) {
      return null;
    }
  }

  /// PNG-encode a rendered page so it can go straight into Image.memory.
  static Future<Uint8List> thumbnailBytes(im.Image image) async =>
      Uint8List.fromList(im.encodePng(image));

  static Future<int> pageCount(String path) async {
    final doc = await rx.PdfDocument.openFile(path);
    final n = doc.pages.length;
    await doc.dispose();
    return n;
  }
}
