/// Size-targeted compression: the "How small?" controls really land under the
/// budget. Covers the pure-Dart paths; video/audio use Android's encoders and
/// can only run on a device.
library;

import 'dart:io';
import 'dart:typed_data';

import 'package:archive/archive.dart';
import 'package:everything_converter/core/fs.dart';
import 'package:everything_converter/core/models.dart';
import 'package:everything_converter/core/shrink.dart';
import 'package:everything_converter/engines/img.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as im;
import 'package:path/path.dart' as pp;

late Directory tmp;

ToolCall call(List<FileItem> files, Map<String, Object?> params, [List<String>? notes]) =>
    ToolCall(
      files: files,
      params: params,
      outDir: tmp.path,
      progress: (_, _) {},
      isCancelled: () => false,
      note: (m) => notes?.add(m),
    );

Future<FileItem> item(String path) async => FileItem(
      path: path,
      name: pp.basename(path),
      ext: FileItem.extOf(path),
      size: await File(path).length(),
    );

/// A photo-ish image: gradients plus noise, so quality settings matter.
im.Image photo(int w, int h) {
  final image = im.Image(width: w, height: h);
  var seed = 3;
  for (var y = 0; y < h; y++) {
    for (var x = 0; x < w; x++) {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      final n = seed % 50;
      image.setPixelRgb(x, y, (x + n) % 256, (y + n) % 256, (x + y + n) % 256);
    }
  }
  return image;
}

Future<String> write(String name, List<int> bytes) async {
  final f = File(pp.join(tmp.path, 'in', name));
  await f.create(recursive: true);
  await f.writeAsBytes(bytes);
  return f.path;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('ec_shrink');
    Fs.initWith(root: tmp);
  });

  tearDown(() {
    try {
      tmp.deleteSync(recursive: true);
    } catch (_) {}
  });

  group('budget', () {
    test('percent and target sizes', () {
      expect(Shrink.budget(1000, call([], {'size_mode': 'percent', 'reduce_pct': 30})), 700);
      expect(
          Shrink.budget(1, call([], {'size_mode': 'target', 'target_size': 1.5, 'target_unit': 'MB'})),
          (1.5 * 1024 * 1024).floor());
      expect(Shrink.budget(1000, call([], {'size_mode': 'quality'})), isNull);
      expect(Shrink.budget(1000, call([], {})), isNull);
      expect(() => Shrink.budget(1, call([], {'size_mode': 'target', 'target_size': 0})),
          throwsException);
    });
  });

  group('images', () {
    test('a JPEG lands under a typed-in KB target', () async {
      final src = await item(await write('p.jpg', im.encodeJpg(photo(900, 600), quality: 95)));
      final notes = <String>[];
      final out = await ImgEngine.toolCompress(call(
          [src], {'size_mode': 'target', 'target_size': 40, 'target_unit': 'KB', 'format': 'keep'}, notes));
      expect(await File(out.single).length(), lessThanOrEqualTo(40 * 1024));
      expect(notes.single, contains('→'));
    });

    test('a PNG shrinks by the requested percentage', () async {
      final src = await item(await write('p.png', im.encodePng(photo(500, 400))));
      final out = await ImgEngine.toolCompress(
          call([src], {'size_mode': 'percent', 'reduce_pct': 60, 'format': 'keep'}));
      expect(await File(out.single).length(), lessThanOrEqualTo((src.size * 0.4).floor()));
      expect(im.decodePng(await File(out.single).readAsBytes()), isNotNull);
    });

    test('a file already under the target is copied, not re-encoded', () async {
      final src = await item(await write('small.png', im.encodePng(im.Image(width: 10, height: 10))));
      final notes = <String>[];
      final out = await ImgEngine.toolCompress(
          call([src], {'size_mode': 'target', 'target_size': 1, 'target_unit': 'MB'}, notes));
      expect(await File(out.single).readAsBytes(), await File(src.path).readAsBytes());
      expect(notes.single, contains('copied unchanged'));
    });
  });

  group('documents & anything else', () {
    test('an Office file shrinks via its pictures and stays a valid zip', () async {
      final archive = Archive()
        ..addFile(ArchiveFile.string('mimetype', 'application/vnd.oasis.opendocument.text'))
        ..addFile(ArchiveFile.string('content.xml', '<doc/>'));
      final pic = im.encodeJpg(photo(1200, 800), quality: 95);
      archive.addFile(ArchiveFile('Pictures/a.jpg', pic.length, pic));
      final src = await item(await write('d.odt', ZipEncoder().encode(archive)!));

      final out = await Shrink.toolCompressOffice(
          call([src], {'size_mode': 'percent', 'reduce_pct': 50}));
      final bytes = await File(out.single).readAsBytes();
      expect(bytes.length, lessThanOrEqualTo(src.size ~/ 2));
      final back = ZipDecoder().decodeBytes(bytes);
      expect(back.files.first.name, 'mimetype');
      expect(im.decodeJpg(Uint8List.fromList(back.findFile('Pictures/a.jpg')!.content as List<int>)),
          isNotNull);
    });

    test('Compress anything zips a text file', () async {
      final src = await item(await write('notes.txt', ('hello world\n' * 5000).codeUnits));
      final out = await Shrink.toolCompressAny(
          call([src], {'size_mode': 'percent', 'reduce_pct': 50}));
      expect(out.single, endsWith('notes.txt.zip'));
      expect(await File(out.single).length(), lessThan(src.size ~/ 2));
    });

    test('Compress anything routes a photo to the image engine', () async {
      final src = await item(await write('p.jpg', im.encodeJpg(photo(800, 600), quality: 95)));
      final out = await Shrink.toolCompressAny(
          call([src], {'size_mode': 'target', 'target_size': 30, 'target_unit': 'KB'}));
      expect(out.single, endsWith('.jpg'));
      expect(await File(out.single).length(), lessThanOrEqualTo(30 * 1024));
    });
  });
}
