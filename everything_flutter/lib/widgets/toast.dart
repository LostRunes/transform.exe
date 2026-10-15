/// Little window-shaped toasts stacked in the bottom corner, same as .toast
/// in web/style.css. Driven through a global overlay so any view can call it.
library;
import 'package:flutter/material.dart';

import '../core/theme.dart';
import 'mascot.dart';
import 'retro.dart';

final toastKey = GlobalKey<ToastHostState>();

void toast(String message, {bool error = false}) =>
    toastKey.currentState?.show(message, error: error);

void failToast(Object e) {
  var s = e.toString();
  if (s.startsWith('Exception: ')) s = s.substring(11);
  toast(s, error: true);
}

class ToastHost extends StatefulWidget {
  const ToastHost({super.key, required this.child});
  final Widget child;

  @override
  State<ToastHost> createState() => ToastHostState();
}

class _Entry {
  _Entry(this.id, this.message, this.error);
  final int id;
  final String message;
  final bool error;
}

class ToastHostState extends State<ToastHost> {
  final List<_Entry> _entries = [];
  var _next = 0;

  void show(String message, {bool error = false}) {
    final entry = _Entry(_next++, message, error);
    setState(() => _entries.add(entry));
    Future.delayed(Duration(milliseconds: error ? 6500 : 3800), () {
      if (mounted) setState(() => _entries.remove(entry));
    });
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        widget.child,
        Positioned(
          right: 16,
          bottom: 60,
          child: IgnorePointer(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              mainAxisSize: MainAxisSize.min,
              children: [
                for (final e in _entries)
                  Padding(
                    key: ValueKey(e.id),
                    padding: const EdgeInsets.only(top: 10),
                    child: _Toast(entry: e),
                  ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _Toast extends StatefulWidget {
  const _Toast({required this.entry});
  final _Entry entry;

  @override
  State<_Toast> createState() => _ToastState();
}

class _ToastState extends State<_Toast> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 250),
  )..forward();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    // @keyframes pop — overshoot in from below.
    final curve = CurvedAnimation(parent: _c, curve: Curves.elasticOut);
    return FadeTransition(
      opacity: _c,
      child: ScaleTransition(
        scale: Tween(begin: 0.9, end: 1.0).animate(curve),
        child: SizedBox(
          width: 340,
          child: RetroWindow(
            title: widget.entry.error ? 'error' : 'notice.txt',
            error: widget.entry.error,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  const Mascot(width: 38, float: false, small: true),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      widget.entry.message,
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                        color: s.text,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
