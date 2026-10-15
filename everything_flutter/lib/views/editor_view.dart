/// paint_a_pdf.exe — annotate a PDF: text, boxes, ellipses, lines, arrows,
/// freehand, highlighter and whiteout. Pages are rendered with PDFium and the
/// marks are stamped back in with Syncfusion, always to a new copy.
///
/// The desktop build can also rewrite a PDF's *existing* text; that relies on
/// PyMuPDF's text-span editing and has no pure-Dart equivalent, so it is not
/// offered here.
library;
import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:syncfusion_flutter_pdf/pdf.dart' as sf;

import '../core/app_state.dart';
import '../core/fs.dart';
import '../core/jobs.dart';
import '../core/models.dart';
import '../core/theme.dart';
import '../engines/pdfeng.dart';
import '../widgets/mascot.dart';
import '../widgets/pickers.dart';
import '../widgets/retro.dart';
import '../widgets/toast.dart';

enum EdTool { text, rect, ellipse, line, arrow, freehand, highlight, whiteout }

/// One mark on one page. Points are 0..1 fractions of the page box, so they
/// survive any zoom level and map straight onto PDF points when saving.
class Mark {
  Mark({
    required this.tool,
    required this.color,
    required this.width,
    this.points = const [],
    this.text = '',
    this.fontSize = 14,
  });

  final EdTool tool;
  final Color color;
  final double width;
  final List<Offset> points;
  final String text;
  final double fontSize;
}

class EditorView extends StatefulWidget {
  const EditorView({super.key});

  @override
  State<EditorView> createState() => _EditorViewState();
}

class _EditorViewState extends State<EditorView> {
  final app = AppState.instance;

  FileItem? _file;
  int _pageCount = 0;
  int _page = 0;
  Uint8List? _pageImage;
  bool _loading = false;

  /// page index -> its marks
  final Map<int, List<Mark>> _marks = {};

  EdTool _tool = EdTool.freehand;
  Color _color = const Color(0xFFEC2B4B);
  double _stroke = 3;
  double _fontSize = 16;

  List<Offset>? _drawing;

  static const _palette = [
    Color(0xFFEC2B4B), Color(0xFFFF7A00), Color(0xFFFFD400),
    Color(0xFF2BB673), Color(0xFF2B7BD4), Color(0xFF8D8FF2),
    Color(0xFF000000), Color(0xFFFFFFFF),
  ];

  Future<void> _open(FileItem f) async {
    setState(() {
      _file = f;
      _loading = true;
      _marks.clear();
      _page = 0;
    });
    try {
      _pageCount = await PdfEngine.pageCount(f.path);
      await _renderPage();
    } catch (e) {
      failToast(e);
      setState(() {
        _file = null;
        _loading = false;
      });
    }
  }

  Future<void> _renderPage() async {
    setState(() => _loading = true);
    try {
      final pages = await PdfEngine.renderToImages(
        _file!.path,
        dpi: 150,
        pages: '${_page + 1}',
      );
      if (pages.isEmpty) throw Exception('Could not render that page');
      final bytes = await PdfEngine.thumbnailBytes(pages.first);
      if (mounted) {
        setState(() {
          _pageImage = bytes;
          _loading = false;
        });
      }
    } catch (e) {
      failToast(e);
      if (mounted) setState(() => _loading = false);
    }
  }

  void _undo() {
    final list = _marks[_page];
    if (list == null || list.isEmpty) return;
    setState(() => list.removeLast());
  }

  Future<void> _save() async {
    if (_file == null) return;
    if (_marks.values.every((m) => m.isEmpty)) {
      toast('Nothing to save yet — draw something first');
      return;
    }
    // Run it as a job like every other piece of work, so the result shows up
    // in the jobs window with Open / Save / Share.
    final source = _file!;
    final marks = {
      for (final e in _marks.entries) e.key: List<Mark>.from(e.value),
    };
    JobQueue.instance.submit(
      title: 'Edit ${source.name}',
      files: [source],
      params: const {},
      outDir: app.outDir,
      body: (call) async {
        call.progress(0.2, 'Stamping marks');
        final doc = sf.PdfDocument(
            inputBytes: await File(source.path).readAsBytes());
        for (final entry in marks.entries) {
          if (entry.key >= doc.pages.count) continue;
          final page = doc.pages[entry.key];
          final box = page.getClientSize();
          for (final mark in entry.value) {
            _stamp(page.graphics, mark, box);
          }
        }
        call.progress(0.7, 'Writing a copy');
        final out =
            Fs.uniq(call.outDir, '${Fs.safeStem(source.name)} edited.pdf');
        await out.writeAsBytes(await doc.save());
        doc.dispose();
        return [out.path];
      },
    );
    toast('Saving a copy — see the jobs window');
    app.setJobsOpen(true);
  }

  /// Draw one mark onto the real PDF page, converting fractions to points.
  void _stamp(sf.PdfGraphics g, Mark m, Size box) {
    sf.PdfColor col(Color c) =>
        sf.PdfColor((c.r * 255).round(), (c.g * 255).round(), (c.b * 255).round());
    Offset pt(Offset f) => Offset(f.dx * box.width, f.dy * box.height);

    final pen = sf.PdfPen(col(m.color), width: m.width);
    final brush = sf.PdfSolidBrush(col(m.color));
    final pts = m.points.map(pt).toList();

    switch (m.tool) {
      case EdTool.text:
        if (pts.isEmpty || m.text.isEmpty) return;
        final font = sf.PdfStandardFont(sf.PdfFontFamily.helvetica, m.fontSize);
        g.drawString(m.text, font,
            brush: brush,
            bounds: Rect.fromLTWH(pts.first.dx, pts.first.dy,
                box.width - pts.first.dx, m.fontSize * 2));
      case EdTool.rect:
        if (pts.length < 2) return;
        g.drawRectangle(pen: pen, bounds: Rect.fromPoints(pts.first, pts.last));
      case EdTool.ellipse:
        if (pts.length < 2) return;
        g.drawEllipse(Rect.fromPoints(pts.first, pts.last), pen: pen);
      case EdTool.line:
        if (pts.length < 2) return;
        g.drawLine(pen, pts.first, pts.last);
      case EdTool.arrow:
        if (pts.length < 2) return;
        g.drawLine(pen, pts.first, pts.last);
        _arrowHead(g, pen, pts.first, pts.last, m.width);
      case EdTool.freehand:
        for (var i = 1; i < pts.length; i++) {
          g.drawLine(pen, pts[i - 1], pts[i]);
        }
      case EdTool.highlight:
        if (pts.length < 2) return;
        final state = g.save();
        g.setTransparency(0.35);
        g.drawRectangle(
            brush: brush, bounds: Rect.fromPoints(pts.first, pts.last));
        g.restore(state);
      case EdTool.whiteout:
        if (pts.length < 2) return;
        g.drawRectangle(
          brush: sf.PdfSolidBrush(sf.PdfColor(255, 255, 255)),
          bounds: Rect.fromPoints(pts.first, pts.last),
        );
    }
  }

  void _arrowHead(
      sf.PdfGraphics g, sf.PdfPen pen, Offset from, Offset to, double w) {
    final dx = to.dx - from.dx;
    final dy = to.dy - from.dy;
    final len = (dx * dx + dy * dy);
    if (len == 0) return;
    final size = (8 + w * 2);
    final angle = _atan2(dy, dx);
    for (final spread in [2.6, -2.6]) {
      final a = angle + spread;
      g.drawLine(
        pen,
        to,
        Offset(to.dx + size * _cos(a), to.dy + size * _sin(a)),
      );
    }
  }

  // Tiny trig helpers so this file doesn't need a dart:math import alias.
  double _atan2(double y, double x) => ui.Offset(x, y).direction;
  double _cos(double a) => ui.Offset.fromDirection(a).dx;
  double _sin(double a) => ui.Offset.fromDirection(a).dy;

  @override
  Widget build(BuildContext context) {
    if (_file == null) return _empty();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _toolbar(),
        const SizedBox(height: 12),
        Expanded(child: _stage()),
      ],
    );
  }

  Widget _empty() {
    final s = context.skin;
    return ViewScroll(
      children: [
        const SizedBox(height: 20),
        Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: RetroWindow(
              title: 'paint_a_pdf.exe',
              child: Padding(
                padding: const EdgeInsets.fromLTRB(26, 22, 26, 26),
                child: Column(
                  children: [
                    const Mascot(width: 130),
                    const SizedBox(height: 10),
                    Text(
                      'pick a pdf to scribble on',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontFamily: kPixel,
                        fontSize: 18,
                        fontWeight: FontWeight.w700,
                        color: s.titleInk,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'Add text, boxes, arrows, freehand, highlights and '
                      'whiteout. Your original file is never changed — the '
                      'edits always go to a new copy.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: s.muted, fontSize: 13),
                    ),
                    const SizedBox(height: 16),
                    RetroButton(
                      label: 'Open a PDF',
                      icon: '📂',
                      size: BtnSize.big,
                      onPressed: () async {
                        try {
                          final picked = await browseFiles(extensions: ['pdf']);
                          if (picked.isNotEmpty) await _open(picked.first);
                        } catch (e) {
                          failToast(e);
                        }
                      },
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _toolbar() {
    final s = context.skin;
    const labels = {
      EdTool.text: ('T', 'Text'),
      EdTool.rect: ('▭', 'Box'),
      EdTool.ellipse: ('◯', 'Ellipse'),
      EdTool.line: ('╱', 'Line'),
      EdTool.arrow: ('→', 'Arrow'),
      EdTool.freehand: ('✎', 'Draw'),
      EdTool.highlight: ('▉', 'Highlight'),
      EdTool.whiteout: ('▢', 'Whiteout'),
    };
    return RetroWindow(
      title: 'tools',
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(8, 7, 8, 7),
            child: Wrap(
              spacing: 4,
              runSpacing: 4,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                for (final e in labels.entries)
                  _TbButton(
                    glyph: e.value.$1,
                    label: e.value.$2,
                    on: _tool == e.key,
                    onTap: () => setState(() => _tool = e.key),
                  ),
                const SizedBox(width: 6),
                RetroButton(
                  label: 'Undo',
                  kind: BtnKind.ghost,
                  size: BtnSize.sm,
                  onPressed: _undo,
                ),
                RetroButton(
                  label: 'Save a copy',
                  size: BtnSize.sm,
                  onPressed: _loading ? null : _save,
                ),
                RetroButton(
                  label: 'Close',
                  kind: BtnKind.ghost,
                  size: BtnSize.sm,
                  onPressed: () => setState(() {
                    _file = null;
                    _pageImage = null;
                    _marks.clear();
                  }),
                ),
              ],
            ),
          ),
          const DashedDivider(),
          Padding(
            padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
            child: Wrap(
              spacing: 5,
              runSpacing: 5,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text('colour',
                    style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        color: s.muted)),
                for (final c in _palette)
                  GestureDetector(
                    onTap: () => setState(() => _color = c),
                    child: Container(
                      width: 22,
                      height: 22,
                      decoration: BoxDecoration(
                        color: c,
                        border: Border.all(color: s.ink, width: 2),
                        borderRadius: BorderRadius.circular(6),
                        boxShadow: _color == c
                            ? [BoxShadow(color: s.pink, spreadRadius: 2)]
                            : null,
                      ),
                    ),
                  ),
                const SizedBox(width: 10),
                Text(_tool == EdTool.text ? 'size' : 'width',
                    style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        color: s.muted)),
                SizedBox(
                  width: 140,
                  child: RetroSlider(
                    value: _tool == EdTool.text ? _fontSize : _stroke,
                    min: _tool == EdTool.text ? 8 : 1,
                    max: _tool == EdTool.text ? 48 : 20,
                    step: 1,
                    onChanged: (v) => setState(() {
                      if (_tool == EdTool.text) {
                        _fontSize = v;
                      } else {
                        _stroke = v;
                      }
                    }),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _stage() {
    final s = context.skin;
    return Column(
      children: [
        if (_pageCount > 1)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                IconBtn(
                  glyph: '‹',
                  onPressed: _page > 0
                      ? () {
                          setState(() => _page--);
                          _renderPage();
                        }
                      : null,
                ),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 14),
                  child: Text('page ${_page + 1} / $_pageCount',
                      style: TextStyle(
                          fontFamily: kPixel,
                          fontSize: 12,
                          color: s.titleInk)),
                ),
                IconBtn(
                  glyph: '›',
                  onPressed: _page < _pageCount - 1
                      ? () {
                          setState(() => _page++);
                          _renderPage();
                        }
                      : null,
                ),
              ],
            ),
          ),
        Expanded(
          child: Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: s.win2,
              border: Border.all(color: s.ink, width: 2),
              borderRadius: BorderRadius.circular(kRadius),
              boxShadow: hardShadow(s.drop),
            ),
            child: _loading || _pageImage == null
                ? Center(
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const RetroSpinner(),
                        const SizedBox(width: 10),
                        Text('rendering…',
                            style: TextStyle(
                                color: s.muted, fontWeight: FontWeight.w700)),
                      ],
                    ),
                  )
                : Center(child: _canvas()),
          ),
        ),
      ],
    );
  }

  Widget _canvas() {
    final s = context.skin;
    final marks = _marks.putIfAbsent(_page, () => []);
    return LayoutBuilder(
      builder: (context, box) => _InteractivePage(
        image: _pageImage!,
        maxSize: Size(box.maxWidth, box.maxHeight),
        marks: marks,
        drawing: _drawing,
        tool: _tool,
        color: _color,
        stroke: _stroke,
        fontSize: _fontSize,
        ink: s.ink,
        onStart: (p) => setState(() => _drawing = [p]),
        onUpdate: (p) => setState(() {
          if (_drawing == null) return;
          if (_tool == EdTool.freehand) {
            _drawing!.add(p);
          } else if (_drawing!.length < 2) {
            _drawing!.add(p);
          } else {
            // Shapes keep just a start and a live end point.
            _drawing![1] = p;
          }
        }),
        onEnd: () {
          final pts = _drawing;
          setState(() => _drawing = null);
          if (pts == null || pts.isEmpty) return;
          if (_tool != EdTool.freehand && pts.length < 2) return;
          setState(() => marks.add(Mark(
                tool: _tool,
                color: _color,
                width: _stroke,
                points: List.of(pts),
              )));
        },
        onTapText: (p) async {
          final text = await _askText();
          if (text == null || text.isEmpty) return;
          setState(() => marks.add(Mark(
                tool: EdTool.text,
                color: _color,
                width: _stroke,
                points: [p],
                text: text,
                fontSize: _fontSize,
              )));
        },
      ),
    );
  }

  Future<String?> _askText() async {
    final controller = TextEditingController();
    return showDialog<String>(
      context: context,
      barrierColor: context.skin.sky1.withValues(alpha: 0.55),
      builder: (ctx) => Center(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 400),
            child: RetroWindow(
              title: 'type_here.txt',
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    RetroField(
                      controller: controller,
                      hint: 'Text to place on the page',
                      onSubmitted: (v) => Navigator.of(ctx).pop(v),
                    ),
                    const SizedBox(height: 14),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        RetroButton(
                          label: 'Place',
                          onPressed: () =>
                              Navigator.of(ctx).pop(controller.text),
                        ),
                        const SizedBox(width: 12),
                        RetroButton(
                          label: 'Cancel',
                          kind: BtnKind.ghost,
                          onPressed: () => Navigator.of(ctx).pop(),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _TbButton extends StatelessWidget {
  const _TbButton({
    required this.glyph,
    required this.label,
    required this.on,
    required this.onTap,
  });

  final String glyph;
  final String label;
  final bool on;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
        decoration: BoxDecoration(
          color: on ? s.sel : Colors.transparent,
          border:
              Border.all(color: on ? s.ink : Colors.transparent, width: 2),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(glyph, style: TextStyle(fontSize: 13, color: s.text)),
            const SizedBox(width: 5),
            Text(label,
                style: TextStyle(
                    fontSize: 13, fontWeight: FontWeight.w700, color: s.text)),
          ],
        ),
      ),
    );
  }
}

/// The page image plus the mark overlay and the gesture handling.
class _InteractivePage extends StatelessWidget {
  const _InteractivePage({
    required this.image,
    required this.maxSize,
    required this.marks,
    required this.drawing,
    required this.tool,
    required this.color,
    required this.stroke,
    required this.fontSize,
    required this.ink,
    required this.onStart,
    required this.onUpdate,
    required this.onEnd,
    required this.onTapText,
  });

  final Uint8List image;
  final Size maxSize;
  final List<Mark> marks;
  final List<Offset>? drawing;
  final EdTool tool;
  final Color color;
  final double stroke;
  final double fontSize;
  final Color ink;
  final ValueChanged<Offset> onStart;
  final ValueChanged<Offset> onUpdate;
  final VoidCallback onEnd;
  final ValueChanged<Offset> onTapText;

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<ui.Image>(
      future: _decode(image),
      builder: (context, snap) {
        if (!snap.hasData) return const RetroSpinner();
        final img = snap.data!;
        final ratio = img.width / img.height;
        var w = maxSize.width;
        var h = w / ratio;
        if (h > maxSize.height) {
          h = maxSize.height;
          w = h * ratio;
        }
        Offset toFraction(Offset local) =>
            Offset((local.dx / w).clamp(0, 1), (local.dy / h).clamp(0, 1));

        return SizedBox(
          width: w,
          height: h,
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTapUp: tool == EdTool.text
                ? (d) => onTapText(toFraction(d.localPosition))
                : null,
            onPanStart: tool == EdTool.text
                ? null
                : (d) => onStart(toFraction(d.localPosition)),
            onPanUpdate: tool == EdTool.text
                ? null
                : (d) => onUpdate(toFraction(d.localPosition)),
            onPanEnd: tool == EdTool.text ? null : (_) => onEnd(),
            child: Container(
              decoration: BoxDecoration(
                color: Colors.white,
                boxShadow: hardShadow(ink.withValues(alpha: 0.35), 4),
              ),
              child: Stack(
                fit: StackFit.expand,
                children: [
                  Image.memory(image, fit: BoxFit.fill, gaplessPlayback: true),
                  CustomPaint(
                    painter: _MarksPainter(
                      marks: marks,
                      live: drawing == null
                          ? null
                          : Mark(
                              tool: tool,
                              color: color,
                              width: stroke,
                              points: drawing!,
                              fontSize: fontSize,
                            ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }

  static Future<ui.Image> _decode(Uint8List bytes) async {
    final codec = await ui.instantiateImageCodec(bytes);
    final frame = await codec.getNextFrame();
    return frame.image;
  }
}

class _MarksPainter extends CustomPainter {
  _MarksPainter({required this.marks, this.live});
  final List<Mark> marks;
  final Mark? live;

  @override
  void paint(Canvas canvas, Size size) {
    for (final m in marks) {
      _one(canvas, size, m);
    }
    if (live != null) _one(canvas, size, live!);
  }

  void _one(Canvas canvas, Size size, Mark m) {
    Offset p(Offset f) => Offset(f.dx * size.width, f.dy * size.height);
    final pts = m.points.map(p).toList();
    final pen = Paint()
      ..color = m.color
      ..strokeWidth = m.width
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;

    switch (m.tool) {
      case EdTool.text:
        if (pts.isEmpty) return;
        final tp = TextPainter(
          text: TextSpan(
            text: m.text,
            style: TextStyle(color: m.color, fontSize: m.fontSize),
          ),
          textDirection: TextDirection.ltr,
        )..layout();
        tp.paint(canvas, pts.first);
      case EdTool.rect:
        if (pts.length < 2) return;
        canvas.drawRect(Rect.fromPoints(pts.first, pts.last), pen);
      case EdTool.ellipse:
        if (pts.length < 2) return;
        canvas.drawOval(Rect.fromPoints(pts.first, pts.last), pen);
      case EdTool.line:
        if (pts.length < 2) return;
        canvas.drawLine(pts.first, pts.last, pen);
      case EdTool.arrow:
        if (pts.length < 2) return;
        canvas.drawLine(pts.first, pts.last, pen);
        final dir = (pts.last - pts.first).direction;
        final size0 = 8 + m.width * 2;
        for (final spread in [2.6, -2.6]) {
          canvas.drawLine(
            pts.last,
            pts.last + Offset.fromDirection(dir + spread, size0),
            pen,
          );
        }
      case EdTool.freehand:
        if (pts.length < 2) return;
        final path = Path()..moveTo(pts.first.dx, pts.first.dy);
        for (final q in pts.skip(1)) {
          path.lineTo(q.dx, q.dy);
        }
        canvas.drawPath(path, pen);
      case EdTool.highlight:
        if (pts.length < 2) return;
        canvas.drawRect(
          Rect.fromPoints(pts.first, pts.last),
          Paint()..color = m.color.withValues(alpha: 0.35),
        );
      case EdTool.whiteout:
        if (pts.length < 2) return;
        canvas.drawRect(
          Rect.fromPoints(pts.first, pts.last),
          Paint()..color = Colors.white,
        );
    }
  }

  @override
  bool shouldRepaint(_MarksPainter old) =>
      old.marks.length != marks.length || old.live != live;
}
