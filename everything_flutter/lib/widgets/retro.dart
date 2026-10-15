/// The retro-desktop widget kit: windows, title bars, buttons and form
/// controls. These are the Flutter equivalents of the .win / .btn / .card /
/// .titlebar rules in web/style.css.
library;
import 'package:flutter/material.dart';

import '../core/theme.dart';

/// box-shadow: Npx Npx 0 var(--drop)
List<BoxShadow> hardShadow(Color drop, [double n = 5]) =>
    [BoxShadow(color: drop, offset: Offset(n, n), blurRadius: 0)];

/// The three little window buttons stamped at the right of every title bar.
class _WindowButtons extends StatelessWidget {
  const _WindowButtons({required this.color});
  final Color color;

  @override
  Widget build(BuildContext context) =>
      CustomPaint(size: const Size(58, 15), painter: _WindowButtonsPainter(color));
}

class _WindowButtonsPainter extends CustomPainter {
  _WindowButtonsPainter(this.color);
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final s = size.width / 60;
    final stroke = Paint()
      ..color = color.withValues(alpha: 0.75)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2 * s;
    Rect box(double x) => Rect.fromLTWH(x * s, 1 * s, 16 * s, 14 * s);
    for (final x in [1.0, 22.0, 43.0]) {
      canvas.drawRRect(
          RRect.fromRectAndRadius(box(x), Radius.circular(3 * s)), stroke);
    }
    // minimise
    canvas.drawLine(Offset(5 * s, 11 * s), Offset(13 * s, 11 * s), stroke);
    // maximise
    canvas.drawRect(
      Rect.fromLTWH(26.5 * s, 4.5 * s, 7 * s, 7 * s),
      Paint()
        ..color = color.withValues(alpha: 0.75)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.6 * s,
    );
    // close
    final x = Paint()
      ..color = color.withValues(alpha: 0.75)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.8 * s;
    canvas.drawLine(Offset(47.5 * s, 4.5 * s), Offset(54.5 * s, 11.5 * s), x);
    canvas.drawLine(Offset(54.5 * s, 4.5 * s), Offset(47.5 * s, 11.5 * s), x);
  }

  @override
  bool shouldRepaint(_WindowButtonsPainter old) => old.color != color;
}

/// .titlebar — gradient strip, pixel font, lowercase.
class Titlebar extends StatelessWidget {
  const Titlebar(this.title, {super.key, this.error = false, this.onClose, this.trailing});

  final String title;
  final bool error;
  final VoidCallback? onClose;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    final ink = error ? const Color(0xFF5A2440) : s.titleInk;
    return Container(
      constraints: const BoxConstraints(minHeight: 32),
      padding: const EdgeInsets.fromLTRB(12, 6, 10, 6),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: error ? [s.pink, s.peach] : [s.title1, s.title2],
        ),
        border: Border(bottom: BorderSide(color: s.ink, width: 2)),
        borderRadius: const BorderRadius.vertical(top: Radius.circular(kRadius - 2)),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              title.toLowerCase(),
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontFamily: kPixel,
                fontSize: 13,
                height: 1.2,
                letterSpacing: 0.4,
                color: ink,
              ),
            ),
          ),
          ?trailing,
          if (onClose != null)
            _TitlebarX(onTap: onClose!, ink: ink)
          else if (trailing == null)
            _WindowButtons(color: ink),
        ],
      ),
    );
  }
}

class _TitlebarX extends StatelessWidget {
  const _TitlebarX({required this.onTap, required this.ink});
  final VoidCallback onTap;
  final Color ink;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return InkWell(
      onTap: onTap,
      child: Container(
        width: 22,
        height: 20,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          border: Border.all(color: ink, width: 2),
          borderRadius: BorderRadius.circular(5),
        ),
        child: Text('✕',
            style: TextStyle(fontSize: 11, height: 1, color: s.titleInk)),
      ),
    );
  }
}

/// .win — a bordered window with an optional title bar.
class RetroWindow extends StatelessWidget {
  const RetroWindow({
    super.key,
    this.title,
    required this.child,
    this.error = false,
    this.onClose,
    this.shadow = 5,
    this.clip = true,
  });

  final String? title;
  final Widget child;
  final bool error;
  final VoidCallback? onClose;
  final double shadow;
  final bool clip;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return Container(
      decoration: BoxDecoration(
        color: s.win,
        border: Border.all(color: s.ink, width: 2),
        borderRadius: BorderRadius.circular(kRadius),
        boxShadow: hardShadow(s.drop, shadow),
      ),
      clipBehavior: clip ? Clip.antiAlias : Clip.none,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ?(title == null ? null : Titlebar(title!, error: error, onClose: onClose)),
          Flexible(child: child),
        ],
      ),
    );
  }
}

/// .card — a window whose title bar doubles as its heading.
class RetroCard extends StatelessWidget {
  const RetroCard({super.key, this.title, required this.child, this.padding});

  final String? title;
  final Widget child;
  final EdgeInsets? padding;

  @override
  Widget build(BuildContext context) => RetroWindow(
        title: title,
        child: Padding(
          padding: padding ?? const EdgeInsets.all(16),
          child: child,
        ),
      );
}

enum BtnKind { primary, ghost, danger }

enum BtnSize { sm, normal, big }

/// .btn — gradient fill, hard border, offset shadow that collapses on press.
class RetroButton extends StatefulWidget {
  const RetroButton({
    super.key,
    required this.label,
    this.onPressed,
    this.kind = BtnKind.primary,
    this.size = BtnSize.normal,
    this.icon,
  });

  final String label;
  final VoidCallback? onPressed;
  final BtnKind kind;
  final BtnSize size;
  final String? icon;

  @override
  State<RetroButton> createState() => _RetroButtonState();
}

class _RetroButtonState extends State<RetroButton> {
  bool _down = false;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    final enabled = widget.onPressed != null;
    final pad = switch (widget.size) {
      BtnSize.sm => const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
      BtnSize.big => const EdgeInsets.symmetric(horizontal: 24, vertical: 10),
      BtnSize.normal => const EdgeInsets.symmetric(horizontal: 16, vertical: 7),
    };
    final fontSize = switch (widget.size) {
      BtnSize.sm => 12.0,
      BtnSize.big => 15.0,
      BtnSize.normal => 14.0,
    };
    final shadow = widget.size == BtnSize.sm ? 2.0 : 3.0;

    final (Gradient? gradient, Color bg, Color fg) = switch (widget.kind) {
      BtnKind.primary => (
          LinearGradient(
              colors: [s.accent, s.accent2],
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter),
          s.accent,
          s.accentInk
        ),
      BtnKind.ghost => (null, s.win, s.text),
      BtnKind.danger => (
          LinearGradient(
              colors: [s.pink, s.err],
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter),
          s.err,
          Colors.white
        ),
    };

    final offset = _down && enabled ? 2.0 : 0.0;
    return Opacity(
      opacity: enabled ? 1 : 0.45,
      child: GestureDetector(
        onTapDown: enabled ? (_) => setState(() => _down = true) : null,
        onTapUp: enabled ? (_) => setState(() => _down = false) : null,
        onTapCancel: enabled ? () => setState(() => _down = false) : null,
        onTap: widget.onPressed,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 60),
          transform: Matrix4.translationValues(offset, offset, 0),
          padding: pad,
          decoration: BoxDecoration(
            gradient: gradient,
            color: gradient == null ? bg : null,
            border: Border.all(color: s.ink, width: 2),
            borderRadius: BorderRadius.circular(9),
            boxShadow: hardShadow(s.drop, _down && enabled ? 1 : shadow),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (widget.icon != null) ...[
                Text(widget.icon!, style: TextStyle(fontSize: fontSize, color: fg)),
                const SizedBox(width: 6),
              ],
              // Flexible so a long label (several tool names are long) gives
              // way on a narrow screen instead of overflowing the button.
              Flexible(
                child: Text(
                  widget.label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: fg,
                    fontWeight: FontWeight.w800,
                    fontSize: fontSize,
                    fontFamily: kFont,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// .icon-btn — the square 32px buttons.
class IconBtn extends StatelessWidget {
  const IconBtn({super.key, required this.glyph, this.onPressed, this.tooltip});
  final String glyph;
  final VoidCallback? onPressed;
  final String? tooltip;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    final btn = GestureDetector(
      onTap: onPressed,
      child: Container(
        width: 32,
        height: 32,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: s.win,
          border: Border.all(color: s.ink, width: 2),
          borderRadius: BorderRadius.circular(8),
          boxShadow: hardShadow(s.drop, 2),
        ),
        child: Text(glyph,
            style: TextStyle(fontWeight: FontWeight.w800, color: s.text)),
      ),
    );
    return tooltip == null ? btn : Tooltip(message: tooltip!, child: btn);
  }
}

/// .badge
class RetroBadge extends StatelessWidget {
  const RetroBadge(this.text, {super.key, this.zero = false});
  final String text;
  final bool zero;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return Container(
      constraints: const BoxConstraints(minWidth: 18),
      padding: const EdgeInsets.symmetric(horizontal: 7),
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: zero ? s.win2 : s.pink,
        border: Border.all(color: s.ink, width: 1.5),
        borderRadius: BorderRadius.circular(99),
      ),
      child: Text(text,
          style: TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.w800,
            color: zero ? s.muted : const Color(0xFF4A2440),
          )),
    );
  }
}

/// .status — the little pill in the jobs window.
class StatusPill extends StatelessWidget {
  const StatusPill(this.label, {super.key, required this.color});
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 1),
        decoration: BoxDecoration(
          border: Border.all(color: color, width: 1.5),
          borderRadius: BorderRadius.circular(99),
        ),
        child: Text(label,
            style: TextStyle(fontFamily: kPixel, fontSize: 10, color: color)),
      );
}

/// .bar — the striped progress bar.
class RetroBar extends StatelessWidget {
  const RetroBar({super.key, required this.value, this.height = 14, this.color});
  final double value;
  final double height;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return Container(
      height: height,
      padding: const EdgeInsets.all(1),
      decoration: BoxDecoration(
        color: s.win,
        border: Border.all(color: s.ink, width: 2),
        borderRadius: BorderRadius.circular(99),
      ),
      child: LayoutBuilder(
        builder: (_, box) => Align(
          alignment: Alignment.centerLeft,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 400),
            width: box.maxWidth * value.clamp(0, 1),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(99),
              color: color,
              gradient: color != null
                  ? null
                  : LinearGradient(
                      colors: [s.accent, s.accent2],
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                      tileMode: TileMode.repeated,
                    ),
            ),
          ),
        ),
      ),
    );
  }
}

/// .section-label — "✦ heading" in the pixel font.
class SectionLabel extends StatelessWidget {
  const SectionLabel(this.text, {super.key});
  final String text;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return Padding(
      padding: const EdgeInsets.only(top: 24, bottom: 12),
      child: Row(children: [
        Text('✦', style: TextStyle(color: s.pink, fontSize: 14)),
        const SizedBox(width: 8),
        Flexible(
          child: Text(text,
              style: TextStyle(
                  fontFamily: kPixel, fontSize: 12, color: s.titleInk)),
        ),
      ]),
    );
  }
}

/// .tool-card — a little desktop window you can click.
class ToolCardTile extends StatefulWidget {
  const ToolCardTile({
    super.key,
    required this.icon,
    required this.title,
    required this.subtitle,
    this.onTap,
    this.accent,
    this.dimmed = false,
  });

  final String icon;
  final String title;
  final String subtitle;
  final VoidCallback? onTap;
  final Color? accent;
  final bool dimmed;

  @override
  State<ToolCardTile> createState() => _ToolCardTileState();
}

class _ToolCardTileState extends State<ToolCardTile> {
  bool _hover = false;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return MouseRegion(
      onEnter: (_) => setState(() => _hover = true),
      onExit: (_) => setState(() => _hover = false),
      cursor: widget.onTap == null
          ? SystemMouseCursors.basic
          : SystemMouseCursors.click,
      child: GestureDetector(
        onTap: widget.onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 120),
          transform: Matrix4.translationValues(
              _hover && widget.onTap != null ? -2 : 0,
              _hover && widget.onTap != null ? -2 : 0,
              0),
          decoration: BoxDecoration(
            color: s.win,
            border: Border.all(color: s.ink, width: 2),
            borderRadius: BorderRadius.circular(kRadius),
            boxShadow: hardShadow(s.drop, _hover && widget.onTap != null ? 7 : 5),
          ),
          clipBehavior: Clip.antiAlias,
          child: Opacity(
            opacity: widget.dimmed ? 0.6 : 1,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                // the 24px gradient strip with three dots
                Container(
                  height: 24,
                  decoration: BoxDecoration(
                    gradient: LinearGradient(colors: [s.title1, s.title2]),
                    border: Border(bottom: BorderSide(color: s.ink, width: 2)),
                  ),
                  child: Align(
                    alignment: Alignment.centerRight,
                    child: Padding(
                      padding: const EdgeInsets.only(right: 9),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          for (final c in [s.butter, s.mint, s.pink])
                            Container(
                              width: 9,
                              height: 9,
                              margin: const EdgeInsets.only(left: 7),
                              decoration: BoxDecoration(
                                color: c,
                                shape: BoxShape.circle,
                                border: Border.all(color: s.ink, width: 1.2),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.all(14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      TileIcon(widget.icon, color: widget.accent ?? s.lilac),
                      const SizedBox(height: 10),
                      Text(widget.title,
                          style: TextStyle(
                              fontWeight: FontWeight.w800, color: s.text)),
                      const SizedBox(height: 4),
                      Text(widget.subtitle,
                          style: TextStyle(fontSize: 12, color: s.muted)),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// .ti / .ico — the rounded pastel icon squares.
class TileIcon extends StatelessWidget {
  const TileIcon(this.glyph,
      {super.key, required this.color, this.size = 38, this.fontSize = 17});

  final String glyph;
  final Color color;
  final double size;
  final double fontSize;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: color,
        border: Border.all(color: s.ink, width: 2),
        borderRadius: BorderRadius.circular(size * 0.26),
        boxShadow: hardShadow(s.drop, 2),
      ),
      child: Text(glyph,
          style: TextStyle(fontSize: fontSize, color: const Color(0xFF3D3C6B))),
    );
  }
}

/// input[type=text] / number / password
class RetroField extends StatelessWidget {
  const RetroField({
    super.key,
    required this.controller,
    this.hint,
    this.obscure = false,
    this.number = false,
    this.onSubmitted,
    this.onChanged,
  });

  final TextEditingController controller;
  final String? hint;
  final bool obscure;
  final bool number;
  final ValueChanged<String>? onSubmitted;
  final ValueChanged<String>? onChanged;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return TextField(
      controller: controller,
      obscureText: obscure,
      keyboardType: number ? TextInputType.number : TextInputType.text,
      onSubmitted: onSubmitted,
      onChanged: onChanged,
      style: TextStyle(color: s.text, fontSize: 14),
      decoration: InputDecoration(
        isDense: true,
        hintText: hint,
        hintStyle: TextStyle(color: s.muted, fontSize: 13),
        filled: true,
        fillColor: s.win2,
        contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: BorderSide(color: s.inkSoft, width: 2),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: BorderSide(color: s.ink, width: 2),
        ),
      ),
    );
  }
}

/// select
class RetroSelect<T> extends StatelessWidget {
  const RetroSelect({
    super.key,
    required this.value,
    required this.items,
    required this.onChanged,
    this.dense = false,
  });

  final T value;
  final List<(T, String)> items;
  final ValueChanged<T> onChanged;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return Container(
      padding: EdgeInsets.symmetric(horizontal: dense ? 6 : 10, vertical: 1),
      decoration: BoxDecoration(
        color: s.win2,
        border: Border.all(color: s.inkSoft, width: 2),
        borderRadius: BorderRadius.circular(dense ? 99 : 8),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<T>(
          value: items.any((e) => e.$1 == value) ? value : items.first.$1,
          isDense: true,
          isExpanded: !dense,
          dropdownColor: s.win,
          borderRadius: BorderRadius.circular(8),
          icon: Icon(Icons.arrow_drop_down, color: s.muted, size: 20),
          style: TextStyle(
            color: s.text,
            fontWeight: FontWeight.w700,
            fontSize: dense ? 12 : 14,
            fontFamily: kFont,
          ),
          items: [
            for (final (v, label) in items)
              DropdownMenuItem(value: v, child: Text(label)),
          ],
          onChanged: (v) {
            if (v != null) onChanged(v);
          },
        ),
      ),
    );
  }
}

/// input[type=checkbox] with its label
class RetroCheck extends StatelessWidget {
  const RetroCheck(
      {super.key, required this.value, required this.label, required this.onChanged});

  final bool value;
  final String label;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return InkWell(
      onTap: () => onChanged(!value),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          SizedBox(
            width: 22,
            height: 22,
            child: Checkbox(
              value: value,
              onChanged: (v) => onChanged(v ?? false),
              activeColor: s.accent,
              checkColor: s.accentInk,
              side: BorderSide(color: s.ink, width: 2),
              materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
          ),
          const SizedBox(width: 8),
          Flexible(
            child: Text(label, style: TextStyle(fontSize: 13, color: s.text)),
          ),
        ],
      ),
    );
  }
}

/// input[type=range] with the pink thumb.
class RetroSlider extends StatelessWidget {
  const RetroSlider({
    super.key,
    required this.value,
    required this.min,
    required this.max,
    required this.step,
    required this.onChanged,
  });

  final double value, min, max, step;
  final ValueChanged<double> onChanged;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    final divisions = step > 0 ? ((max - min) / step).round() : null;
    return SliderTheme(
      data: SliderTheme.of(context).copyWith(
        trackHeight: 10,
        activeTrackColor: s.accent,
        inactiveTrackColor: s.win3,
        thumbColor: s.pink,
        overlayShape: SliderComponentShape.noOverlay,
        thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 9),
        tickMarkShape: SliderTickMarkShape.noTickMark,
      ),
      child: Slider(
        value: value.clamp(min, max),
        min: min,
        max: max,
        divisions: divisions != null && divisions > 0 ? divisions : null,
        onChanged: onChanged,
      ),
    );
  }
}

/// .spinner
class RetroSpinner extends StatelessWidget {
  const RetroSpinner({super.key, this.size = 16});
  final double size;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return SizedBox(
      width: size,
      height: size,
      child: CircularProgressIndicator(
        strokeWidth: 3,
        color: s.pink,
        backgroundColor: s.inkSoft,
      ),
    );
  }
}

/// A dashed rule, standing in for `border-top: 2px dashed`.
class DashedDivider extends StatelessWidget {
  const DashedDivider({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return LayoutBuilder(
      builder: (_, box) {
        const dash = 6.0;
        final count = (box.maxWidth / (dash * 2)).floor().clamp(1, 400);
        return Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: List.generate(
            count,
            (_) => Container(width: dash, height: 2, color: s.inkSoft),
          ),
        );
      },
    );
  }
}
