/// convert.exe — queue files, pick a target format for each, run.
/// Port of renderConvert()/runConvert() in web/app.js.
library;
import 'package:flutter/material.dart';

import '../core/app_state.dart';
import '../core/jobs.dart';
import '../core/models.dart';
import '../core/registry.dart';
import '../core/theme.dart';
import '../widgets/params_form.dart';
import '../widgets/pickers.dart';
import '../widgets/retro.dart';
import '../widgets/toast.dart';

class ConvertView extends StatefulWidget {
  const ConvertView({super.key});

  @override
  State<ConvertView> createState() => _ConvertViewState();
}

class _ConvertViewState extends State<ConvertView> {
  final app = AppState.instance;
  final Map<String, Object?> _values = {};

  /// Which option groups apply to the chosen targets.
  List<ParamDef> get _params {
    final groups = <String>{};
    for (final f in app.convertFiles) {
      final tc = category(f.target);
      final sc = category(f.ext);
      if ((tc == 'image' || tc == 'gif') && (sc == 'doc' || sc == 'data')) {
        groups.add('from_pdf_image');
      } else if (tc == 'image' || tc == 'gif') {
        groups.add('image');
      }
    }
    final seen = <String>{};
    final out = <ParamDef>[];
    for (final g in groups) {
      for (final p in convertParams[g] ?? const <ParamDef>[]) {
        if (seen.add(p.name)) out.add(p);
      }
    }
    return out;
  }

  void _run() {
    final ready =
        app.convertFiles.where((f) => f.target.isNotEmpty && !f.bad).toList();
    if (ready.isEmpty) return;

    for (final f in ready) {
      JobQueue.instance.submit(
        title: '${f.name} → ${f.target.toUpperCase()}',
        files: [f],
        params: Map.of(_values),
        outDir: app.outDir,
        body: (call) => runRoute(f, f.target, call),
      );
    }
    toast('Started converting ${ready.length} file(s)');
    app.convertFiles.removeWhere((f) => ready.contains(f));
    app.setJobsOpen(true);
    setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final files = app.convertFiles;
    final params = _params;

    return ViewScroll(
      children: [
        Dropzone(
          onAdd: (f) => setState(() => app.addFiles(f)),
          showGallery: true,
        ),
        if (files.isEmpty) ...[
          const SectionLabel('What can it do?'),
          const _CapabilityGrid(),
        ] else ...[
          _bulkActions(files),
          for (final f in files) _row(f),
          if (params.isNotEmpty) ...[
            const SizedBox(height: 14),
            RetroCard(
              title: 'options.ini',
              child: ParamsForm(params: params, values: _values),
            ),
          ],
          RunBar(
            label:
                'Convert ${files.where((f) => f.target.isNotEmpty && !f.bad).length} file(s)',
            outDir: app.outDir,
            onRun: files.any((f) => f.target.isNotEmpty && !f.bad) ? _run : null,
          ),
        ],
      ],
    );
  }

  /// The "All JPG → …" chips for each input type present more than once.
  Widget _bulkActions(List<FileItem> files) {
    final byExt = <String, List<FileItem>>{};
    for (final f in files) {
      byExt.putIfAbsent(f.ext, () => []).add(f);
    }
    return FileActions(
      count: files.length,
      onClear: () => setState(() => app.convertFiles.clear()),
      extra: [
        for (final e in byExt.entries)
          if (e.value.length > 1 && targetsFor(e.key).isNotEmpty)
            _GroupSet(
              ext: e.key,
              value: e.value.first.target,
              onChanged: (t) => setState(() {
                for (final f in e.value) {
                  f.target = t;
                }
                app.rememberTarget(e.key, t);
              }),
            ),
      ],
    );
  }

  Widget _row(FileItem f) {
    final s = context.skin;
    final targets = targetsFor(f.ext);
    return FileRow(
      file: f,
      onRemove: () => setState(() => app.convertFiles.remove(f)),
      trailing: targets.isEmpty
          ? Text('No converter for this type',
              style: TextStyle(fontSize: 12, color: s.muted))
          : Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text('→',
                    style: TextStyle(
                        color: s.accent, fontWeight: FontWeight.w800)),
                const SizedBox(width: 8),
                // Flexible, not a fixed box: the dropdown has to be able to
                // shrink on a 320px screen.
                Flexible(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 130),
                    child: TargetSelect(
                      targets: targets,
                      value: f.target,
                      onChanged: (t) => setState(() {
                        f.target = t;
                        app.rememberTarget(f.ext, t);
                      }),
                    ),
                  ),
                ),
              ],
            ),
    );
  }
}

/// A target dropdown, grouped by category like the web <optgroup>s.
class TargetSelect extends StatelessWidget {
  const TargetSelect({
    super.key,
    required this.targets,
    required this.value,
    required this.onChanged,
    this.dense = false,
  });

  final List<String> targets;
  final String value;
  final ValueChanged<String> onChanged;
  final bool dense;

  static const _catNames = {
    'image': 'Images',
    'gif': 'Animated',
    'doc': 'Documents',
    'data': 'Sheets & data',
    'other': 'Other',
  };

  @override
  Widget build(BuildContext context) {
    // Group, then flatten with the group name on the first of each run.
    final groups = <String, List<String>>{};
    for (final t in targets) {
      groups.putIfAbsent(category(t), () => []).add(t);
    }
    final items = <(String, String)>[];
    for (final g in groups.entries) {
      for (var i = 0; i < g.value.length; i++) {
        final label = i == 0
            ? '${g.value[i].toUpperCase()}  ·  ${_catNames[g.key] ?? g.key}'
            : g.value[i].toUpperCase();
        items.add((g.value[i], label));
      }
    }
    return RetroSelect<String>(
      value: value,
      items: items,
      onChanged: onChanged,
      dense: dense,
    );
  }
}

/// .group-set — the rounded "All PNG → JPG" pill.
class _GroupSet extends StatelessWidget {
  const _GroupSet(
      {required this.ext, required this.value, required this.onChanged});
  final String ext;
  final String value;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 3, 3, 3),
      decoration: BoxDecoration(
        color: s.win,
        border: Border.all(color: s.inkSoft, width: 2),
        borderRadius: BorderRadius.circular(99),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text('All ${ext.toUpperCase()} →',
              style: TextStyle(
                  fontSize: 12, fontWeight: FontWeight.w700, color: s.text)),
          const SizedBox(width: 6),
          TargetSelect(
            targets: targetsFor(ext),
            value: value,
            onChanged: onChanged,
            dense: true,
          ),
        ],
      ),
    );
  }
}

/// The "What can it do?" grid shown while the queue is empty.
class _CapabilityGrid extends StatelessWidget {
  const _CapabilityGrid();

  static const _cards = [
    ['▧', 'Images', 'JPG · PNG · WebP · HEIC · GIF · TIFF · BMP · ICO · SVG → PDF'],
    ['▤', 'Documents', 'PDF → Word/text/HTML/Markdown · Markdown · HTML · TXT → PDF'],
    ['▦', 'Spreadsheets', 'XLSX · CSV · TSV · JSON · XML · SQL · Markdown tables · PDF'],
    ['📷', 'Scan', 'Snap pages with the camera or pick photos, get one tidy PDF'],
    ['⇲', 'Compress', 'Shrink any file by a % or to an exact size: photos, video, audio, PDFs, Office'],
    ['✦', 'Tools', 'Merge/split PDFs, resize photos, edit PDFs, free up space'],
  ];

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, box) {
        final columns = (box.maxWidth / 230).floor().clamp(1, 4);
        // Six full cards stacked is a lot of scrolling on a phone, so one
        // column gets a compact list in a single window instead.
        if (columns == 1) return _compact(context);
        final width = (box.maxWidth - (columns - 1) * 16) / columns;
        return Wrap(
          spacing: 16,
          runSpacing: 16,
          children: [
            for (final c in _cards)
              SizedBox(
                width: width,
                child: ToolCardTile(
                  icon: c[0],
                  title: c[1],
                  subtitle: c[2],
                  accent: _accent(context, _cards.indexOf(c)),
                ),
              ),
          ],
        );
      },
    );
  }

  Widget _compact(BuildContext context) {
    final s = context.skin;
    return RetroWindow(
      title: 'what_it_does.txt',
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (var i = 0; i < _cards.length; i++) ...[
              if (i > 0) const Padding(
                padding: EdgeInsets.symmetric(vertical: 8),
                child: DashedDivider(),
              ),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  TileIcon(_cards[i][0],
                      color: _accent(context, i), size: 30, fontSize: 14),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(_cards[i][1],
                            style: TextStyle(
                                fontWeight: FontWeight.w800, color: s.text)),
                        const SizedBox(height: 2),
                        Text(_cards[i][2],
                            style:
                                TextStyle(fontSize: 12, color: s.muted)),
                      ],
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  Color _accent(BuildContext context, int i) {
    final s = context.skin;
    return [s.lilac, s.pink, s.mint, s.butter, s.sky, s.peach][i % 6];
  }
}
