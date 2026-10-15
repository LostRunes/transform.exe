/// Design tokens ported 1:1 from web/style.css (:root day + :root[data-theme=dark] night).
library;
import 'package:flutter/material.dart';

enum ThemeMode2 { day, night }

@immutable
class Skin extends ThemeExtension<Skin> {
  const Skin({
    required this.isDark,
    required this.sky1,
    required this.sky2,
    required this.grid,
    required this.win,
    required this.win2,
    required this.win3,
    required this.title1,
    required this.title2,
    required this.titleInk,
    required this.ink,
    required this.inkSoft,
    required this.text,
    required this.muted,
    required this.accent,
    required this.accent2,
    required this.accentInk,
    required this.pink,
    required this.mint,
    required this.butter,
    required this.sky,
    required this.lilac,
    required this.peach,
    required this.ok,
    required this.warn,
    required this.err,
    required this.sel,
    required this.drop,
    required this.cloudFill,
    required this.cloudStroke,
    required this.spark,
    required this.task,
    required this.task2,
  });

  final bool isDark;
  final Color sky1, sky2, grid;
  final Color win, win2, win3;
  final Color title1, title2, titleInk;
  final Color ink, inkSoft, text, muted;
  final Color accent, accent2, accentInk;
  final Color pink, mint, butter, sky, lilac, peach;
  final Color ok, warn, err;
  final Color sel, drop;
  final Color cloudFill, cloudStroke, spark;
  final Color task, task2;

  /// --- day (light) ---
  static const day = Skin(
    isDark: false,
    sky1: Color(0xFFD9E6FF), sky2: Color(0xFFE8DCFF), grid: Color(0x217A7FD0),
    win: Color(0xFFFBFAFF), win2: Color(0xFFF0F1FF), win3: Color(0xFFE6E8FF),
    title1: Color(0xFFC5D2FF), title2: Color(0xFFE6D3FF), titleInk: Color(0xFF5A5CA8),
    ink: Color(0xFF8086D4), inkSoft: Color(0xFFC3C6F0), text: Color(0xFF3F3E6E), muted: Color(0xFF8B8AB6),
    accent: Color(0xFF8D8FF2), accent2: Color(0xFFB39CF5), accentInk: Color(0xFFFFFFFF),
    pink: Color(0xFFF6A9C9), mint: Color(0xFFA9E7CF), butter: Color(0xFFFFE3A3),
    sky: Color(0xFFA8C8FF), lilac: Color(0xFFCDB8FF), peach: Color(0xFFFFC7B0),
    ok: Color(0xFF3FB58A), warn: Color(0xFFE3A33C), err: Color(0xFFEC6F8E),
    sel: Color(0x298D8FF2), drop: Color(0x478086D4),
    cloudFill: Color(0x99FFFFFF), cloudStroke: Color(0xFFFFFFFF), spark: Color(0xFFFFFFFF),
    task: Color(0xFF8F95E2), task2: Color(0xFFA4A0EF),
  );

  /// --- night (dark) ---
  static const night = Skin(
    isDark: true,
    sky1: Color(0xFF15142E), sky2: Color(0xFF2A2356), grid: Color(0x12A9A6FF),
    win: Color(0xFF23214A), win2: Color(0xFF1B1A3C), win3: Color(0xFF2D2B5C),
    title1: Color(0xFF3A3B85), title2: Color(0xFF56408C), titleInk: Color(0xFFE6E2FF),
    ink: Color(0xFF8F8CF0), inkSoft: Color(0xFF4A4890), text: Color(0xFFECEBFF), muted: Color(0xFFA4A2D8),
    accent: Color(0xFF9D9BFF), accent2: Color(0xFFC19CFF), accentInk: Color(0xFF1B1A3C),
    pink: Color(0xFFE88FB8), mint: Color(0xFF79CDB0), butter: Color(0xFFE9C97A),
    sky: Color(0xFF7FA6F0), lilac: Color(0xFFA78BF0), peach: Color(0xFFE7A48B),
    ok: Color(0xFF6FDCB0), warn: Color(0xFFF1BF62), err: Color(0xFFFF8AA8),
    sel: Color(0x2E9D9BFF), drop: Color(0x61000000),
    cloudFill: Color(0x248C82E6), cloudStroke: Color(0x47CDC8FF), spark: Color(0xFFFFF6C9),
    task: Color(0xFF2C2A62), task2: Color(0xFF3B3480),
  );

  @override
  Skin copyWith() => this;

  @override
  Skin lerp(ThemeExtension<Skin>? other, double t) =>
      t < 0.5 ? this : (other as Skin? ?? this);
}

/// --r: 12px
const double kRadius = 12;

/// var(--pixel) — Silkscreen
const String kPixel = 'Pixel';

/// var(--font) — Nunito
const String kFont = 'Nunito';

extension SkinContext on BuildContext {
  Skin get skin => Theme.of(this).extension<Skin>()!;
}

ThemeData buildTheme(Skin s) {
  final base = s.isDark ? ThemeData.dark() : ThemeData.light();
  return base.copyWith(
    extensions: [s],
    scaffoldBackgroundColor: s.sky1,
    canvasColor: s.win,
    textTheme: base.textTheme.apply(
      fontFamily: kFont,
      bodyColor: s.text,
      displayColor: s.text,
    ),
    colorScheme: base.colorScheme.copyWith(
      primary: s.accent,
      secondary: s.pink,
      surface: s.win,
      error: s.err,
    ),
    // The retro skin draws its own chrome; strip Material's.
    splashFactory: NoSplash.splashFactory,
    highlightColor: Colors.transparent,
  );
}
