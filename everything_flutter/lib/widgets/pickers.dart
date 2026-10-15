/// The "drop files on me" panel and the file rows beneath it. On Android there
/// is nothing to drag, so the dropzone becomes the browse/gallery/camera entry
/// point — the panel keeps its shape from web/style.css .dropzone.
library;
import 'dart:io';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:path/path.dart' as pp;

import '../core/models.dart';
import '../core/theme.dart';
import '../engines/pdfeng.dart';
import 'mascot.dart';
import 'retro.dart';
import 'toast.dart';

/// Ask the system file browser for files.
///
/// Always opens with [FileType.any]. Android resolves `allowedExtensions` to
/// MIME types, and the odder ones this app accepts (tga, psd, exr, pnm…) have
/// no mapping, which makes the picker refuse to open at all. Filtering the
/// result ourselves is both reliable and friendlier: the user sees why a file
/// was skipped instead of being unable to find it.
Future<List<FileItem>> browseFiles({List<String>? extensions}) async {
  final picked = await FilePicker.pickFiles(type: FileType.any);
  final all = <FileItem>[
    for (final f in picked)
      if (f.path != null) await fileItem(f.path!),
  ];
  if (extensions == null || extensions.isEmpty) return all;

  final allowed = extensions.map((e) => e.replaceAll('.', '')).toSet();
  final kept = all.where((f) => allowed.contains(f.ext)).toList();
  final skipped = all.length - kept.length;
  if (skipped > 0) {
    toast('$skipped file(s) skipped — not a supported type here', error: true);
  }
  return kept;
}

/// Media types for the formats this app writes, so "Save a copy" hands Android
/// something it can file sensibly instead of a generic blob.
const _mimeTypes = {
  'pdf': 'application/pdf',
  'png': 'image/png',
  'jpg': 'image/jpeg',
  'jpeg': 'image/jpeg',
  'webp': 'image/webp',
  'gif': 'image/gif',
  'bmp': 'image/bmp',
  'tiff': 'image/tiff',
  'heic': 'image/heic',
  'svg': 'image/svg+xml',
  'txt': 'text/plain',
  'md': 'text/markdown',
  'html': 'text/html',
  'csv': 'text/csv',
  'tsv': 'text/tab-separated-values',
  'json': 'application/json',
  'xml': 'application/xml',
  'sql': 'application/sql',
  'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
};

String mimeFor(String ext) =>
    _mimeTypes[ext.toLowerCase()] ?? 'application/octet-stream';

/// Save a copy of a finished file wherever the user wants, through Android's
/// own "Save to" dialog. The app's output folder is not always somewhere
/// convenient, so this is the escape hatch.
Future<void> downloadFile(String path) async {
  final file = File(path);
  if (!file.existsSync()) {
    toast('That file is no longer there', error: true);
    return;
  }
  try {
    final saved = await FilePicker.saveFile(
      fileName: pp.basename(path),
      bytes: await file.readAsBytes(),
      mimeType: mimeFor(FileItem.extOf(path)),
      dialogTitle: 'Save a copy',
    );
    if (saved != null) toast('Saved ${pp.basename(path)}');
  } catch (e) {
    failToast(e);
  }
}

/// Pick images out of the gallery.
Future<List<FileItem>> pickFromGallery() async {
  final picked = await ImagePicker().pickMultiImage();
  return [for (final x in picked) await fileItem(x.path)];
}

Future<FileItem> fileItem(String path) async {
  final f = File(path);
  final name = pp.basename(path);
  return FileItem(
    path: path,
    name: name,
    ext: FileItem.extOf(name),
    size: await f.exists() ? await f.length() : 0,
  );
}

/// .dropzone — the big dashed panel with the mascot in the corner.
class Dropzone extends StatelessWidget {
  const Dropzone({
    super.key,
    required this.onAdd,
    this.accepts,
    this.extensions,
    this.showGallery = false,
  });

  final ValueChanged<List<FileItem>> onAdd;
  final String? accepts;
  final List<String>? extensions;
  final bool showGallery;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    final narrow = MediaQuery.sizeOf(context).width < 600;
    return RetroWindow(
      title: 'pick_files_here.exe',
      shadow: narrow ? 3 : 5,
      child: Padding(
        padding: EdgeInsets.all(narrow ? 10 : 14),
        child: Stack(
          children: [
            Container(
              width: double.infinity,
              padding: EdgeInsets.all(narrow ? 16 : 22),
              decoration: BoxDecoration(
                color: s.win2,
                border: Border.all(
                    color: s.inkSoft, width: 2, style: BorderStyle.solid),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Column(
                children: [
                  Text(
                    'pick files for me ✦',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontFamily: kPixel,
                      fontSize: 17,
                      fontWeight: FontWeight.w700,
                      color: s.titleInk,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    'Everything happens on this phone. Nothing is uploaded anywhere.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: s.muted, fontSize: 13),
                  ),
                  if (accepts != null) ...[
                    const SizedBox(height: 4),
                    Text(
                      'Accepts: $accepts',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: s.muted, fontSize: 12),
                    ),
                  ],
                  const SizedBox(height: 14),
                  Wrap(
                    alignment: WrapAlignment.center,
                    spacing: 10,
                    runSpacing: 10,
                    children: [
                      RetroButton(
                        label: 'Browse files',
                        icon: '📂',
                        onPressed: () async {
                          try {
                            final files = await browseFiles(extensions: extensions);
                            if (files.isNotEmpty) onAdd(files);
                          } catch (e) {
                            failToast(e);
                          }
                        },
                      ),
                      if (showGallery)
                        RetroButton(
                          label: 'Gallery',
                          icon: '🖼',
                          kind: BtnKind.ghost,
                          onPressed: () async {
                            try {
                              final files = await pickFromGallery();
                              if (files.isNotEmpty) onAdd(files);
                            } catch (e) {
                              failToast(e);
                            }
                          },
                        ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// .file — one row in a queue: thumbnail, name, size, and whatever goes right.
class FileRow extends StatelessWidget {
  const FileRow({
    super.key,
    required this.file,
    this.trailing,
    this.onRemove,
    this.index,
    this.reorderable = false,
    this.onTapThumb,
  });

  final FileItem file;
  final Widget? trailing;
  final VoidCallback? onRemove;
  final int? index;
  final bool reorderable;

  /// Tapping the preview is the obvious way into an editor, so the scanner
  /// wires it to Crop.
  final VoidCallback? onTapThumb;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return Container(
      margin: const EdgeInsets.only(bottom: 7),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      decoration: BoxDecoration(
        color: s.win,
        border: Border.all(color: file.bad ? s.err : s.inkSoft, width: 2),
        borderRadius: BorderRadius.circular(11),
        boxShadow: hardShadow(s.drop, 3),
      ),
      child: Row(
        children: [
          if (reorderable && index != null) ...[
            ReorderableDragStartListener(
              index: index!,
              child: Text('⋮⋮',
                  style: TextStyle(color: s.muted, fontSize: 15)),
            ),
            const SizedBox(width: 10),
          ],
          GestureDetector(
            onTap: onTapThumb,
            child: FileThumb(file: file),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  file.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontWeight: FontWeight.w800, color: s.text),
                ),
                Text(
                  '${file.ext.toUpperCase()} · ${file.sizeH}',
                  style: TextStyle(fontSize: 12, color: s.muted),
                ),
              ],
            ),
          ),
          // Flexible: on a narrow screen the format dropdown gives way rather
          // than pushing the row over its width.
          if (trailing != null) ...[
            const SizedBox(width: 8),
            Flexible(child: trailing!),
          ],
          if (onRemove != null)
            GestureDetector(
              onTap: onRemove,
              behavior: HitTestBehavior.opaque,
              child: SizedBox(
                width: 36,
                height: 36,
                child: Center(
                  child: Text('✕',
                      style: TextStyle(color: s.muted, fontSize: 15)),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// .thumb — shows a real preview for images and PDFs, else the extension.
class FileThumb extends StatefulWidget {
  const FileThumb({super.key, required this.file, this.size = 46});
  final FileItem file;
  final double size;

  @override
  State<FileThumb> createState() => _FileThumbState();
}

class _FileThumbState extends State<FileThumb> {
  Uint8List? _pdfThumb;

  static const _imageExts = [
    'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'heic', 'heif',
  ];

  @override
  void initState() {
    super.initState();
    if (widget.file.ext == 'pdf') _loadPdf();
  }

  Future<void> _loadPdf() async {
    final bytes = await PdfEngine.thumbnail(widget.file.path, width: 96);
    if (mounted && bytes != null) setState(() => _pdfThumb = bytes);
  }

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    Widget inner;
    if (_pdfThumb != null) {
      inner = Image.memory(_pdfThumb!, fit: BoxFit.cover);
    } else if (_imageExts.contains(widget.file.ext)) {
      inner = Image.file(
        File(widget.file.path),
        fit: BoxFit.cover,
        cacheWidth: (widget.size * 3).round(),
        errorBuilder: (_, _, _) => _label(s),
      );
    } else {
      inner = _label(s);
    }
    return Container(
      width: widget.size,
      height: widget.size,
      decoration: BoxDecoration(
        color: s.win3,
        border: Border.all(color: s.inkSoft, width: 2),
        borderRadius: BorderRadius.circular(9),
      ),
      clipBehavior: Clip.antiAlias,
      child: inner,
    );
  }

  Widget _label(Skin s) => Center(
        child: Text(
          widget.file.ext.toUpperCase(),
          style: TextStyle(
              fontFamily: kPixel, fontSize: 9, color: s.titleInk),
        ),
      );
}

/// The "N file(s) … Clear all" strip above a queue.
class FileActions extends StatelessWidget {
  const FileActions({
    super.key,
    required this.count,
    required this.onClear,
    this.note,
    this.extra,
  });

  final int count;
  final VoidCallback onClear;
  final String? note;
  final List<Widget>? extra;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return Padding(
      padding: const EdgeInsets.only(top: 16, bottom: 6),
      child: Wrap(
        spacing: 8,
        runSpacing: 8,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          Text('$count file(s)',
              style: TextStyle(
                  fontFamily: kPixel, fontSize: 13, color: s.titleInk)),
          if (note != null)
            Text(note!, style: TextStyle(fontSize: 12, color: s.muted)),
          ...?extra,
          RetroButton(
            label: 'Clear',
            kind: BtnKind.ghost,
            size: BtnSize.sm,
            onPressed: onClear,
          ),
        ],
      ),
    );
  }
}

/// The run bar at the bottom of every view.
class RunBar extends StatelessWidget {
  const RunBar({
    super.key,
    required this.label,
    required this.onRun,
    required this.outDir,
  });

  final String label;
  final VoidCallback? onRun;
  final String outDir;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return Padding(
      padding: const EdgeInsets.only(top: 18),
      child: Wrap(
        spacing: 14,
        runSpacing: 10,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          RetroButton(label: label, size: BtnSize.big, onPressed: onRun),
          Text('Saved to: $outDir',
              style: TextStyle(fontSize: 12, color: s.muted)),
        ],
      ),
    );
  }
}

/// Shared empty-state used by the tool pages.
class ViewScroll extends StatelessWidget {
  const ViewScroll({super.key, required this.children});
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.fromLTRB(2, 0, 2, 24),
        children: children,
      );
}

/// Keeps the mascot/empty block available to views that import this file.
Widget emptyBlock(String text, {String? sub}) =>
    MascotEmpty(text: text, sub: sub);
