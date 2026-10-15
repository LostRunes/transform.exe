/// clean_up.exe — storage overview, app cache, and the clutter finder
/// (duplicates / large files / empty folders) over a folder you choose.
///
/// Android has no Recycle Bin, so unlike the desktop build these deletes are
/// permanent. The confirm dialog says so rather than promising an undo.
library;

import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:open_filex/open_filex.dart';

import '../core/app_state.dart';
import '../core/fs.dart';
import '../core/models.dart';
import '../core/theme.dart';
import '../widgets/mascot.dart';
import '../widgets/pickers.dart';
import '../widgets/retro.dart';
import '../widgets/toast.dart';

enum ScanKind { duplicates, large, empty }

class CleanupView extends StatefulWidget {
  const CleanupView({super.key});

  @override
  State<CleanupView> createState() => _CleanupViewState();
}

class _CleanupViewState extends State<CleanupView> {
  final app = AppState.instance;

  ScanKind _kind = ScanKind.duplicates;
  int _cacheBytes = 0;
  bool _loadingOverview = true;

  String _folder = '';
  final _minController = TextEditingController(text: '1');
  bool _scanning = false;

  List<List<String>> _dupGroups = [];
  List<(String, int)> _bigFiles = [];
  List<String> _emptyDirs = [];
  final Set<String> _checked = {};
  String _summary = '';

  @override
  void initState() {
    super.initState();
    _folder = app.getString('cleanFolder') ?? '';
    _overview();
  }

  @override
  void dispose() {
    _minController.dispose();
    super.dispose();
  }

  Future<void> _overview() async {
    setState(() => _loadingOverview = true);
    final size = await Fs.cacheSize();
    if (mounted) {
      setState(() {
        _cacheBytes = size;
        _loadingOverview = false;
      });
    }
  }

  Future<void> _scan() async {
    if (_folder.isEmpty) {
      toast('Choose a folder to scan', error: true);
      return;
    }
    if (!await Fs.ensureStorage()) {
      toast('Storage permission is needed to scan files', error: true);
      return;
    }
    app.putString('cleanFolder', _folder);
    setState(() {
      _scanning = true;
      _dupGroups = [];
      _bigFiles = [];
      _emptyDirs = [];
      _checked.clear();
      _summary = '';
    });
    try {
      final min = int.tryParse(_minController.text.trim()) ?? 1;
      switch (_kind) {
        case ScanKind.duplicates:
          await _findDuplicates(min * 1024);
        case ScanKind.large:
          await _findLarge(min * 1024 * 1024);
        case ScanKind.empty:
          await _findEmpty();
      }
    } catch (e) {
      failToast(e);
    }
    if (mounted) setState(() => _scanning = false);
  }

  /// Group by size first, then hash only the candidates — the same trick the
  /// desktop version uses to avoid reading every byte on disk.
  Future<void> _findDuplicates(int minBytes) async {
    final bySize = <int, List<String>>{};
    await for (final f in _walk(_folder)) {
      final len = await f.length().catchError((_) => 0);
      if (len < minBytes) continue;
      bySize.putIfAbsent(len, () => []).add(f.path);
    }
    final groups = <List<String>>[];
    var wasted = 0;
    for (final entry in bySize.entries) {
      if (entry.value.length < 2) continue;
      final byHash = <String, List<String>>{};
      for (final path in entry.value) {
        try {
          final digest = md5.convert(await File(path).readAsBytes()).toString();
          byHash.putIfAbsent(digest, () => []).add(path);
        } catch (_) {
          // Unreadable file; skip it rather than failing the whole scan.
        }
      }
      for (final dupes in byHash.values) {
        if (dupes.length < 2) continue;
        groups.add(dupes);
        wasted += entry.key * (dupes.length - 1);
        // Everything but the first copy starts ticked.
        _checked.addAll(dupes.skip(1));
      }
    }
    setState(() {
      _dupGroups = groups;
      _summary = groups.isEmpty
          ? 'No duplicates found 🎉'
          : '${groups.length} duplicate groups · ${humanSize(wasted)} reclaimable. '
              'The first copy in each group is kept unless you tick it.';
    });
  }

  Future<void> _findLarge(int minBytes) async {
    final found = <(String, int)>[];
    await for (final f in _walk(_folder)) {
      final len = await f.length().catchError((_) => 0);
      if (len >= minBytes) found.add((f.path, len));
    }
    found.sort((a, b) => b.$2.compareTo(a.$2));
    setState(() {
      _bigFiles = found;
      _summary = found.isEmpty
          ? 'No files above that size.'
          : '${found.length} large files (biggest first). Tick the ones you want gone.';
    });
  }

  Future<void> _findEmpty() async {
    final found = <String>[];
    final root = Directory(_folder);
    if (!root.existsSync()) throw Exception('That folder does not exist');
    await for (final e in root.list(recursive: true, followLinks: false)) {
      if (e is! Directory) continue;
      try {
        if (e.listSync().isEmpty) found.add(e.path);
      } catch (_) {
        // Permission denied; leave it alone.
      }
    }
    setState(() {
      _emptyDirs = found;
      _checked.addAll(found);
      _summary =
          found.isEmpty ? 'No empty folders.' : '${found.length} empty folders.';
    });
  }

  Stream<File> _walk(String root) async* {
    final dir = Directory(root);
    if (!dir.existsSync()) throw Exception('That folder does not exist');
    await for (final e in dir.list(recursive: true, followLinks: false)) {
      if (e is File) yield e;
    }
  }

  Future<void> _deleteChecked() async {
    if (_checked.isEmpty) {
      toast('Nothing selected');
      return;
    }
    final ok = await ask(
      context,
      'Permanently delete ${_checked.length} item(s)? Android has no Recycle '
      'Bin, so this cannot be undone.',
      danger: true,
      yes: 'Delete',
    );
    if (!ok) return;

    var freed = 0;
    var failed = 0;
    for (final path in _checked.toList()) {
      try {
        final file = File(path);
        if (file.existsSync()) {
          freed += await file.length();
          await file.delete();
        } else {
          final d = Directory(path);
          if (d.existsSync()) await d.delete();
        }
        _dupGroups = [
          for (final g in _dupGroups)
            [for (final p in g) if (p != path) p]
        ]..removeWhere((g) => g.length < 2);
        _bigFiles.removeWhere((e) => e.$1 == path);
        _emptyDirs.remove(path);
      } catch (_) {
        failed++;
      }
    }
    setState(_checked.clear);
    toast('Freed ${humanSize(freed)}'
        '${failed > 0 ? ' · $failed could not be deleted' : ''}');
  }

  @override
  Widget build(BuildContext context) {
    return ViewScroll(
      children: [
        LayoutBuilder(
          builder: (context, box) {
            final two = box.maxWidth >= 640;
            final width = two ? (box.maxWidth - 16) / 2 : box.maxWidth;
            return Wrap(
              spacing: 16,
              runSpacing: 16,
              children: [
                SizedBox(width: width, child: _storageCard()),
                SizedBox(width: width, child: _cacheCard()),
              ],
            );
          },
        ),
        const SizedBox(height: 16),
        _finderCard(),
      ],
    );
  }

  Widget _storageCard() {
    final s = context.skin;
    return RetroCard(
      title: 'storage.sys',
      child: FutureBuilder<_DiskInfo>(
        future: _diskInfo(),
        builder: (context, snap) {
          if (!snap.hasData) {
            return Row(children: [
              const RetroSpinner(),
              const SizedBox(width: 10),
              Text('measuring…', style: TextStyle(color: s.muted)),
            ]);
          }
          final d = snap.data!;
          final used = d.total == 0 ? 0.0 : (d.total - d.free) / d.total;
          final low = d.total > 0 && d.free / d.total < 0.1;
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text('Internal storage',
                      style: TextStyle(
                          fontWeight: FontWeight.w800, color: s.text)),
                  Text(
                    d.total == 0
                        ? 'unavailable'
                        : '${humanSize(d.free)} free of ${humanSize(d.total)}',
                    style: TextStyle(fontSize: 12, color: s.muted),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              RetroBar(value: used, height: 16, color: low ? s.err : s.accent),
              if (low) ...[
                const SizedBox(height: 4),
                Text('Almost full: big conversions may run out of space.',
                    style: TextStyle(fontSize: 12, color: s.err)),
              ],
            ],
          );
        },
      ),
    );
  }

  Widget _cacheCard() {
    final s = context.skin;
    return RetroCard(
      title: 'app_cache.tmp',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text('Scratch files left over from conversions and camera captures.',
              style: TextStyle(fontSize: 12, color: s.muted)),
          const SizedBox(height: 6),
          Text(
            _loadingOverview ? '…' : humanSize(_cacheBytes),
            style: TextStyle(
                fontFamily: kPixel, fontSize: 26, color: s.titleInk),
          ),
          const SizedBox(height: 10),
          RetroButton(
            label: 'Clear app cache',
            kind: BtnKind.ghost,
            onPressed: () async {
              final before = _cacheBytes;
              await Fs.wipeScratch();
              try {
                final scans = Directory('${Fs.cacheDir.path}/scans');
                if (scans.existsSync()) await scans.delete(recursive: true);
              } catch (_) {
                // Still in use; it'll clear next time.
              }
              await _overview();
              toast('Freed ${humanSize(before - _cacheBytes)}');
            },
          ),
        ],
      ),
    );
  }

  Widget _finderCard() {
    final s = context.skin;
    final minLabel =
        {ScanKind.duplicates: 'Min KB', ScanKind.large: 'Min MB'}[_kind];

    return RetroCard(
      title: 'find_clutter.exe',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            'Pick a folder and see what is wasting space. Deleting is '
            'permanent on Android, so check before you tick.',
            style: TextStyle(fontSize: 12, color: s.muted),
          ),
          const SizedBox(height: 12),
          // .tabs — scrolls sideways, because all three labels do not fit
          // across a phone.
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Container(
              padding: const EdgeInsets.all(3),
              decoration: BoxDecoration(
                color: s.win2,
                border: Border.all(color: s.inkSoft, width: 2),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  for (final e in const {
                    ScanKind.duplicates: 'Duplicate files',
                    ScanKind.large: 'Large files',
                    ScanKind.empty: 'Empty folders',
                  }.entries)
                    GestureDetector(
                      onTap: () => setState(() {
                        _kind = e.key;
                        _minController.text =
                            e.key == ScanKind.large ? '100' : '1';
                        _summary = '';
                        _dupGroups = [];
                        _bigFiles = [];
                        _emptyDirs = [];
                        _checked.clear();
                      }),
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 14, vertical: 5),
                        decoration: BoxDecoration(
                          color: _kind == e.key ? s.win : Colors.transparent,
                          borderRadius: BorderRadius.circular(7),
                          border: Border.all(
                            color: _kind == e.key ? s.ink : Colors.transparent,
                            width: 2,
                          ),
                        ),
                        child: Text(e.value,
                            style: TextStyle(
                              fontWeight: FontWeight.w800,
                              fontSize: 13,
                              color: _kind == e.key ? s.text : s.muted,
                            )),
                      ),
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          _accessNotice(s),
          const SizedBox(height: 10),
          // Quick picks, because the system folder picker will not hand over
          // Download or the storage root at all.
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final path in Fs.commonFolders())
                GestureDetector(
                  onTap: () => setState(() => _folder = path),
                  child: Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                    decoration: BoxDecoration(
                      color: _folder == path ? s.sel : s.win2,
                      border: Border.all(
                          color: _folder == path ? s.ink : s.inkSoft, width: 2),
                      borderRadius: BorderRadius.circular(99),
                    ),
                    child: Text(
                      path.split('/').last,
                      style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                          color: s.text),
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 320, minWidth: 180),
                child: Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
                  decoration: BoxDecoration(
                    color: s.win2,
                    border: Border.all(color: s.inkSoft, width: 2),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    _folder.isEmpty ? 'No folder chosen yet' : _folder,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 12.5,
                      fontFamily: 'monospace',
                      color: _folder.isEmpty ? s.muted : s.text,
                    ),
                  ),
                ),
              ),
              RetroButton(
                label: 'Browse…',
                kind: BtnKind.ghost,
                onPressed: () async {
                  final dir = await FilePicker.getDirectoryPath(
                      dialogTitle: 'Folder to scan');
                  if (dir != null) setState(() => _folder = dir);
                },
              ),
              if (minLabel != null) ...[
                Text(minLabel,
                    style: TextStyle(fontSize: 12, color: s.muted)),
                SizedBox(
                  width: 90,
                  child: RetroField(controller: _minController, number: true),
                ),
              ],
              RetroButton(
                label: _scanning ? 'Scanning…' : 'Scan',
                onPressed: _scanning ? null : _scan,
              ),
            ],
          ),
          const SizedBox(height: 14),
          if (_scanning)
            Row(children: [
              const RetroSpinner(),
              const SizedBox(width: 10),
              Text('Scanning… big folders can take a while',
                  style: TextStyle(color: s.muted)),
            ])
          else
            _results(),
        ],
      ),
    );
  }

  /// Explains the folder-picker refusal and offers the only real way around it.
  Widget _accessNotice(Skin s) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: s.win2,
        border: Border.all(color: s.inkSoft, width: 2),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text('What can be scanned?',
              style: TextStyle(fontWeight: FontWeight.w800, color: s.text)),
          const SizedBox(height: 4),
          Text(
            'Android lets apps look through your photos and videos (DCIM, '
            'Pictures, Movies…) and the folders you pick. It keeps other apps\' '
            'private files hidden, so those are never scanned. Nothing is ever '
            'uploaded, and anything you remove is deleted only after you confirm.',
            style: TextStyle(fontSize: 12, color: s.muted),
          ),
        ],
      ),
    );
  }

  Widget _results() {
    final s = context.skin;
    final hasAny =
        _dupGroups.isNotEmpty || _bigFiles.isNotEmpty || _emptyDirs.isNotEmpty;
    if (_summary.isEmpty) {
      return const MascotEmpty(
        text: 'nothing scanned yet~',
        sub: 'Pick a folder and hit Scan.',
        width: 80,
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        Wrap(
          spacing: 10,
          runSpacing: 10,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Text(_summary, style: TextStyle(color: s.muted)),
            ),
            if (hasAny)
              RetroButton(
                label: 'Delete selected',
                kind: BtnKind.danger,
                onPressed: _deleteChecked,
              ),
          ],
        ),
        const SizedBox(height: 10),
        ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 520),
          child: ListView(
            shrinkWrap: true,
            children: [
              for (final g in _dupGroups.take(500))
                Container(
                  margin: const EdgeInsets.only(bottom: 8),
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  decoration: BoxDecoration(
                    color: s.win2,
                    border: Border.all(color: s.inkSoft, width: 2),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text('${g.length} copies',
                          style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w700,
                              color: s.muted)),
                      for (var i = 0; i < g.length; i++)
                        _resultRow(g[i], keep: i == 0),
                    ],
                  ),
                ),
              for (final f in _bigFiles) _resultRow(f.$1, size: f.$2),
              for (final d in _emptyDirs) _resultRow(d),
            ],
          ),
        ),
      ],
    );
  }

  Widget _resultRow(String path, {int? size, bool keep = false}) {
    final s = context.skin;
    final on = _checked.contains(path);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          SizedBox(
            width: 24,
            height: 24,
            child: Checkbox(
              value: on,
              onChanged: (v) => setState(() {
                v == true ? _checked.add(path) : _checked.remove(path);
              }),
              activeColor: s.accent,
              side: BorderSide(color: s.ink, width: 2),
              materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              path,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 12.5, color: s.text),
            ),
          ),
          if (keep)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 6),
              child: Text('KEEP',
                  style: TextStyle(
                      fontFamily: kPixel, fontSize: 9, color: s.ok)),
            ),
          if (size != null)
            Text(humanSize(size),
                style: TextStyle(fontSize: 12, color: s.muted)),
          const SizedBox(width: 8),
          GestureDetector(
            onTap: () => OpenFilex.open(path),
            child: Text('Open',
                style: TextStyle(
                    fontSize: 12,
                    color: s.accent,
                    fontWeight: FontWeight.w800)),
          ),
        ],
      ),
    );
  }

  Future<_DiskInfo> _diskInfo() async {
    // StatFs isn't exposed to Dart; read the numbers the VM already has.
    try {
      final stat = await Process.run('df', ['-k', Fs.docsDir.path]);
      final lines = stat.stdout.toString().trim().split('\n');
      if (lines.length >= 2) {
        final parts = lines.last.split(RegExp(r'\s+'));
        if (parts.length >= 4) {
          final total = (int.tryParse(parts[1]) ?? 0) * 1024;
          final free = (int.tryParse(parts[3]) ?? 0) * 1024;
          return _DiskInfo(total, free);
        }
      }
    } catch (_) {
      // df is missing or blocked; fall through to "unavailable".
    }
    return const _DiskInfo(0, 0);
  }
}

class _DiskInfo {
  const _DiskInfo(this.total, this.free);
  final int total;
  final int free;
}
