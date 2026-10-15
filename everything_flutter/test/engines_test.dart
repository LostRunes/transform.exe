/// End-to-end engine tests: real files in, real files out, re-opened and
/// checked. These cover the pure-Dart engines. Anything needing PDFium or an
/// Android platform codec (PDF rasterising, WebP/HEIC encoding) can only run
/// on a device and is called out in the README instead of faked here.
library;

import 'dart:convert';
import 'dart:io';

import 'package:everything_converter/core/fs.dart';
import 'package:everything_converter/core/models.dart';
import 'package:everything_converter/core/registry.dart';
import 'package:everything_converter/engines/data.dart';
import 'package:everything_converter/engines/doc.dart';
import 'package:everything_converter/engines/img.dart';
import 'package:everything_converter/engines/pdfeng.dart';
import 'package:flutter_test/flutter_test.dart';
import 'dart:ui' show Rect;

import 'package:image/image.dart' as im;
import 'package:path/path.dart' as pp;
import 'package:syncfusion_flutter_pdf/pdf.dart' as sf;

late Directory tmp;

/// Build a ToolCall the way JobQueue does.
ToolCall call(List<FileItem> files, Map<String, Object?> params) => ToolCall(
      files: files,
      params: params,
      outDir: tmp.path,
      progress: (_, _) {},
      isCancelled: () => false,
    );

Future<FileItem> item(String path) async => FileItem(
      path: path,
      name: pp.basename(path),
      ext: FileItem.extOf(path),
      size: await File(path).length(),
    );

/// A real PNG on disk.
Future<String> makePng(String name, {int w = 120, int h = 80}) async {
  final image = im.Image(width: w, height: h);
  im.fill(image, color: im.ColorRgb8(200, 120, 180));
  im.fillRect(image,
      x1: 10, y1: 10, x2: w - 10, y2: h - 10, color: im.ColorRgb8(40, 40, 90));
  final f = File(pp.join(tmp.path, name));
  await f.writeAsBytes(im.encodePng(image));
  return f.path;
}

/// A noisy PNG, so JPEG quality settings behave as they would on a photo.
Future<String> makeNoisyPng(String name, {int w = 160, int h = 120}) async {
  final image = im.Image(width: w, height: h);
  var seed = 7;
  for (var y = 0; y < h; y++) {
    for (var x = 0; x < w; x++) {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      image.setPixelRgb(x, y, seed % 255, (seed >> 8) % 255, (seed >> 16) % 255);
    }
  }
  final f = File(pp.join(tmp.path, name));
  await f.writeAsBytes(im.encodePng(image));
  return f.path;
}

/// A real multi-page PDF on disk.
Future<String> makePdf(String name, int pages) async {
  final doc = sf.PdfDocument();
  for (var i = 0; i < pages; i++) {
    final page = doc.pages.add();
    page.graphics.drawString(
      'Page ${i + 1}',
      sf.PdfStandardFont(sf.PdfFontFamily.helvetica, 24),
    );
  }
  final f = File(pp.join(tmp.path, name));
  await f.writeAsBytes(await doc.save());
  doc.dispose();
  return f.path;
}

Future<int> pdfPages(String path) async {
  final doc = sf.PdfDocument(inputBytes: await File(path).readAsBytes());
  final n = doc.pages.count;
  doc.dispose();
  return n;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('ec_engine');
    Fs.initWith(root: tmp);
    buildGraph();
  });

  tearDown(() {
    try {
      tmp.deleteSync(recursive: true);
    } catch (_) {
      // Windows sometimes still holds a handle; the temp dir can linger.
    }
  });

  group('images', () {
    test('png converts to jpg and is a real jpg', () async {
      final src = await item(await makePng('in.png'));
      final out = await ImgEngine.rasterToRaster(src, 'jpg', call([src], {}));

      expect(out, hasLength(1));
      expect(File(out.first).existsSync(), isTrue);
      final decoded = im.decodeJpg(await File(out.first).readAsBytes());
      expect(decoded, isNotNull);
      expect(decoded!.width, 120);
      expect(decoded.height, 80);
    });

    test('resize by percent halves the image', () async {
      final src = await item(await makePng('r.png'));
      final out = await ImgEngine.toolResize(
          call([src], {'mode': 'percent', 'percent': 50}));

      final decoded = im.decodePng(await File(out.first).readAsBytes())!;
      expect(decoded.width, 60);
      expect(decoded.height, 40);
    });

    test('resize to exact pixels keeps the aspect ratio', () async {
      final src = await item(await makePng('r2.png'));
      final out = await ImgEngine.toolResize(call([src],
          {'mode': 'pixels', 'width': 60, 'height': 0, 'keep_ratio': true}));

      final decoded = im.decodePng(await File(out.first).readAsBytes())!;
      expect(decoded.width, 60);
      expect(decoded.height, 40);
    });

    test('rotating 90 degrees swaps the dimensions', () async {
      final src = await item(await makePng('t.png'));
      final out = await ImgEngine.toolTransform(call([src], {'rotate': 90}));

      final decoded = im.decodePng(await File(out.first).readAsBytes())!;
      expect(decoded.width, 80);
      expect(decoded.height, 120);
    });

    test('the compress quality knob really changes the output size', () async {
      final src = await item(await makeNoisyPng('c.png'));
      final low = await ImgEngine.toolCompress(
          call([src], {'quality': 20, 'format': 'jpg', 'max_side': 0}));
      final high = await ImgEngine.toolCompress(
          call([src], {'quality': 95, 'format': 'jpg', 'max_side': 0}));

      expect(await File(low.first).length(),
          lessThan(await File(high.first).length()));
    });

    test('max_side caps the longest edge', () async {
      final src = await item(await makeNoisyPng('m.png', w: 400, h: 200));
      final out = await ImgEngine.toolCompress(
          call([src], {'quality': 80, 'format': 'jpg', 'max_side': 100}));

      final decoded = im.decodeJpg(await File(out.first).readAsBytes())!;
      expect(decoded.width, 100);
      expect(decoded.height, 50);
    });

    test('several images become one PDF with one page each', () async {
      final a = await item(await makePng('p1.png'));
      final b = await item(await makePng('p2.png'));
      final c = await item(await makePng('p3.png'));
      final out = await ImgEngine.toolImagesToPdf(
          call([a, b, c], {'page_size': 'fit', 'margin': 0, 'quality': 90}));

      expect(out, hasLength(1));
      expect(await pdfPages(out.first), 3);
    });
  });

  group('crop', () {
    test('a half-width crop keeps the left half', () async {
      final src = im.decodePng(
          await File(await makeNoisyPng('crop.png', w: 200, h: 100))
              .readAsBytes())!;

      final out = ImgEngine.cropRotate(
          src, const Rect.fromLTRB(0, 0, 0.5, 1.0));

      expect(out.width, 100);
      expect(out.height, 100);
      // Same pixels as the original's top-left corner.
      expect(out.getPixel(0, 0), src.getPixel(0, 0));
    });

    test('a centred crop lands on the right pixels', () async {
      final src = im.decodePng(
          await File(await makeNoisyPng('crop2.png', w: 100, h: 100))
              .readAsBytes())!;

      final out = ImgEngine.cropRotate(
          src, const Rect.fromLTRB(0.25, 0.25, 0.75, 0.75));

      expect(out.width, 50);
      expect(out.height, 50);
      expect(out.getPixel(0, 0), src.getPixel(25, 25));
    });

    test('rotation is applied before the crop', () async {
      final src = im.decodePng(
          await File(await makeNoisyPng('crop3.png', w: 200, h: 100))
              .readAsBytes())!;

      // One quarter turn makes it 100x200, so a full-height crop is 200 tall.
      final out = ImgEngine.cropRotate(
          src, const Rect.fromLTRB(0, 0, 1, 1), quarterTurns: 1);

      expect(out.width, 100);
      expect(out.height, 200);
    });

    test('a full-frame crop with no rotation is a no-op', () async {
      final src = im.decodePng(
          await File(await makeNoisyPng('crop4.png', w: 60, h: 40))
              .readAsBytes())!;

      final out = ImgEngine.cropRotate(src, const Rect.fromLTRB(0, 0, 1, 1));
      expect(out.width, 60);
      expect(out.height, 40);
    });

    test('an out-of-range rect is clamped instead of throwing', () async {
      final src = im.decodePng(
          await File(await makeNoisyPng('crop5.png', w: 50, h: 50))
              .readAsBytes())!;

      final out = ImgEngine.cropRotate(
          src, const Rect.fromLTRB(0.9, 0.9, 2.0, 2.0));

      expect(out.width, greaterThan(0));
      expect(out.height, greaterThan(0));
      expect(out.width, lessThanOrEqualTo(50));
    });

    test('a cropped page still exports to a PDF', () async {
      final path = await makeNoisyPng('page.png', w: 200, h: 200);
      final src = im.decodePng(await File(path).readAsBytes())!;
      final cropped =
          ImgEngine.cropRotate(src, const Rect.fromLTRB(0.1, 0.1, 0.9, 0.9));
      final out = File(pp.join(tmp.path, 'cropped.jpg'));
      await out.writeAsBytes(im.encodeJpg(cropped));

      final bytes = await ImgEngine.buildPdf([out.path]);
      expect(bytes.length, greaterThan(100));
    });
  });

  group('pdf tools', () {
    test('merge joins page counts in order', () async {
      final a = await item(await makePdf('a.pdf', 2));
      final b = await item(await makePdf('b.pdf', 3));
      final out = await PdfEngine.toolMerge(call([a, b], {}));

      expect(await pdfPages(out.first), 5);
    });

    test('merge accepts images as pages too', () async {
      final a = await item(await makePdf('m.pdf', 1));
      final b = await item(await makePng('m.png'));
      final out = await PdfEngine.toolMerge(call([a, b], {}));

      expect(await pdfPages(out.first), 2);
    });

    test('split every page yields one file per page', () async {
      final a = await item(await makePdf('s.pdf', 4));
      final out = await PdfEngine.toolSplit(call([a], {'mode': 'every'}));

      expect(out, hasLength(4));
      for (final p in out) {
        expect(await pdfPages(p), 1);
      }
    });

    test('split into chunks of 2', () async {
      final a = await item(await makePdf('s2.pdf', 5));
      final out =
          await PdfEngine.toolSplit(call([a], {'mode': 'chunks', 'chunk': 2}));

      expect(out, hasLength(3));
      expect(await pdfPages(out[0]), 2);
      expect(await pdfPages(out[2]), 1);
    });

    test('extract keeps only the listed pages', () async {
      final a = await item(await makePdf('e.pdf', 6));
      final out = await PdfEngine.toolSelectPages(
          call([a], {'action': 'extract', 'pages': '2-4'}));

      expect(await pdfPages(out.first), 3);
    });

    test('delete removes the listed pages', () async {
      final a = await item(await makePdf('d.pdf', 6));
      final out = await PdfEngine.toolSelectPages(
          call([a], {'action': 'delete', 'pages': '1,2'}));

      expect(await pdfPages(out.first), 4);
    });

    test('deleting every page is refused rather than writing an empty file',
        () async {
      final a = await item(await makePdf('d2.pdf', 2));
      expect(
        () => PdfEngine.toolSelectPages(
            call([a], {'action': 'delete', 'pages': '1-2'})),
        throwsA(isA<Exception>()),
      );
    });

    test('rotate writes a file that still opens', () async {
      final a = await item(await makePdf('rot.pdf', 2));
      final out =
          await PdfEngine.toolRotate(call([a], {'angle': '90', 'pages': ''}));

      expect(await pdfPages(out.first), 2);
    });

    test('watermark and page numbers keep the page count', () async {
      final a = await item(await makePdf('w.pdf', 3));
      final marked = await PdfEngine.toolWatermark(call([a], {
        'text': 'DRAFT',
        'size': 40,
        'color': '#ff0000',
        'opacity': 0.2,
        'diagonal': true,
      }));
      expect(await pdfPages(marked.first), 3);

      final numbered = await PdfEngine.toolPageNumbers(call([a], {
        'format': '{n} / {total}',
        'position': 'bottom-center',
        'size': 10,
      }));
      expect(await pdfPages(numbered.first), 3);
    });

    test('protect then unlock round-trips', () async {
      final a = await item(await makePdf('lock.pdf', 2));
      final locked =
          await PdfEngine.toolProtect(call([a], {'password': 'hunter2'}));

      // The locked file must refuse to open without the password.
      expect(
        () => sf.PdfDocument(inputBytes: File(locked.first).readAsBytesSync()),
        throwsA(anything),
      );

      final lockedItem = await item(locked.first);
      final opened = await PdfEngine.toolUnlock(
          call([lockedItem], {'password': 'hunter2'}));
      expect(await pdfPages(opened.first), 2);
    });

    test('protect with no password is refused', () async {
      final a = await item(await makePdf('np.pdf', 1));
      expect(() => PdfEngine.toolProtect(call([a], {'password': ''})),
          throwsA(isA<Exception>()));
    });

    test('pdf to text recovers the words on the page', () async {
      final a = await item(await makePdf('txt.pdf', 2));
      final out = await PdfEngine.pdfToText(a, 'txt', call([a], {}));

      final text = await File(out.first).readAsString();
      expect(text, contains('Page 1'));
      expect(text, contains('Page 2'));
    });

    test('compressing at a light level still opens', () async {
      final a = await item(await makePdf('z.pdf', 2));
      final out = await PdfEngine.toolCompress(call([a], {'level': 'medium'}));
      expect(await pdfPages(out.first), 2);
    });
  });

  group('tables', () {
    Future<String> makeCsv(String name, String body) async {
      final f = File(pp.join(tmp.path, name));
      await f.writeAsString(body);
      return f.path;
    }

    test('csv to json keeps headers and rows', () async {
      final src = await item(
          await makeCsv('t.csv', 'name,qty\r\napples,3\r\npears,5\r\n'));
      final out = await DataEngine.convertTable(src, 'json', call([src], {}));

      final decoded = jsonDecode(await File(out.first).readAsString()) as List;
      expect(decoded, hasLength(2));
      expect(decoded.first, {'name': 'apples', 'qty': '3'});
    });

    test('csv to xlsx can be read back', () async {
      final src =
          await item(await makeCsv('x.csv', 'a,b\r\n1,2\r\n3,4\r\n'));
      final out = await DataEngine.convertTable(src, 'xlsx', call([src], {}));

      final tables = await DataEngine.read(out.first);
      expect(tables.first.header, ['a', 'b']);
      expect(tables.first.rows, [
        ['1', '2'],
        ['3', '4'],
      ]);
    });

    test('csv to markdown escapes pipes', () async {
      final src = await item(await makeCsv('p.csv', 'a,b\r\n1,"x|y"\r\n'));
      final out = await DataEngine.convertTable(src, 'md', call([src], {}));

      final md = await File(out.first).readAsString();
      expect(md, contains('| a | b |'));
      expect(md, contains(r'x\|y'));
    });

    test('csv to sql quotes values safely', () async {
      final src = await item(await makeCsv('q.csv', "a\r\nO'Brien\r\n"));
      final out = await DataEngine.convertTable(src, 'sql', call([src], {}));

      final sql = await File(out.first).readAsString();
      expect(sql, contains("O''Brien"));
    });

    test('merging spreadsheets stacks rows and tags the source', () async {
      final a = await item(await makeCsv('m1.csv', 'a,b\r\n1,2\r\n'));
      final b = await item(await makeCsv('m2.csv', 'a,b\r\n3,4\r\n'));
      final out = await DataEngine.toolMerge(
          call([a, b], {'out_fmt': 'csv', 'add_source': true}));

      final table = (await DataEngine.read(out.first)).first;
      expect(table.header, contains('source'));
      expect(table.rows, hasLength(2));
    });

    test('a table becomes a PDF', () async {
      final src = await item(await makeCsv('pdf.csv', 'a,b\r\n1,2\r\n'));
      final out = await DataEngine.tableToPdf(src, 'pdf', call([src], {}));
      expect(await pdfPages(out.first), greaterThanOrEqualTo(1));
    });
  });

  group('documents', () {
    Future<FileItem> write(String name, String body) async {
      final f = File(pp.join(tmp.path, name));
      await f.writeAsString(body);
      return item(f.path);
    }

    test('markdown to html', () async {
      final src = await write('a.md', '# Hi\n\nSome **bold**.');
      final out = await DocEngine.convertText(src, 'html', call([src], {}));

      final html = await File(out.first).readAsString();
      expect(html, contains('<h1>Hi</h1>'));
      expect(html, contains('<strong>bold</strong>'));
    });

    test('text to pdf produces a readable page', () async {
      final src = await write('a.txt', 'Hello there\n\nSecond paragraph.');
      final out = await DocEngine.textToPdf(src, 'pdf', call([src], {}));

      expect(await pdfPages(out.first), greaterThanOrEqualTo(1));
      final pdf = await item(out.first);
      final back = await PdfEngine.pdfToText(pdf, 'txt', call([pdf], {}));
      final text = await File(back.first).readAsString();
      // Whole lines, not one word per line.
      expect(text, contains('Hello there'));
      expect(text, contains('Second paragraph.'));
    });

    test('text to docx can be read back', () async {
      final src = await write('b.txt', 'First para.\n\nSecond para.');
      final out = await DocEngine.convertText(src, 'docx', call([src], {}));

      final paras = await DocEngine.docxParagraphs(out.first);
      expect(paras.join('\n'), contains('First para.'));
      expect(paras.join('\n'), contains('Second para.'));
    });

    test('html to text drops the markup', () async {
      final src = await write('c.html', '<p>Alpha</p><p>Beta</p>');
      final out = await DocEngine.convertText(src, 'txt', call([src], {}));

      final text = await File(out.first).readAsString();
      expect(text, contains('Alpha'));
      expect(text, isNot(contains('<p>')));
    });
  });

  group('routing', () {
    test('a multi-step route writes only the final file to the output dir',
        () async {
      final src = await item(await makePdf('route.pdf', 1));
      // pdf -> docx is a single registered edge; prove the runner works.
      final out = await runRoute(src, 'docx', call([src], {}));

      expect(out, hasLength(1));
      expect(out.first, endsWith('.docx'));
      expect(File(out.first).existsSync(), isTrue);
      expect(pp.dirname(out.first), tmp.path);
    });

    test('an impossible route fails with a clear message', () async {
      final src = await item(await makePng('no.png'));
      expect(
        () => runRoute(src, 'mp3', call([src], {})),
        throwsA(predicate(
            (e) => e.toString().contains('No way to turn .png into .mp3'))),
      );
    });
  });

  group('output naming', () {
    test('existing files are never overwritten', () async {
      final a = Fs.uniq(tmp.path, 'same.txt')..writeAsStringSync('1');
      final b = Fs.uniq(tmp.path, 'same.txt')..writeAsStringSync('2');

      expect(pp.basename(a.path), 'same.txt');
      expect(pp.basename(b.path), 'same (2).txt');
      expect(a.readAsStringSync(), '1');
    });
  });
}
