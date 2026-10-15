/// Builds a settings form from a list of [ParamDef]s and reads the values back,
/// including the show_if dependency rules. Port of renderParams/readParams.
library;
import 'package:flutter/material.dart';

import '../core/models.dart';
import '../core/theme.dart';
import 'retro.dart';

class ParamsForm extends StatefulWidget {
  const ParamsForm(
      {super.key, required this.params, required this.values, this.onChanged});

  final List<ParamDef> params;

  /// Called after any value changes, so the page can refresh a live estimate.
  final VoidCallback? onChanged;

  /// Mutated in place, so the owning view can read it when the user hits Run.
  final Map<String, Object?> values;

  @override
  State<ParamsForm> createState() => _ParamsFormState();
}

class _ParamsFormState extends State<ParamsForm> {
  final Map<String, TextEditingController> _controllers = {};

  @override
  void initState() {
    super.initState();
    _seed();
  }

  @override
  void didUpdateWidget(ParamsForm old) {
    super.didUpdateWidget(old);
    if (old.params != widget.params) _seed();
  }

  void _seed() {
    for (final p in widget.params) {
      widget.values.putIfAbsent(p.name, () => p.defaultValue);
      if (p.type == ParamType.text ||
          p.type == ParamType.number ||
          p.type == ParamType.password) {
        final controller =
            _controllers.putIfAbsent(p.name, () => TextEditingController());
        final text = (widget.values[p.name] ?? '').toString();
        // Only assign when it really changed: writing .text resets the
        // selection, which would jump the caret while someone is typing.
        if (controller.text != text) controller.text = text;
      }
    }
  }

  @override
  void dispose() {
    for (final c in _controllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  /// A field is hidden until every show_if condition matches, and while the
  /// field it depends on is itself hidden.
  bool _visible(ParamDef p) {
    if (p.showIf == null) return true;
    return p.showIf!.entries.every((e) {
      final parent = widget.params.where((o) => o.name == e.key);
      if (parent.isNotEmpty && !_visible(parent.first)) return false;
      final want = e.value;
      final have = '${widget.values[e.key]}';
      return want is List ? want.contains(have) : have == '$want';
    });
  }

  @override
  void setState(VoidCallback fn) {
    super.setState(fn);
    widget.onChanged?.call();
  }

  @override
  Widget build(BuildContext context) {
    final shown = widget.params.where(_visible).toList();
    return LayoutBuilder(
      builder: (context, box) {
        // .opts — auto-fill, minmax(240px, 1fr)
        final columns = (box.maxWidth / 260).floor().clamp(1, 3);
        final width = columns == 1
            ? box.maxWidth
            : (box.maxWidth - (columns - 1) * 22) / columns;
        return Wrap(
          spacing: 22,
          runSpacing: 14,
          children: [
            for (final p in shown)
              SizedBox(width: width, child: _field(context, p)),
          ],
        );
      },
    );
  }

  Widget _field(BuildContext context, ParamDef p) {
    final s = context.skin;
    final value = widget.values[p.name];

    Widget labelled(Widget child) => Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              p.label,
              style: TextStyle(
                  fontSize: 12, fontWeight: FontWeight.w700, color: s.muted),
            ),
            const SizedBox(height: 5),
            child,
          ],
        );

    switch (p.type) {
      case ParamType.select:
        return labelled(RetroSelect<String>(
          value: '$value',
          items: [for (final o in p.options) (o[0], o[1])],
          onChanged: (v) => setState(() => widget.values[p.name] = v),
        ));

      case ParamType.checkbox:
        return Padding(
          padding: const EdgeInsets.only(top: 18),
          child: RetroCheck(
            value: value == true,
            label: p.label,
            onChanged: (v) => setState(() => widget.values[p.name] = v),
          ),
        );

      case ParamType.range:
        final v = (value is num ? value.toDouble() : p.min.toDouble());
        final decimals = p.step < 1 ? 2 : 0;
        return labelled(Row(
          children: [
            Expanded(
              child: RetroSlider(
                value: v,
                min: p.min.toDouble(),
                max: p.max.toDouble(),
                step: p.step.toDouble(),
                onChanged: (nv) => setState(() => widget.values[p.name] = nv),
              ),
            ),
            const SizedBox(width: 8),
            Text(
              v.toStringAsFixed(decimals),
              style: TextStyle(fontWeight: FontWeight.w800, color: s.text),
            ),
          ],
        ));

      case ParamType.color:
        return labelled(_ColorRow(
          value: '$value',
          onChanged: (v) => setState(() => widget.values[p.name] = v),
        ));

      case ParamType.text:
      case ParamType.number:
      case ParamType.password:
        return labelled(RetroField(
          controller: _controllers[p.name]!,
          number: p.type == ParamType.number,
          obscure: p.type == ParamType.password,
          onChanged: (v) {
            widget.values[p.name] =
                p.type == ParamType.number ? (v.trim().isEmpty ? '' : num.tryParse(v.trim()) ?? '') : v;
            // Only rebuild when something else depends on this field.
            if (widget.params.any((o) => o.showIf?.containsKey(p.name) ?? false)) {
              setState(() {});
            } else {
              widget.onChanged?.call();
            }
          },
        ));
    }
  }
}

/// A row of preset swatches plus the current colour, standing in for
/// input[type=color] (Android has no native colour dialog).
class _ColorRow extends StatelessWidget {
  const _ColorRow({required this.value, required this.onChanged});

  final String value;
  final ValueChanged<String> onChanged;

  static const _swatches = [
    '#ff0000', '#ff7a00', '#ffd400', '#2bb673', '#2b7bd4',
    '#8d8ff2', '#d44bb0', '#000000', '#8a8a8a',
  ];

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return Wrap(
      spacing: 5,
      runSpacing: 5,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        for (final hex in _swatches)
          GestureDetector(
            onTap: () => onChanged(hex),
            child: Container(
              width: 22,
              height: 22,
              decoration: BoxDecoration(
                color: Color(
                    0xFF000000 | (int.tryParse(hex.substring(1), radix: 16) ?? 0)),
                border: Border.all(color: s.ink, width: 2),
                borderRadius: BorderRadius.circular(6),
                boxShadow: hardShadow(s.drop, 1),
              ),
              child: hex == value
                  ? Icon(Icons.check, size: 14, color: s.win)
                  : null,
            ),
          ),
      ],
    );
  }
}
