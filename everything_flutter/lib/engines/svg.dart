/// SVG input. Rasterised through Flutter's own vector renderer, so no native
/// helper is needed. (The desktop build's raster-to-SVG tracing has no
/// pure-Dart equivalent and is not offered here.)
library;
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter_svg/flutter_svg.dart';
import 'package:image/image.dart' as im;

import '../core/fs.dart';
import '../core/models.dart';
import 'img.dart';

class SvgEngine {
  /// Render an .svg to a Dart image at [scale]x its intrinsic size.
  static Future<im.Image> render(String path, {double scale = 2}) async {
    final raw = await File(path).readAsString();
    final info = await vg.loadPicture(SvgStringLoader(raw), null);
    final w = (info.size.width * scale).round().clamp(1, 10000);
    final h = (info.size.height * scale).round().clamp(1, 10000);

    final recorder = ui.PictureRecorder();
    final canvas = ui.Canvas(recorder);
    canvas.drawColor(const ui.Color(0x00000000), ui.BlendMode.src);
    canvas.scale(scale);
    canvas.drawPicture(info.picture);
    final picture = recorder.endRecording();
    final image = await picture.toImage(w, h);
    final data = await image.toByteData(format: ui.ImageByteFormat.rawRgba);
    picture.dispose();
    info.picture.dispose();
    image.dispose();
    if (data == null) throw Exception('Could not rasterise that SVG');

    return im.Image.fromBytes(
      width: w,
      height: h,
      bytes: data.buffer,
      bytesOffset: data.offsetInBytes,
      numChannels: 4,
      order: im.ChannelOrder.rgba,
    );
  }

  static Future<List<String>> svgToRaster(
      FileItem f, String target, ToolCall c) async {
    c.progress(0.4, 'Rendering ${f.name}');
    final image = await render(f.path);
    final out = Fs.uniq(c.outDir, '${Fs.safeStem(f.name)}.$target');
    await out.writeAsBytes(
        await ImgEngine.encode(image, target, quality: c.intP('quality', 90)));
    return [out.path];
  }

  static Future<List<String>> svgToPdf(
      FileItem f, String target, ToolCall c) async {
    c.progress(0.4, 'Rendering ${f.name}');
    final image = await render(f.path);
    final scratch = Fs.scratch();
    final tmp = File('${scratch.path}/page.png');
    await tmp.writeAsBytes(im.encodePng(image));
    final out = Fs.uniq(c.outDir, '${Fs.safeStem(f.name)}.pdf');
    await out.writeAsBytes(await ImgEngine.buildPdf([tmp.path]));
    await scratch.delete(recursive: true).catchError((_) => scratch);
    return [out.path];
  }
}
