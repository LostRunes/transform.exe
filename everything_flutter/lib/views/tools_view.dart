/// pdf_tools.exe / image_tools.exe / spreadsheets.exe — the tool grid and the
/// page you land on after picking one. Port of renderToolGrid/renderToolPage.
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

class ToolsView extends StatefulWidget {
  const ToolsView({super.key, required this.category});
  final String category;

  @override
  State<ToolsView> createState() => _ToolsViewState();
}

class _ToolsViewState extends State<ToolsView> {
  final app = AppState.instance;
  final Map<String, Map<String, Object?>> _values = {};

  @override
  Widget build(BuildContext context) {
    final tool = app.currentTool;
    if (tool == null || tool.cat != widget.category) return _grid();
    return _ToolPage(
      tool: tool,
      values: _values.putIfAbsent(tool.id, () => {}),
      onBack: () => setState(() => app.openTool(null)),
      onChanged: () => setState(() {}),
    );
  }

  Widget _grid() {
    final s = context.skin;
    final list = tools.where((t) => t.cat == widget.category).toList();
    return ViewScroll(
      children: [
        LayoutBuilder(
          builder: (context, box) {
            final columns = (box.maxWidth / 230).floor().clamp(1, 4);
            final width = columns == 1
                ? box.maxWidth
                : (box.maxWidth - (columns - 1) * 16) / columns;
            return Wrap(
              spacing: 16,
              runSpacing: 16,
              children: [
                for (var i = 0; i < list.length; i++)
                  SizedBox(
                    width: width,
                    child: ToolCardTile(
                      icon: list[i].icon,
                      title: list[i].name,
                      subtitle: list[i].desc.isNotEmpty
                          ? list[i].desc
                          : _shortAccepts(list[i]),
                      accent: [s.lilac, s.pink, s.mint, s.butter, s.sky, s.peach]
                          [i % 6],
                      dimmed: !list[i].available,
                      onTap: list[i].available
                          ? () => setState(() => app.openTool(list[i]))
                          : () => toast(list[i].unavailableNote, error: true),
                    ),
                  ),
              ],
            );
          },
        ),
        if (widget.category == 'PDF') ...[
          const SectionLabel('Annotate & draw on a PDF'),
          ToolCardTile(
            icon: '✎',
            title: 'Open the PDF editor',
            subtitle: 'Add text, shapes, arrows, freehand, highlights and '
                'whiteout, then save a copy.',
            accent: s.butter,
            onTap: () => app.route('editor'),
          ),
        ],
        if (widget.category == 'PDF' ||
            widget.category == 'Data' ||
            widget.category == 'Image')
          Padding(
            padding: const EdgeInsets.only(top: 18),
            child: Wrap(
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text('Format changes (e.g. PDF → Word, Excel → CSV) are on the ',
                    style: TextStyle(fontSize: 12, color: s.muted)),
                GestureDetector(
                  onTap: () => app.route('convert'),
                  child: Text('Convert',
                      style: TextStyle(
                          fontSize: 12,
                          color: s.accent,
                          fontWeight: FontWeight.w800)),
                ),
                Text(' page.', style: TextStyle(fontSize: 12, color: s.muted)),
              ],
            ),
          ),
      ],
    );
  }

  static String _shortAccepts(ToolDef t) {
    if (t.inputs.contains('*')) return 'Any file';
    final shown = t.inputs.take(8).map((e) => e.toUpperCase()).join(', ');
    return shown + (t.inputs.length > 8 ? '…' : '');
  }
}

class _ToolPage extends StatefulWidget {
  const _ToolPage({
    required this.tool,
    required this.values,
    required this.onBack,
    required this.onChanged,
  });

  final ToolDef tool;
  final Map<String, Object?> values;
  final VoidCallback onBack;
  final VoidCallback onChanged;

  @override
  State<_ToolPage> createState() => _ToolPageState();
}

class _ToolPageState extends State<_ToolPage> {
  final app = AppState.instance;

  List<FileItem> get _files =>
      app.toolFiles.putIfAbsent(widget.tool.id, () => []);

  void _run() {
    final t = widget.tool;
    final files = List<FileItem>.from(_files);
    JobQueue.instance.submit(
      title: t.name,
      files: files,
      params: Map.of(widget.values),
      outDir: app.outDir,
      body: t.run,
    );
    toast('Started: ${t.name}');
    app.toolFiles[t.id] = [];
    app.setJobsOpen(true);
    setState(() {});
  }

  static const _units = {'KB': 1024, 'MB': 1024 * 1024, 'GB': 1024 * 1024 * 1024};

  /// One line saying what the size controls will aim for, given the files so far.
  String? _estimate(List<FileItem> files) {
    final v = widget.values;
    if (!widget.tool.params.any((p) => p.name == 'size_mode')) return null;
    if (v['size_mode'] == 'target') {
      final n = v['target_size'];
      final limit = (n is num ? n : 0) * (_units[v['target_unit']] ?? _units['MB']!);
      if (limit <= 0) return 'Type a size to aim for.';
      final under = files.where((f) => f.size <= limit).length;
      return 'Each file will be made ${humanSize(limit)} or smaller.'
          '${under > 0 ? ' $under already fit${under > 1 ? '' : 's'} and will be copied as-is.' : ''}';
    }
    if (v['size_mode'] == 'percent' && files.isNotEmpty) {
      final total = files.fold<int>(0, (a, f) => a + f.size);
      final pct = v['reduce_pct'] is num ? v['reduce_pct'] as num : 50;
      return '≈ ${humanSize(total)} → ${humanSize(total * (100 - pct) / 100)} in total';
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final t = widget.tool;
    final s = context.skin;
    final files = _files;
    // Merge-style tools need at least two files; the rest need one.
    final minimum = t.multi ? 2 : 1;

    return ViewScroll(
      children: [
        GestureDetector(
          onTap: widget.onBack,
          child: Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Text(
              '← All ${t.cat} tools',
              style: TextStyle(
                  fontFamily: kPixel, fontSize: 12, color: s.accent),
            ),
          ),
        ),
        Row(
          children: [
            TileIcon(t.icon, color: s.pink, size: 48, fontSize: 21),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(t.name,
                      style: TextStyle(
                        fontFamily: kPixel,
                        fontSize: 17,
                        fontWeight: FontWeight.w700,
                        color: s.titleInk,
                      )),
                  if (t.desc.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Text(t.desc,
                          style: TextStyle(color: s.muted, fontSize: 13)),
                    ),
                ],
              ),
            ),
          ],
        ),
        const SizedBox(height: 16),
        Dropzone(
          onAdd: (picked) {
            final any = t.inputs.contains('*');
            final ok = picked
                .where((f) =>
                    any || t.inputs.contains(f.ext) || t.inputs.contains(norm(f.ext)))
                .toList();
            if (ok.length < picked.length) {
              toast('${picked.length - ok.length} file(s) skipped: not '
                  'supported by "${t.name}"', error: true);
            }
            setState(() => files.addAll(ok));
          },
          accepts: _ToolsViewState._shortAccepts(t),
          extensions: t.inputs.contains('*') ? null : t.inputs,
          showGallery: t.inputs.contains('jpg') || t.inputs.contains('*'),
        ),
        if (files.isNotEmpty) ...[
          FileActions(
            count: files.length,
            note: t.multi ? 'Drag ⋮⋮ to set the order' : null,
            onClear: () => setState(() => files.clear()),
          ),
          if (t.multi)
            ReorderableListView(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              buildDefaultDragHandles: false,
              onReorder: (from, to) => setState(() {
                if (to > from) to -= 1;
                files.insert(to, files.removeAt(from));
              }),
              children: [
                for (var i = 0; i < files.length; i++)
                  FileRow(
                    key: ValueKey(files[i].path + i.toString()),
                    file: files[i],
                    index: i,
                    reorderable: true,
                    onRemove: () => setState(() => files.removeAt(i)),
                  ),
              ],
            )
          else
            for (final f in files)
              FileRow(
                file: f,
                onRemove: () => setState(() => files.remove(f)),
              ),
        ],
        if (t.params.isNotEmpty) ...[
          const SizedBox(height: 14),
          RetroCard(
            title: 'settings.ini',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                ParamsForm(
                  params: t.params,
                  values: widget.values,
                  onChanged: () => setState(() {}),
                ),
                if (_estimate(files) case final est?)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: Text(est,
                        style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w800,
                            color: s.accent)),
                  ),
              ],
            ),
          ),
        ],
        RunBar(
          label: t.name,
          outDir: app.outDir,
          onRun: files.length >= minimum ? _run : null,
        ),
        if (files.isNotEmpty && files.length < minimum)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text('Add at least $minimum files for this one.',
                style: TextStyle(fontSize: 12, color: s.muted)),
          ),
      ],
    );
  }
}
