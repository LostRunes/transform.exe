/// scanner.exe — the Android-only addition: snap pages with the camera or pull
/// them in from the gallery, tidy them up, and export one PDF. Everything is
/// processed on-device; no image ever leaves the phone.
library;
import 'dart:io';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:image/image.dart' as im;
import 'package:path/path.dart' as pp;

import '../core/app_state.dart';
import '../core/fs.dart';
import '../core/jobs.dart';
import '../core/models.dart';
import '../core/theme.dart';
import '../engines/img.dart';
import '../widgets/mascot.dart';
import '../widgets/params_form.dart';
import '../widgets/pickers.dart';
import '../widgets/retro.dart';
import 'crop_view.dart';
import '../widgets/toast.dart';

/// How a captured page is cleaned up before it becomes a PDF page.
enum ScanFilter { original, greyscale, mono }

class ScanView extends StatefulWidget {
  const ScanView({super.key});

  @override
  State<ScanView> createState() => _ScanViewState();
}

class _ScanViewState extends State<ScanView> {
  final app = AppState.instance;
  final Map<String, Object?> _values = {};

  static const _params = [
    ParamDef('page_size', 'Page size', ParamType.select, 'fit', options: [
      ['fit', 'Fit to photo'],
      ['a4', 'A4'],
    ]),
    ParamDef('filter', 'Clean-up', ParamType.select, 'original', options: [
      ['original', 'Original colours'],
      ['greyscale', 'Greyscale'],
      ['mono', 'High contrast (document)'],
    ]),
    ParamDef('margin', 'Margin (pt)', ParamType.number, 0),
    ParamDef('quality', 'JPEG quality', ParamType.range, 92,
        min: 30, max: 100, step: 1),
  ];

  List<FileItem> get _pages => app.scanPages;

  Future<void> _openCamera() async {
    if (!await Fs.ensureCamera()) {
      toast('Camera permission is needed to scan pages', error: true);
      return;
    }
    if (!mounted) return;
    final shots = await Navigator.of(context).push<List<String>>(
      MaterialPageRoute(builder: (_) => const _CameraPage()),
    );
    if (shots == null || shots.isEmpty) return;
    for (final path in shots) {
      _pages.add(await fileItem(path));
    }
    if (mounted) setState(() {});
  }

  /// Open the crop screen for a page, then apply what comes back.
  Future<void> _crop(int index) async {
    final page = _pages[index];
    final result = await Navigator.of(context).push<CropResult>(
      MaterialPageRoute(
        builder: (_) => CropPage(path: page.path, title: 'crop page ${index + 1}'),
      ),
    );
    if (result == null || result.isNoop) return;
    await _rewrite(index, (image) => ImgEngine.cropRotate(
          image,
          result.rect,
          quarterTurns: result.quarterTurns,
        ));
  }

  Future<void> _rotate(int index) =>
      _rewrite(index, (image) => im.copyRotate(image, angle: 90));

  /// Apply [edit] to a page and swap in the result.
  ///
  /// Always writes a *new* file in our own scratch folder: a page can come
  /// straight from the gallery, and editing that in place would alter the
  /// user's original photo. A fresh name also means Flutter's image cache
  /// cannot hand back the stale thumbnail.
  Future<void> _rewrite(
      int index, im.Image Function(im.Image) edit) async {
    final page = _pages[index];
    try {
      final edited = edit(await ImgEngine.decode(page.path));
      final dir = Directory(pp.join(Fs.cacheDir.path, 'scans'))
        ..createSync(recursive: true);
      final dest = File(pp.join(
          dir.path, 'page_${DateTime.now().microsecondsSinceEpoch}.jpg'));
      await dest.writeAsBytes(im.encodeJpg(edited, quality: 95));

      final replacement = await fileItem(dest.path);
      final old = page.path;
      if (!mounted) return;
      setState(() => _pages[index] = replacement);

      // Clean up the previous scratch file, but never the user's own.
      if (pp.isWithin(dir.path, old)) {
        try {
          await File(old).delete();
        } catch (_) {
          // Harmless: the cache gets cleared from the Clean up page anyway.
        }
      }
    } catch (e) {
      failToast(e);
    }
  }

  void _export() {
    final pages = List<FileItem>.from(_pages);
    final filter = switch (_values['filter']) {
      'greyscale' => ScanFilter.greyscale,
      'mono' => ScanFilter.mono,
      _ => ScanFilter.original,
    };
    JobQueue.instance.submit(
      title: 'Scan → PDF (${pages.length} page(s))',
      files: pages,
      params: Map.of(_values),
      outDir: app.outDir,
      body: (call) => buildScanPdf(call, filter),
    );
    toast('Building a PDF from ${pages.length} page(s)');
    app.scanPages.clear();
    app.setJobsOpen(true);
    setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return ViewScroll(
      children: [
        RetroWindow(
          title: 'scan_to_pdf.exe',
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.all(22),
              decoration: BoxDecoration(
                color: s.win2,
                border: Border.all(color: s.inkSoft, width: 2),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Column(
                children: [
                  Text(
                    'snap pages → one pdf ✦',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontFamily: kPixel,
                      fontSize: 17,
                      fontWeight: FontWeight.w700,
                      color: s.titleInk,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    'Take photo after photo without leaving the camera, or pick '
                    'pictures you already have. They stay on this phone.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: s.muted, fontSize: 13),
                  ),
                  const SizedBox(height: 14),
                  Wrap(
                    alignment: WrapAlignment.center,
                    spacing: 10,
                    runSpacing: 10,
                    children: [
                      RetroButton(
                        label: 'Take photos',
                        icon: '📷',
                        size: BtnSize.big,
                        onPressed: _openCamera,
                      ),
                      RetroButton(
                        label: 'From gallery',
                        icon: '🖼',
                        kind: BtnKind.ghost,
                        onPressed: () async {
                          try {
                            final picked = await pickFromGallery();
                            if (picked.isNotEmpty) {
                              setState(() => _pages.addAll(picked));
                            }
                          } catch (e) {
                            failToast(e);
                          }
                        },
                      ),
                      RetroButton(
                        label: 'From files',
                        icon: '📂',
                        kind: BtnKind.ghost,
                        onPressed: () async {
                          try {
                            final picked =
                                await browseFiles(extensions: rasterIn);
                            if (picked.isNotEmpty) {
                              setState(() => _pages.addAll(picked));
                            }
                          } catch (e) {
                            failToast(e);
                          }
                        },
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
        if (_pages.isEmpty)
          const Padding(
            padding: EdgeInsets.only(top: 30),
            child: MascotEmpty(
              text: 'no pages yet~',
              sub: 'Tap "Take photos" and snap away. Each shot becomes a page.',
              width: 120,
            ),
          )
        else ...[
          FileActions(
            count: _pages.length,
            note: 'Drag ⋮⋮ to reorder',
            onClear: () => setState(_pages.clear),
          ),
          ReorderableListView(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            buildDefaultDragHandles: false,
            onReorder: (from, to) => setState(() {
              if (to > from) to -= 1;
              _pages.insert(to, _pages.removeAt(from));
            }),
            children: [
              for (var i = 0; i < _pages.length; i++)
                FileRow(
                  key: ValueKey('${_pages[i].path}#$i'),
                  file: _pages[i],
                  index: i,
                  reorderable: true,
                  onRemove: () => setState(() => _pages.removeAt(i)),
                  onTapThumb: () => _crop(i),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text('p${i + 1}',
                          style: TextStyle(
                              fontFamily: kPixel,
                              fontSize: 11,
                              color: s.titleInk)),
                      const SizedBox(width: 6),
                      IconBtn(
                        glyph: '⬚',
                        tooltip: 'Crop',
                        onPressed: () => _crop(i),
                      ),
                      const SizedBox(width: 4),
                      IconBtn(
                        glyph: '↻',
                        tooltip: 'Rotate 90°',
                        onPressed: () => _rotate(i),
                      ),
                    ],
                  ),
                ),
            ],
          ),
          const SizedBox(height: 14),
          RetroCard(
            title: 'settings.ini',
            child: ParamsForm(params: _params, values: _values),
          ),
          RunBar(
            label: 'Make PDF (${_pages.length} page(s))',
            outDir: app.outDir,
            onRun: _export,
          ),
        ],
      ],
    );
  }
}

/// Apply the chosen clean-up, then lay the pages out as a PDF.
Future<List<String>> buildScanPdf(ToolCall c, ScanFilter filter) async {
  final scratch = Fs.scratch();
  try {
    final prepared = <String>[];
    for (var i = 0; i < c.files.length; i++) {
      if (c.isCancelled()) break;
      c.progress(0.6 * i / c.files.length, 'Cleaning page ${i + 1}');
      final f = c.files[i];
      if (filter == ScanFilter.original) {
        prepared.add(f.path);
        continue;
      }
      var image = im.grayscale(await ImgEngine.decode(f.path));
      if (filter == ScanFilter.mono) {
        // Lift the paper to white and push the ink down, so text stays crisp.
        image = im.adjustColor(image, contrast: 1.8, brightness: 1.08);
      }
      final tmp = File(pp.join(scratch.path, 'page$i.jpg'));
      await tmp.writeAsBytes(im.encodeJpg(image, quality: c.intP('quality', 92)));
      prepared.add(tmp.path);
    }

    c.progress(0.6, 'Laying out ${prepared.length} page(s)');
    final bytes = await ImgEngine.buildPdf(
      prepared,
      pageSize: c.strP('page_size', 'fit'),
      margin: c.dblP('margin', 0),
      quality: c.intP('quality', 92),
      onPage: (i, n) => c.progress(0.6 + 0.35 * i / n, 'Page ${i + 1} of $n'),
      cancelled: c.isCancelled,
    );
    final stamp = DateTime.now();
    final name = 'Scan ${stamp.year}-${_two(stamp.month)}-${_two(stamp.day)} '
        '${_two(stamp.hour)}${_two(stamp.minute)}.pdf';
    final out = Fs.uniq(c.outDir, name);
    await out.writeAsBytes(bytes);
    return [out.path];
  } finally {
    await scratch.delete(recursive: true).catchError((_) => scratch);
  }
}

String _two(int n) => n.toString().padLeft(2, '0');

// ---------------------------------------------------------------- camera

/// Full-screen capture: shoot page after page without leaving the viewfinder.
class _CameraPage extends StatefulWidget {
  const _CameraPage();

  @override
  State<_CameraPage> createState() => _CameraPageState();
}

class _CameraPageState extends State<_CameraPage> {
  CameraController? _controller;
  final List<String> _shots = [];
  String? _error;
  bool _busy = false;
  FlashMode _flash = FlashMode.off;

  @override
  void initState() {
    super.initState();
    _start();
  }

  Future<void> _start() async {
    try {
      final cameras = await availableCameras();
      if (cameras.isEmpty) {
        setState(() => _error = 'This device has no camera.');
        return;
      }
      final back = cameras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.back,
        orElse: () => cameras.first,
      );
      final controller = CameraController(
        back,
        ResolutionPreset.veryHigh,
        enableAudio: false,
      );
      await controller.initialize();
      await controller.setFlashMode(FlashMode.off);
      if (!mounted) {
        await controller.dispose();
        return;
      }
      setState(() => _controller = controller);
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    }
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  Future<void> _shoot() async {
    final c = _controller;
    if (c == null || !c.value.isInitialized || _busy) return;
    setState(() => _busy = true);
    try {
      final shot = await c.takePicture();
      // Move it out of the plugin's temp dir into our own scratch space.
      final dir = Directory(pp.join(Fs.cacheDir.path, 'scans'))
        ..createSync(recursive: true);
      final dest = pp.join(dir.path,
          'page_${DateTime.now().microsecondsSinceEpoch}.jpg');
      await File(shot.path).copy(dest);
      await File(shot.path).delete().catchError((_) => File(shot.path));
      setState(() => _shots.add(dest));
    } catch (e) {
      failToast(e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _toggleFlash() async {
    final c = _controller;
    if (c == null) return;
    final next = _flash == FlashMode.off ? FlashMode.torch : FlashMode.off;
    try {
      await c.setFlashMode(next);
      setState(() => _flash = next);
    } catch (e) {
      failToast(e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    final controller = _controller;

    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: Stack(
          children: [
            Positioned.fill(
              child: _error != null
                  ? Center(
                      child: Padding(
                        padding: const EdgeInsets.all(24),
                        child: Text(_error!,
                            textAlign: TextAlign.center,
                            style: const TextStyle(color: Colors.white)),
                      ),
                    )
                  : controller == null
                      ? const Center(child: RetroSpinner(size: 32))
                      : Center(
                          child: AspectRatio(
                            aspectRatio: 1 / controller.value.aspectRatio,
                            child: CameraPreview(controller),
                          ),
                        ),
            ),
            // top bar: close + flash + counter
            Positioned(
              top: 10,
              left: 10,
              right: 10,
              child: Row(
                children: [
                  _RoundBtn(
                    glyph: '✕',
                    onTap: () => Navigator.of(context).pop(<String>[]),
                  ),
                  const Spacer(),
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 12, vertical: 6),
                    decoration: BoxDecoration(
                      color: s.win,
                      border: Border.all(color: s.ink, width: 2),
                      borderRadius: BorderRadius.circular(99),
                    ),
                    child: Text(
                      '${_shots.length} page${_shots.length == 1 ? '' : 's'}',
                      style: TextStyle(
                          fontFamily: kPixel,
                          fontSize: 12,
                          color: s.titleInk),
                    ),
                  ),
                  const Spacer(),
                  _RoundBtn(
                    glyph: _flash == FlashMode.off ? '🔦' : '💡',
                    onTap: _toggleFlash,
                  ),
                ],
              ),
            ),
            // bottom bar: last shot, shutter, done
            Positioned(
              left: 0,
              right: 0,
              bottom: 16,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                children: [
                  SizedBox(
                    width: 56,
                    height: 56,
                    child: _shots.isEmpty
                        ? const SizedBox.shrink()
                        : Container(
                            decoration: BoxDecoration(
                              border: Border.all(color: s.ink, width: 2),
                              borderRadius: BorderRadius.circular(9),
                            ),
                            clipBehavior: Clip.antiAlias,
                            child: Image.file(File(_shots.last),
                                fit: BoxFit.cover, cacheWidth: 160),
                          ),
                  ),
                  GestureDetector(
                    onTap: _shoot,
                    child: Container(
                      width: 74,
                      height: 74,
                      decoration: BoxDecoration(
                        color: _busy ? s.muted : s.pink,
                        shape: BoxShape.circle,
                        border: Border.all(color: s.ink, width: 3),
                        boxShadow: hardShadow(s.drop, 3),
                      ),
                      child: _busy
                          ? const Padding(
                              padding: EdgeInsets.all(22),
                              child: RetroSpinner(size: 26),
                            )
                          : null,
                    ),
                  ),
                  SizedBox(
                    width: 56,
                    child: RetroButton(
                      label: 'Done',
                      size: BtnSize.sm,
                      onPressed: _shots.isEmpty
                          ? null
                          : () => Navigator.of(context).pop(_shots),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _RoundBtn extends StatelessWidget {
  const _RoundBtn({required this.glyph, required this.onTap});
  final String glyph;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 40,
        height: 40,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: s.win,
          shape: BoxShape.circle,
          border: Border.all(color: s.ink, width: 2),
        ),
        child: Text(glyph, style: const TextStyle(fontSize: 16)),
      ),
    );
  }
}
