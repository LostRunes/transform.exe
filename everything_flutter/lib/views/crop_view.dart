/// Crop a scanned page before it becomes a PDF.
///
/// Hand-rolled rather than pulling in image_cropper: that package ships its own
/// native Material activity, which would look nothing like the rest of this app
/// and adds an Android dependency for something the framework can already do.
library;

import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../core/theme.dart';
import '../widgets/retro.dart';

/// What the crop screen hands back: the kept area as 0..1 fractions of the
/// rotated image, plus how far it was rotated.
class CropResult {
  const CropResult(this.rect, this.quarterTurns);
  final Rect rect;
  final int quarterTurns;

  bool get isNoop => quarterTurns % 4 == 0 && rect == const Rect.fromLTRB(0, 0, 1, 1);
}

class CropPage extends StatefulWidget {
  const CropPage({super.key, required this.path, this.title = 'crop.exe'});

  final String path;
  final String title;

  @override
  State<CropPage> createState() => _CropPageState();
}

class _CropPageState extends State<CropPage> {
  /// Natural pixel size of the file, before any rotation.
  Size? _natural;
  String? _error;

  int _turns = 0;
  Rect _rect = const Rect.fromLTRB(0, 0, 1, 1);

  /// Smallest crop we allow, as a fraction, so handles stay grabbable.
  static const _minFrac = 0.08;
  static const _handle = 28.0;

  @override
  void initState() {
    super.initState();
    _measure();
  }

  /// Read the pixel dimensions without fully decoding the file.
  Future<void> _measure() async {
    try {
      final bytes = await File(widget.path).readAsBytes();
      final buffer = await ui.ImmutableBuffer.fromUint8List(bytes);
      final descriptor = await ui.ImageDescriptor.encoded(buffer);
      final size =
          Size(descriptor.width.toDouble(), descriptor.height.toDouble());
      descriptor.dispose();
      buffer.dispose();
      if (mounted) setState(() => _natural = size);
    } catch (e) {
      if (mounted) setState(() => _error = 'Could not read that image');
    }
  }

  /// Size as displayed, accounting for the quarter turns applied so far.
  Size get _rotated {
    final n = _natural!;
    return _turns.isEven ? n : Size(n.height, n.width);
  }

  void _rotate() {
    setState(() {
      _turns = (_turns + 1) % 4;
      // The old box means nothing once the axes swap.
      _rect = const Rect.fromLTRB(0, 0, 1, 1);
    });
  }

  void _reset() => setState(() {
        _turns = 0;
        _rect = const Rect.fromLTRB(0, 0, 1, 1);
      });

  /// Drag one corner, keeping the box inside the image and above the minimum.
  void _dragCorner(Alignment corner, Offset deltaFrac) {
    setState(() {
      var l = _rect.left, t = _rect.top, r = _rect.right, b = _rect.bottom;
      if (corner.x < 0) {
        l = (l + deltaFrac.dx).clamp(0.0, r - _minFrac);
      } else {
        r = (r + deltaFrac.dx).clamp(l + _minFrac, 1.0);
      }
      if (corner.y < 0) {
        t = (t + deltaFrac.dy).clamp(0.0, b - _minFrac);
      } else {
        b = (b + deltaFrac.dy).clamp(t + _minFrac, 1.0);
      }
      _rect = Rect.fromLTRB(l, t, r, b);
    });
  }

  void _dragBody(Offset deltaFrac) {
    setState(() {
      final dx = deltaFrac.dx.clamp(-_rect.left, 1 - _rect.right);
      final dy = deltaFrac.dy.clamp(-_rect.top, 1 - _rect.bottom);
      _rect = _rect.shift(Offset(dx, dy));
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return Scaffold(
      backgroundColor: s.sky1,
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(10, 10, 10, 6),
              child: RetroWindow(
                title: widget.title,
                shadow: 3,
                child: Padding(
                  padding: const EdgeInsets.all(8),
                  child: Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      RetroButton(
                        label: 'Rotate',
                        icon: '↻',
                        kind: BtnKind.ghost,
                        size: BtnSize.sm,
                        onPressed: _natural == null ? null : _rotate,
                      ),
                      RetroButton(
                        label: 'Reset',
                        kind: BtnKind.ghost,
                        size: BtnSize.sm,
                        onPressed: _natural == null ? null : _reset,
                      ),
                      const Spacer(),
                      RetroButton(
                        label: 'Cancel',
                        kind: BtnKind.ghost,
                        size: BtnSize.sm,
                        onPressed: () => Navigator.of(context).pop(),
                      ),
                      RetroButton(
                        key: const Key('crop-apply'),
                        label: 'Use this',
                        size: BtnSize.sm,
                        onPressed: _natural == null
                            ? null
                            : () => Navigator.of(context)
                                .pop(CropResult(_rect, _turns)),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            Expanded(child: _stage(s)),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
              child: Text(
                'Drag the corners to keep just the page.',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 12, color: s.muted),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _stage(Skin s) {
    if (_error != null) {
      return Center(
        child: Text(_error!, style: TextStyle(color: s.err)),
      );
    }
    if (_natural == null) {
      return const Center(child: RetroSpinner(size: 28));
    }

    return Padding(
      padding: const EdgeInsets.all(16),
      child: LayoutBuilder(
        builder: (context, box) {
          // Fit the rotated image inside the available area.
          final rotated = _rotated;
          final scale = (box.maxWidth / rotated.width)
              .clamp(0.0, box.maxHeight / rotated.height);
          final w = rotated.width * scale;
          final h = rotated.height * scale;

          return Center(
            child: SizedBox(
              width: w,
              height: h,
              child: Stack(
                clipBehavior: Clip.none,
                children: [
                  Positioned.fill(
                    child: RotatedBox(
                      quarterTurns: _turns,
                      child: Image.file(
                        File(widget.path),
                        fit: BoxFit.fill,
                        gaplessPlayback: true,
                      ),
                    ),
                  ),
                  Positioned.fill(
                    child: IgnorePointer(
                      child: CustomPaint(
                        painter: _CropPainter(rect: _rect, ink: s.ink),
                      ),
                    ),
                  ),
                  // Move the whole box.
                  Positioned(
                    left: _rect.left * w,
                    top: _rect.top * h,
                    width: _rect.width * w,
                    height: _rect.height * h,
                    child: GestureDetector(
                      behavior: HitTestBehavior.translucent,
                      onPanUpdate: (d) => _dragBody(
                          Offset(d.delta.dx / w, d.delta.dy / h)),
                    ),
                  ),
                  for (final corner in const [
                    Alignment.topLeft,
                    Alignment.topRight,
                    Alignment.bottomLeft,
                    Alignment.bottomRight,
                  ])
                    Positioned(
                      left: (corner.x < 0 ? _rect.left : _rect.right) * w -
                          _handle / 2,
                      top: (corner.y < 0 ? _rect.top : _rect.bottom) * h -
                          _handle / 2,
                      width: _handle,
                      height: _handle,
                      child: GestureDetector(
                        behavior: HitTestBehavior.opaque,
                        onPanUpdate: (d) => _dragCorner(
                            corner, Offset(d.delta.dx / w, d.delta.dy / h)),
                        child: Center(
                          child: Container(
                            width: 16,
                            height: 16,
                            decoration: BoxDecoration(
                              color: s.pink,
                              border: Border.all(color: s.ink, width: 2),
                              borderRadius: BorderRadius.circular(4),
                            ),
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

/// Dims everything outside the crop box and draws thirds guides inside it.
class _CropPainter extends CustomPainter {
  _CropPainter({required this.rect, required this.ink});
  final Rect rect;
  final Color ink;

  @override
  void paint(Canvas canvas, Size size) {
    final box = Rect.fromLTRB(
      rect.left * size.width,
      rect.top * size.height,
      rect.right * size.width,
      rect.bottom * size.height,
    );

    final shade = Path.combine(
      PathOperation.difference,
      Path()..addRect(Offset.zero & size),
      Path()..addRect(box),
    );
    canvas.drawPath(shade, Paint()..color = const Color(0x99000000));

    canvas.drawRect(
      box,
      Paint()
        ..color = Colors.white
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );

    final guide = Paint()
      ..color = Colors.white.withValues(alpha: 0.4)
      ..strokeWidth = 1;
    for (var i = 1; i < 3; i++) {
      final x = box.left + box.width * i / 3;
      final y = box.top + box.height * i / 3;
      canvas.drawLine(Offset(x, box.top), Offset(x, box.bottom), guide);
      canvas.drawLine(Offset(box.left, y), Offset(box.right, y), guide);
    }
  }

  @override
  bool shouldRepaint(_CropPainter old) => old.rect != rect || old.ink != ink;
}
