/// The conversion graph (any format -> any format via chained steps) and the
/// tool catalogue. Ported from core/registry.py.
library;
import 'dart:collection';
import 'dart:io';

import '../engines/data.dart';
import '../engines/doc.dart';
import '../engines/img.dart';
import '../engines/pdfeng.dart';
import '../engines/svg.dart';
import '../engines/media.dart';
import 'fs.dart';
import 'models.dart';
import 'shrink.dart';

/// One hop of a conversion: read [f], write [target], return the new paths.
typedef ConvertFn = Future<List<String>> Function(
    FileItem f, String target, ToolCall c);

const _aliases = {
  'jpeg': 'jpg',
  'jfif': 'jpg',
  'tif': 'tiff',
  'htm': 'html',
  'markdown': 'md',
  'heif': 'heic',
  'yml': 'yaml',
};

String norm(String ext) {
  final e = ext.toLowerCase().replaceFirst(RegExp(r'^\.'), '');
  return _aliases[e] ?? e;
}

/// edges[src][dst] = fn
final Map<String, Map<String, ConvertFn>> edges = {};

void edge(Iterable<String> srcs, Iterable<String> dsts, ConvertFn fn,
    {bool override = false}) {
  for (final rawS in srcs) {
    final s = norm(rawS);
    for (final rawD in dsts) {
      final d = norm(rawD);
      if (s == d) continue;
      final slot = edges.putIfAbsent(s, () => {});
      if (override || !slot.containsKey(d)) slot[d] = fn;
    }
  }
}

/// Formats the whole app understands, used to classify dropped files.
const docFormats = [
  'pdf', 'docx', 'doc', 'docm', 'rtf', 'odt', 'txt', 'html', 'md',
  'ppt', 'pptx', 'odp',
];
const videoFormats = [
  'mp4', 'mkv', 'mov', 'webm', 'avi', 'flv', 'wmv', 'm4v', 'mpeg', '3gp', 'ts',
];
const audioFormats = [
  'mp3', 'wav', 'flac', 'm4a', 'aac', 'ogg', 'opus', 'wma', 'aiff',
];

var _built = false;

void buildGraph() {
  if (_built) return;
  _built = true;

  // ---------- images ----------
  edge(rasterIn, rasterOut, ImgEngine.rasterToRaster);
  edge(rasterIn, ['pdf'], ImgEngine.rasterToPdf);
  edge(['svg'], rasterOut, SvgEngine.svgToRaster);
  edge(['svg'], ['pdf'], SvgEngine.svgToPdf);

  // ---------- pdf ----------
  edge(['pdf'], ['png', 'jpg', 'webp', 'tiff', 'bmp', 'gif'],
      PdfEngine.pdfToRaster);
  edge(['pdf'], ['txt'], PdfEngine.pdfToText);
  edge(['pdf'], ['html', 'md'], PdfEngine.pdfToMarkup);
  edge(['pdf'], ['docx'], _pdfToDocx);

  // ---------- documents ----------
  edge(['docx', 'docm'], ['txt', 'html', 'md'], DocEngine.convertText);
  edge(['md'], ['html', 'txt', 'docx'], DocEngine.convertText);
  edge(['txt'], ['html', 'md', 'docx'], DocEngine.convertText);
  edge(['html'], ['txt', 'md', 'docx'], DocEngine.convertText);
  edge(['txt', 'md', 'html', 'docx', 'docm'], ['pdf'], DocEngine.textToPdf);

  // ---------- spreadsheets / data ----------
  edge(tableIn, dataOut, DataEngine.convertTable);
  edge(tableIn, ['pdf'], DataEngine.tableToPdf);
}

/// pdf -> docx, via the extracted text.
Future<List<String>> _pdfToDocx(FileItem f, String target, ToolCall c) async {
  c.progress(0.3, 'Reading text from ${f.name}');
  final txt = await PdfEngine.pdfToText(f, 'txt', c);
  final text = await File(txt.first).readAsString();
  await File(txt.first).delete().catchError((_) => File(txt.first));
  final out = Fs.uniq(c.outDir, '${Fs.safeStem(f.name)}.docx');
  await out.writeAsBytes(DocEngine.buildDocx(text.split(RegExp(r'\n\s*\n'))));
  return [out.path];
}

/// Multi-step routes may only pass *through* these formats.
const _hubs = {'pdf', 'html', 'png', 'docx'};

String category(String rawExt) {
  final ext = norm(rawExt);
  if (ext == 'gif') return 'gif';
  if (ext == 'svg' || rasterIn.contains(ext) || rasterOut.contains(ext)) {
    return 'image';
  }
  if (videoFormats.contains(ext)) return 'video';
  if (audioFormats.contains(ext)) return 'audio';
  if (tableIn.contains(ext) ||
      (dataOut.contains(ext) && ext != 'html' && ext != 'md')) {
    return 'data';
  }
  if (docFormats.contains(ext)) return 'doc';
  return 'other';
}

/// Source category -> target categories that make sense.
const _allowedCats = {
  'image': {'image', 'gif', 'doc_pdf'},
  'gif': {'image', 'gif', 'doc_pdf'},
  'doc': {'doc', 'image', 'gif'},
  'data': {'data', 'doc', 'image'},
};

bool _allowed(String src, String dst) {
  final sc = category(src);
  final dc = category(dst);
  final allowed = _allowedCats[sc] ?? const <String>{};
  if (dst == 'pdf' && allowed.contains('doc_pdf')) return true;
  return allowed.contains(dc);
}

class Step {
  Step(this.from, this.to, this.fn);
  final String from;
  final String to;
  final ConvertFn fn;
}

/// BFS from [src] through hub formats. Returns dst -> steps.
Map<String, List<Step>> _search(String src, {int maxHops = 3}) {
  final routes = <String, List<Step>>{};
  final q = Queue<(String, List<Step>)>()..add((src, const []));
  final seen = {src};
  while (q.isNotEmpty) {
    final (node, path) = q.removeFirst();
    if (path.length >= maxHops) continue;
    for (final entry in (edges[node] ?? const {}).entries) {
      if (seen.contains(entry.key)) continue;
      seen.add(entry.key);
      final step = [...path, Step(node, entry.key, entry.value)];
      routes[entry.key] = step;
      if (_hubs.contains(entry.key)) q.add((entry.key, step));
    }
  }
  routes.removeWhere((d, s) => s.length != 1 && !_allowed(src, d));
  return routes;
}

List<Step>? findPath(String srcExt, String dstExt) {
  buildGraph();
  final src = norm(srcExt);
  final dst = norm(dstExt);
  if (src == dst) return null;
  return _search(src)[dst];
}

/// Every format [srcExt] can reach, nearest routes first.
List<String> targetsFor(String srcExt) {
  buildGraph();
  final routes = _search(norm(srcExt));
  final keys = routes.keys.toList();
  keys.sort((a, b) {
    final byHops = routes[a]!.length.compareTo(routes[b]!.length);
    return byHops != 0 ? byHops : a.compareTo(b);
  });
  return keys;
}

/// Run a (possibly multi-step) route, writing intermediates to scratch.
Future<List<String>> runRoute(FileItem f, String target, ToolCall c) async {
  final path = findPath(f.ext, target);
  if (path == null || path.isEmpty) {
    throw Exception('No way to turn .${f.ext} into .$target');
  }
  var current = f;
  final scratch = Fs.scratch();
  try {
    for (var i = 0; i < path.length; i++) {
      if (c.isCancelled()) break;
      final step = path[i];
      final last = i == path.length - 1;
      // Intermediates go to scratch; only the final step writes to the output folder.
      final hop = ToolCall(
        files: [current],
        params: c.params,
        outDir: last ? c.outDir : scratch.path,
        progress: (p, m) => c.progress((i + p) / path.length, m),
        isCancelled: c.isCancelled,
      );
      final produced = await step.fn(current, step.to, hop);
      if (produced.isEmpty) throw Exception('Step ${step.from}→${step.to} produced nothing');
      if (last) return produced;
      // A step that fans out (pdf -> many pages) can't feed a further step.
      final next = File(produced.first);
      current = FileItem(
        path: next.path,
        name: next.uri.pathSegments.last,
        ext: step.to,
        size: await next.length(),
      );
    }
    return [current.path];
  } finally {
    await scratch.delete(recursive: true).catchError((_) => scratch);
  }
}

// ---------------------------------------------------------------- capabilities

/// What this build can actually do. The UI shows these as chips, same as the
/// desktop version — ffmpeg and the Office engines have no Android equivalent.
Map<String, bool> capabilities() => const {
      'images': true,
      'pdf': true,
      'docs': true,
      'sheets': true,
      'heic': true,
      'media': true,
    };

// ---------------------------------------------------------------- tools

const _pagesParam =
    ParamDef('pages', 'Pages (e.g. 1-3, 5, 8-; blank = all)', ParamType.text, '');

final List<ToolDef> tools = [
  // ---- PDF ----
  ToolDef(
    id: 'pdf_merge',
    cat: 'PDF',
    name: 'Merge PDFs',
    icon: '⊕',
    multi: true,
    inputs: ['pdf', ...rasterIn],
    outExt: 'pdf',
    desc: 'Combine files into one PDF in the order listed (drag to reorder). '
        'Images are added as pages.',
    run: PdfEngine.toolMerge,
  ),
  ToolDef(
    id: 'pdf_split',
    cat: 'PDF',
    name: 'Split PDF',
    icon: '✂',
    inputs: ['pdf'],
    desc: 'Split into single pages, fixed-size chunks or custom ranges.',
    params: [
      ParamDef('mode', 'Split mode', ParamType.select, 'every', options: [
        ['every', 'Every page'],
        ['chunks', 'Every N pages'],
        ['ranges', 'Custom ranges'],
      ]),
      ParamDef('chunk', 'N pages per file', ParamType.number, 2,
          showIf: {'mode': 'chunks'}),
      ParamDef('ranges', 'Ranges separated by ; (e.g. 1-3; 4-10; 11-)',
          ParamType.text, '',
          showIf: {'mode': 'ranges'}),
    ],
    run: PdfEngine.toolSplit,
  ),
  ToolDef(
    id: 'pdf_pages',
    cat: 'PDF',
    name: 'Extract / delete / reorder pages',
    icon: '☰',
    inputs: ['pdf'],
    desc: 'Keep, remove or reorder pages. Reorder: list pages in the new '
        'order, e.g. 3,1,2,4-',
    params: [
      ParamDef('action', 'Action', ParamType.select, 'extract', options: [
        ['extract', 'Keep only these / reorder'],
        ['delete', 'Delete these pages'],
      ]),
      ParamDef('pages', 'Pages (e.g. 1-3, 5, 8-)', ParamType.text, ''),
    ],
    run: PdfEngine.toolSelectPages,
  ),
  ToolDef(
    id: 'pdf_rotate',
    cat: 'PDF',
    name: 'Rotate pages',
    icon: '↻',
    inputs: ['pdf'],
    params: [
      ParamDef('angle', 'Angle', ParamType.select, '90', options: [
        ['90', '90° clockwise'],
        ['180', '180°'],
        ['270', '90° counter-clockwise'],
      ]),
      _pagesParam,
    ],
    run: PdfEngine.toolRotate,
  ),
  ToolDef(
    id: 'pdf_compress',
    cat: 'PDF',
    name: 'Compress PDF',
    icon: '⇲',
    inputs: ['pdf'],
    desc: 'Shrink by a percentage or to an exact size, or pick a level.',
    params: [
      ...sizeParams(qualityLabel: 'Pick a compression level'),
      ParamDef('level', 'Compression', ParamType.select, 'medium',
          options: [
            ['low', 'Light (best quality)'],
            ['medium', 'Balanced'],
            ['high', 'Strong'],
            ['extreme', 'Extreme (smallest)'],
          ],
          showIf: qualityMode),
      ParamDef('flatten',
          'If repacking isn\'t enough, flatten pages to images (text stops being selectable)',
          ParamType.checkbox, true,
          showIf: sizedMode),
    ],
    run: PdfEngine.toolCompress,
  ),
  ToolDef(
    id: 'pdf_watermark',
    cat: 'PDF',
    name: 'Watermark',
    icon: '⌘',
    inputs: ['pdf'],
    params: [
      ParamDef('text', 'Text', ParamType.text, 'CONFIDENTIAL'),
      ParamDef('size', 'Font size', ParamType.number, 60),
      ParamDef('color', 'Colour', ParamType.color, '#ff0000'),
      ParamDef('opacity', 'Opacity', ParamType.range, 0.15,
          min: 0.05, max: 1, step: 0.05),
      ParamDef('diagonal', 'Diagonal', ParamType.checkbox, true),
    ],
    run: PdfEngine.toolWatermark,
  ),
  ToolDef(
    id: 'pdf_numbers',
    cat: 'PDF',
    name: 'Add page numbers',
    icon: '#',
    inputs: ['pdf'],
    params: [
      ParamDef('format', 'Format ({n}, {total})', ParamType.text, '{n} / {total}'),
      ParamDef('position', 'Position', ParamType.select, 'bottom-center',
          options: [
            ['bottom-center', 'bottom-center'],
            ['bottom-right', 'bottom-right'],
            ['bottom-left', 'bottom-left'],
            ['top-center', 'top-center'],
            ['top-right', 'top-right'],
            ['top-left', 'top-left'],
          ]),
      ParamDef('size', 'Font size', ParamType.number, 10),
    ],
    run: PdfEngine.toolPageNumbers,
  ),
  ToolDef(
    id: 'pdf_protect',
    cat: 'PDF',
    name: 'Password-protect',
    icon: '🔒',
    inputs: ['pdf'],
    params: [ParamDef('password', 'Password', ParamType.password, '')],
    run: PdfEngine.toolProtect,
  ),
  ToolDef(
    id: 'pdf_unlock',
    cat: 'PDF',
    name: 'Remove password',
    icon: '🔓',
    inputs: ['pdf'],
    params: [ParamDef('password', 'Current password', ParamType.password, '')],
    run: PdfEngine.toolUnlock,
  ),
  ToolDef(
    id: 'pdf_page_images',
    cat: 'PDF',
    name: 'Save pages as images',
    icon: '▣',
    inputs: ['pdf'],
    desc: 'Render each page to a PNG or JPG.',
    params: [
      ParamDef('dpi', 'Resolution (DPI)', ParamType.number, 150),
      _pagesParam,
      ParamDef('format', 'Format', ParamType.select, 'png', options: [
        ['png', 'PNG'],
        ['jpg', 'JPG'],
      ]),
    ],
    run: PdfEngine.toolPageImages,
  ),

  // ---- Images ----
  ToolDef(
    id: 'img_compress',
    cat: 'Image',
    name: 'Compress images',
    icon: '⇲',
    inputs: rasterIn,
    desc: 'Shrink by a percentage or to an exact size (e.g. under 200 KB), or '
        'pick a quality yourself.',
    params: [
      ...sizeParams(qualityLabel: 'Set the quality myself'),
      ParamDef('quality', 'Quality', ParamType.range, 75,
          min: 10, max: 100, step: 1, showIf: qualityMode),
      ParamDef('max_side', 'Max width/height in px (0 = keep)',
          ParamType.number, 0),
      ParamDef('format', 'Output format', ParamType.select, 'keep', options: [
        ['keep', 'Same as input'],
        ['jpg', 'JPG'],
        ['webp', 'WebP (smaller)'],
        ['png', 'PNG'],
        ['heic', 'HEIC'],
      ]),
      ParamDef('png_colors', 'PNG palette colours (0 = full colour)',
          ParamType.number, 0,
          showIf: {'format': 'png'}),
    ],
    run: ImgEngine.toolCompress,
  ),
  ToolDef(
    id: 'img_resize',
    cat: 'Image',
    name: 'Resize images',
    icon: '⤢',
    inputs: rasterIn,
    params: [
      ParamDef('mode', 'Resize by', ParamType.select, 'percent', options: [
        ['percent', 'Percentage'],
        ['pixels', 'Exact pixels'],
      ]),
      ParamDef('percent', 'Percent', ParamType.range, 50,
          min: 5, max: 400, step: 5, showIf: {'mode': 'percent'}),
      ParamDef('width', 'Width px (blank = auto)', ParamType.number, '',
          showIf: {'mode': 'pixels'}),
      ParamDef('height', 'Height px (blank = auto)', ParamType.number, '',
          showIf: {'mode': 'pixels'}),
      ParamDef('keep_ratio', 'Keep aspect ratio (fit inside)',
          ParamType.checkbox, true,
          showIf: {'mode': 'pixels'}),
    ],
    run: ImgEngine.toolResize,
  ),
  ToolDef(
    id: 'img_edit',
    cat: 'Image',
    name: 'Rotate / flip / grayscale',
    icon: '↻',
    inputs: rasterIn,
    params: [
      ParamDef('rotate', 'Rotate', ParamType.select, '0', options: [
        ['0', 'None'],
        ['90', '90° clockwise'],
        ['180', '180°'],
        ['270', '90° counter-clockwise'],
      ]),
      ParamDef('flip_h', 'Flip horizontally', ParamType.checkbox, false),
      ParamDef('flip_v', 'Flip vertically', ParamType.checkbox, false),
      ParamDef('grayscale', 'Black & white', ParamType.checkbox, false),
      ParamDef('strip_metadata', 'Strip EXIF/GPS metadata',
          ParamType.checkbox, true),
    ],
    run: ImgEngine.toolTransform,
  ),
  ToolDef(
    id: 'img_to_pdf',
    cat: 'Image',
    name: 'Images → one PDF',
    icon: '⊕',
    multi: true,
    inputs: rasterIn,
    outExt: 'pdf',
    desc: 'Every image becomes a page, in the listed order.',
    params: [
      ParamDef('page_size', 'Page size', ParamType.select, 'fit', options: [
        ['fit', 'Fit to image'],
        ['a4', 'A4'],
      ]),
      ParamDef('margin', 'Margin (pt)', ParamType.number, 0),
      ParamDef('quality', 'JPEG quality', ParamType.range, 92,
          min: 30, max: 100, step: 1),
    ],
    run: ImgEngine.toolImagesToPdf,
  ),

  // ---- Video & audio: the phone's own encoders, no FFmpeg ----
  ToolDef(
    id: 'vid_compress',
    cat: 'Video & Audio',
    name: 'Compress video',
    icon: '⇲',
    inputs: MediaEngine.videoIn,
    desc: 'Shrink by a percentage or to an exact size, using the phone\'s '
        'hardware encoder. Saves as MP4.',
    params: [
      ...sizeParams(qualityLabel: 'Set the quality myself'),
      ParamDef('quality', 'Quality', ParamType.range, 60,
          min: 10, max: 100, step: 5, showIf: qualityMode),
      ParamDef('max_height', 'Max resolution', ParamType.select, '0', options: [
        ['0', 'Keep'],
        ['1080', '1080p'],
        ['720', '720p'],
        ['480', '480p'],
        ['360', '360p'],
      ]),
      ParamDef('auto_res', 'Lower the resolution if the size is tight (looks far better)',
          ParamType.checkbox, true,
          showIf: sizedMode),
      ParamDef('codec', 'Codec', ParamType.select, 'h264', options: [
        ['h264', 'H.264 (plays everywhere)'],
        ['h265', 'H.265 (smaller, newer phones)'],
      ]),
    ],
    run: MediaEngine.toolCompressVideo,
  ),
  ToolDef(
    id: 'aud_compress',
    cat: 'Video & Audio',
    name: 'Compress audio',
    icon: '♫',
    inputs: MediaEngine.audioIn,
    desc: 'Shrink songs, voice notes and podcasts by a percentage or to an exact '
        'size. Saves as M4A (AAC).',
    params: [
      ...sizeParams(qualityLabel: 'Pick a bitrate'),
      ParamDef('bitrate', 'Bitrate', ParamType.select, '96',
          options: [
            for (final b in ['32', '48', '64', '96', '128', '160', '192']) [b, '$b kbps'],
          ],
          showIf: qualityMode),
      ParamDef('channels', 'Channels', ParamType.select, 'auto', options: [
        ['auto', 'Automatic (mono when the size is tight)'],
        ['stereo', 'Keep stereo'],
        ['mono', 'Mono (half the data)'],
      ]),
      ParamDef('sample_rate', 'Sample rate', ParamType.select, '0', options: [
        ['0', 'Automatic'],
        ['48000', '48 kHz'],
        ['44100', '44.1 kHz (CD)'],
        ['32000', '32 kHz'],
        ['22050', '22 kHz (voice)'],
        ['16000', '16 kHz (calls)'],
      ]),
    ],
    run: MediaEngine.toolCompressAudio,
  ),
  ToolDef(
    id: 'vid_unavailable',
    cat: 'Video & Audio',
    name: 'Trim, join & convert',
    icon: '▶',
    inputs: [...videoFormats, ...audioFormats],
    desc: 'Trimming, joining and format changes need FFmpeg, which this build '
        'does not ship. Compression above uses the phone\'s own encoders.',
    available: false,
    unavailableNote: 'FFmpeg is not bundled in this build.',
    run: _unavailable,
  ),

  // ---- Compress anything ----
  ToolDef(
    id: 'compress_any',
    cat: 'Compress',
    name: 'Compress anything',
    icon: '⇲',
    inputs: const ['*'],
    desc: 'Photos, videos, audio, PDFs, Word/Excel/PowerPoint or anything else: '
        'each is squeezed with the right engine; other files are zipped.',
    params: [
      ...sizeParams(),
      const ParamDef('flatten', 'PDFs: flatten pages to images if needed',
          ParamType.checkbox, true),
    ],
    run: Shrink.toolCompressAny,
  ),
  ToolDef(
    id: 'doc_compress',
    cat: 'Compress',
    name: 'Compress Office documents',
    icon: '▤',
    inputs: Shrink.office,
    desc: 'Word, Excel, PowerPoint and OpenDocument files: recompresses the '
        'pictures inside and repacks the file.',
    params: sizeParams(),
    run: Shrink.toolCompressOffice,
  ),

  // ---- Data ----
  ToolDef(
    id: 'data_merge',
    cat: 'Data',
    name: 'Merge spreadsheets',
    icon: '⊕',
    multi: true,
    inputs: tableIn,
    outExt: 'xlsx',
    desc: 'Stack rows from several CSV/Excel/JSON files into one sheet.',
    params: [
      ParamDef('out_fmt', 'Save as', ParamType.select, 'xlsx', options: [
        ['xlsx', 'Excel'],
        ['csv', 'CSV'],
        ['json', 'JSON'],
      ]),
      ParamDef('add_source', "Add a 'source' column", ParamType.checkbox, true),
    ],
    run: DataEngine.toolMerge,
  ),
];

Future<List<String>> _unavailable(ToolCall c) async =>
    throw Exception('This tool is not available in the Android build.');

ToolDef? toolById(String id) {
  for (final t in tools) {
    if (t.id == id) return t;
  }
  return null;
}

/// Params for the Convert tab, shown depending on the chosen target.
const convertParams = <String, List<ParamDef>>{
  'image': [
    ParamDef('quality', 'Quality', ParamType.range, 90,
        min: 10, max: 100, step: 1),
  ],
  'from_pdf_image': [
    ParamDef('dpi', 'Resolution (DPI)', ParamType.number, 150),
    _pagesParam,
  ],
};

/// Sensible default target for each input type (DEFAULT_TARGET in app.js).
const defaultTarget = {
  'jpg': 'png', 'png': 'jpg', 'heic': 'jpg', 'webp': 'png', 'bmp': 'png',
  'tiff': 'jpg', 'gif': 'png', 'svg': 'png', 'ico': 'png',
  'pdf': 'docx', 'docx': 'pdf', 'md': 'pdf', 'html': 'pdf', 'txt': 'pdf',
  'xlsx': 'csv', 'xls': 'xlsx', 'csv': 'xlsx', 'tsv': 'csv', 'json': 'csv',
  'xml': 'csv',
};
