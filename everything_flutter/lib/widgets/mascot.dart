/// The buddy: a floating mascot with a speech bubble that wiggles when poked.
library;
import 'package:flutter/material.dart';

import '../core/app_state.dart';
import '../core/theme.dart';
import 'retro.dart';

const mascotAsset = 'assets/images/mascot-light.png';
const mascotAssetSm = 'assets/images/mascot-light-sm.png';

/// .mascot.float — the gentle bob, plus a one-shot wiggle on tap.
class Mascot extends StatefulWidget {
  const Mascot({
    super.key,
    this.width = 84,
    this.float = true,
    this.tappable = false,
    this.small = false,
  });

  final double width;
  final bool float;
  final bool tappable;
  final bool small;

  @override
  State<Mascot> createState() => _MascotState();
}

class _MascotState extends State<Mascot> with TickerProviderStateMixin {
  late final AnimationController _floatC = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 3400),
  );

  late final AnimationController _wiggleC = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 600),
  );

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // Same reasoning as Sky: a forever-repeating controller never goes idle.
    final still = MediaQuery.disableAnimationsOf(context);
    if (still && _floatC.isAnimating) {
      _floatC.stop();
    } else if (!still && !_floatC.isAnimating) {
      _floatC.repeat(reverse: true);
    }
  }

  @override
  void dispose() {
    _floatC.dispose();
    _wiggleC.dispose();
    super.dispose();
  }

  void _poke() {
    if (!widget.tappable) return;
    _wiggleC.forward(from: 0);
    final app = AppState.instance;
    app.say(quips[DateTime.now().microsecond % quips.length]);
    Future.delayed(const Duration(milliseconds: 2600), () {
      if (mounted) app.resetSay();
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    final still = MediaQuery.disableAnimationsOf(context);

    Widget image = Image.asset(
      widget.small ? mascotAssetSm : mascotAsset,
      width: widget.width,
      fit: BoxFit.contain,
      filterQuality: FilterQuality.medium,
    );

    // drop-shadow(3px 4px 0 var(--drop))
    image = DecoratedBox(
      decoration: BoxDecoration(boxShadow: [
        BoxShadow(color: s.drop, offset: const Offset(3, 4), blurRadius: 0),
      ]),
      child: image,
    );

    if (!still) {
      image = AnimatedBuilder(
        animation: Listenable.merge([_floatC, _wiggleC]),
        builder: (_, child) {
          final lift = widget.float ? -7 * Curves.easeInOut.transform(_floatC.value) : 0.0;
          final tilt = widget.float ? -0.026 * _floatC.value : 0.0;
          // 25% -8deg, 75% +8deg, with a slight scale-up.
          final w = _wiggleC.isAnimating
              ? 0.14 * -(1 - 2 * _wiggleC.value).sign * (1 - (2 * _wiggleC.value - 1).abs())
              : 0.0;
          final scale = _wiggleC.isAnimating
              ? 1 + 0.05 * (1 - (2 * _wiggleC.value - 1).abs())
              : 1.0;
          return Transform.translate(
            offset: Offset(0, lift),
            child: Transform.rotate(
              angle: tilt + w,
              child: Transform.scale(scale: scale, child: child),
            ),
          );
        },
        child: image,
      );
    }

    return widget.tappable
        ? GestureDetector(onTap: _poke, child: image)
        : image;
  }
}

/// .bubble — the speech bubble above the buddy, with its little tail.
class SpeechBubble extends StatelessWidget {
  const SpeechBubble(this.text, {super.key});
  final String text;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          constraints: const BoxConstraints(maxWidth: 200),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: s.win2,
            border: Border.all(color: s.ink, width: 2),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Text(
            text,
            textAlign: TextAlign.center,
            style: TextStyle(
                fontSize: 12, fontWeight: FontWeight.w700, color: s.text),
          ),
        ),
        // the rotated square tail
        Transform.translate(
          offset: const Offset(0, -6),
          child: Transform.rotate(
            angle: 0.785,
            child: Container(
              width: 11,
              height: 11,
              decoration: BoxDecoration(
                color: s.win2,
                border: Border(
                  right: BorderSide(color: s.ink, width: 2),
                  bottom: BorderSide(color: s.ink, width: 2),
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// The "nothing here yet" blocks that pair the mascot with a line of text.
class MascotEmpty extends StatelessWidget {
  const MascotEmpty({super.key, required this.text, this.sub, this.width = 90});
  final String text;
  final String? sub;
  final double width;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 20, horizontal: 10),
      child: Column(
        children: [
          Mascot(width: width),
          const SizedBox(height: 10),
          Text(text,
              textAlign: TextAlign.center,
              style: TextStyle(fontWeight: FontWeight.w700, color: s.muted)),
          if (sub != null) ...[
            const SizedBox(height: 4),
            Text(sub!,
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 12, color: s.muted)),
          ],
        ],
      ),
    );
  }
}

/// The retro "are you sure?" dialog. Resolves true for Yes.
Future<bool> ask(
  BuildContext context,
  String message, {
  String title = 'are you sure?',
  String yes = 'Yes',
  String no = 'No',
  bool danger = false,
}) async {
  final result = await showDialog<bool>(
    context: context,
    barrierColor: context.skin.sky1.withValues(alpha: 0.55),
    builder: (ctx) {
      final s = ctx.skin;
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 400),
            child: RetroWindow(
              title: title,
              error: danger,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(18, 18, 18, 8),
                    child: Row(
                      children: [
                        const Mascot(width: 70),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Text(message,
                              style: TextStyle(
                                  fontWeight: FontWeight.w700, color: s.text)),
                        ),
                      ],
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(18, 12, 18, 18),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        RetroButton(
                          label: yes,
                          kind: danger ? BtnKind.danger : BtnKind.primary,
                          onPressed: () => Navigator.of(ctx).pop(true),
                        ),
                        const SizedBox(width: 14),
                        RetroButton(
                          label: no,
                          kind: BtnKind.ghost,
                          onPressed: () => Navigator.of(ctx).pop(false),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    },
  );
  return result ?? false;
}
