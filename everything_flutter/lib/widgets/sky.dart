/// The decorative backdrop: gradient + 28px grid, drifting clouds, twinkling
/// sparkles, and stars plus a moon after dark. Mirrors the .sky block in
/// web/style.css.
library;
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../core/theme.dart';

class Sky extends StatefulWidget {
  const Sky({super.key, required this.child});
  final Widget child;

  @override
  State<Sky> createState() => _SkyState();
}

class _SkyState extends State<Sky> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(seconds: 60),
  );

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // Honour reduced motion by actually stopping the ticker, not just hiding
    // the result: a controller left repeating never lets the frame scheduler
    // go idle, which burns battery and hangs any pumpAndSettle in a test.
    final still = MediaQuery.disableAnimationsOf(context);
    if (still && _c.isAnimating) {
      _c.stop();
    } else if (!still && !_c.isAnimating) {
      _c.repeat();
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    // Respect the reduced-motion preference, same as the CSS media query.
    final still = MediaQuery.disableAnimationsOf(context);
    return DecoratedBox(
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [s.sky1, s.sky2],
        ),
      ),
      child: Stack(
        children: [
          Positioned.fill(
            child: RepaintBoundary(
              child: still
                  ? CustomPaint(painter: _SkyPainter(s, 0))
                  : AnimatedBuilder(
                      animation: _c,
                      builder: (_, _) =>
                          CustomPaint(painter: _SkyPainter(s, _c.value)),
                    ),
            ),
          ),
          Positioned.fill(child: widget.child),
        ],
      ),
    );
  }
}

class _SkyPainter extends CustomPainter {
  _SkyPainter(this.s, this.t);
  final Skin s;
  final double t;

  // left, top, width, speed — as fractions of the viewport.
  static const _clouds = [
    (0.18, 0.08, 220.0, 1.0),
    (0.62, 0.58, 280.0, 0.75),
    (0.08, 0.82, 170.0, 0.86),
    (0.90, 0.28, 190.0, 0.67),
  ];

  static const _sparks = [
    (0.44, 0.14, 16.0, 0.0),
    (0.30, 0.36, 10.0, 0.6),
    (0.48, 0.70, 16.0, 1.2),
    (0.78, 0.22, 22.0, 1.8),
    (0.70, 0.88, 12.0, 0.3),
    (0.12, 0.50, 12.0, 2.2),
    (0.70, 0.06, 9.0, 1.0),
  ];

  static const _stars = [
    (0.10, 0.05, 0.0), (0.56, 0.12, 0.4), (0.80, 0.30, 0.8), (0.05, 0.44, 1.2),
    (0.36, 0.64, 1.6), (0.90, 0.76, 2.0), (0.34, 0.20, 0.2), (0.60, 0.90, 1.0),
    (0.74, 0.54, 1.4), (0.88, 0.03, 2.4),
  ];

  @override
  void paint(Canvas canvas, Size size) {
    _grid(canvas, size);

    for (final (x, y, w, speed) in _clouds) {
      // @keyframes drift: translateX(0 -> 70px), alternating.
      final phase = (t * speed) % 1.0;
      final drift = 70 * (1 - (2 * phase - 1).abs());
      _cloud(canvas, Offset(size.width * x - w / 2 + drift, size.height * y), w);
    }

    if (s.isDark) {
      _moon(canvas, Offset(size.width * 0.91, size.height * 0.07), 70);
      for (final (x, y, delay) in _stars) {
        final a = _twinkle(delay, 2.6);
        canvas.drawCircle(
          Offset(size.width * x, size.height * y),
          1.5,
          Paint()..color = Colors.white.withValues(alpha: a),
        );
      }
    }

    for (final (x, y, w, delay) in _sparks) {
      _spark(canvas, Offset(size.width * x, size.height * y), w,
          _twinkle(delay, 3.2));
    }
  }

  /// 50% { scale(.55); opacity .35 } — approximated as a smooth pulse.
  double _twinkle(double delay, double period) {
    final phase = ((t * 60 / period) + delay / period) % 1.0;
    return 0.35 + 0.55 * (0.5 + 0.5 * math.cos(phase * 2 * math.pi));
  }

  void _grid(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = s.grid
      ..strokeWidth = 1;
    for (var x = 0.0; x < size.width; x += 28) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), paint);
    }
    for (var y = 0.0; y < size.height; y += 28) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), paint);
    }
  }

  /// The same rounded blob as the inline `<svg class="cloud">` path.
  void _cloud(Canvas canvas, Offset at, double width) {
    final scale = width / 200;
    canvas.save();
    canvas.translate(at.dx, at.dy);
    canvas.scale(scale);
    final path = Path()
      ..moveTo(30, 80)
      ..lineTo(170, 80)
      ..arcToPoint(const Offset(170, 30), radius: const Radius.circular(25))
      ..arcToPoint(const Offset(108, 14), radius: const Radius.circular(35))
      ..arcToPoint(const Offset(58, 34), radius: const Radius.circular(28))
      ..arcToPoint(const Offset(30, 80), radius: const Radius.circular(23))
      ..close();
    canvas.drawPath(path, Paint()..color = s.cloudFill);
    canvas.drawPath(
      path,
      Paint()
        ..color = s.cloudStroke
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3,
    );
    canvas.restore();
  }

  void _spark(Canvas canvas, Offset at, double size, double alpha) {
    final path = Path();
    // The 8-point star from the CSS clip-path.
    const pts = [
      [0.50, 0.00], [0.62, 0.38], [1.00, 0.50], [0.62, 0.62],
      [0.50, 1.00], [0.38, 0.62], [0.00, 0.50], [0.38, 0.38],
    ];
    for (var i = 0; i < pts.length; i++) {
      final dx = at.dx + (pts[i][0] - 0.5) * size;
      final dy = at.dy + (pts[i][1] - 0.5) * size;
      i == 0 ? path.moveTo(dx, dy) : path.lineTo(dx, dy);
    }
    path.close();
    canvas.save();
    // Scale about the centre so it pulses in place.
    canvas.translate(at.dx, at.dy);
    canvas.scale(0.55 + 0.45 * alpha);
    canvas.translate(-at.dx, -at.dy);
    canvas.drawPath(path, Paint()..color = s.spark.withValues(alpha: alpha));
    canvas.restore();
  }

  void _moon(Canvas canvas, Offset at, double size) {
    final scale = size / 64;
    canvas.save();
    canvas.translate(at.dx - size / 2, at.dy);
    canvas.scale(scale);
    final path = Path()
      ..moveTo(44, 8)
      ..arcToPoint(const Offset(58, 48),
          radius: const Radius.circular(26), clockwise: false)
      ..arcToPoint(const Offset(44, 8), radius: const Radius.circular(22))
      ..close();
    canvas.drawPath(
      path,
      Paint()
        ..color = const Color(0xFFFFF3C2)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 6),
    );
    canvas.drawPath(path, Paint()..color = const Color(0xFFFFF3C2));
    canvas.restore();
  }

  @override
  bool shouldRepaint(_SkyPainter old) => old.t != t || old.s != s;
}
