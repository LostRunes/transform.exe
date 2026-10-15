/// Document engine: txt / md / html / docx, and all of them to PDF.
/// DOCX is read and written as raw OOXML through `archive`, so there is no
/// Office dependency — the desktop build's Word/Excel COM path has no
/// equivalent on Android.
library;
import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:xml/xml.dart';

import '../core/fs.dart';
import '../core/models.dart';

class DocEngine {
  // ---------------------------------------------------------------- read

  /// Pull the visible text out of a .docx, one string per paragraph.
  static Future<List<String>> docxParagraphs(String path) async {
    final bytes = await File(path).readAsBytes();
    final zip = ZipDecoder().decodeBytes(bytes);
    final entry = zip.files.where((f) => f.name == 'word/document.xml');
    if (entry.isEmpty) {
      throw Exception('That .docx has no document body — it may be corrupt');
    }
    final xml = XmlDocument.parse(utf8.decode(entry.first.content as List<int>));
    final paras = <String>[];
    for (final p in xml.findAllElements('w:p')) {
      final buf = StringBuffer();
      for (final node in p.descendantElements) {
        if (node.name.qualified == 'w:t') {
          buf.write(node.innerText);
        } else if (node.name.qualified == 'w:tab') {
          buf.write('\t');
        } else if (node.name.qualified == 'w:br') {
          buf.write('\n');
        }
      }
      paras.add(buf.toString());
    }
    return paras;
  }

  static Future<String> readText(String path) async {
    final ext = FileItem.extOf(path);
    if (ext == 'docx' || ext == 'docm') {
      return (await docxParagraphs(path)).join('\n');
    }
    if (ext == 'html' || ext == 'htm') {
      return htmlToText(await File(path).readAsString());
    }
    return File(path).readAsString();
  }

  // ---------------------------------------------------------------- markup

  /// Small Markdown subset: headings, bold/italic/code, lists, links, rules.
  static String mdToHtml(String md) {
    final out = StringBuffer();
    var inList = false;
    var inCode = false;
    for (final raw in const LineSplitter().convert(md)) {
      final line = raw.trimRight();
      if (line.trimLeft().startsWith('```')) {
        out.writeln(inCode ? '</pre>' : '<pre>');
        inCode = !inCode;
        continue;
      }
      if (inCode) {
        out.writeln(esc(line));
        continue;
      }
      final bullet = RegExp(r'^\s*[-*+]\s+(.*)$').firstMatch(line);
      if (bullet != null) {
        if (!inList) {
          out.writeln('<ul>');
          inList = true;
        }
        out.writeln('<li>${_inline(bullet.group(1)!)}</li>');
        continue;
      }
      if (inList) {
        out.writeln('</ul>');
        inList = false;
      }
      if (line.trim().isEmpty) continue;
      if (RegExp(r'^\s*(-{3,}|\*{3,})\s*$').hasMatch(line)) {
        out.writeln('<hr>');
        continue;
      }
      final head = RegExp(r'^(#{1,6})\s+(.*)$').firstMatch(line);
      if (head != null) {
        final n = head.group(1)!.length;
        out.writeln('<h$n>${_inline(head.group(2)!)}</h$n>');
        continue;
      }
      out.writeln('<p>${_inline(line)}</p>');
    }
    if (inList) out.writeln('</ul>');
    if (inCode) out.writeln('</pre>');
    return out.toString();
  }

  static String _inline(String s) {
    var t = esc(s);
    t = t.replaceAllMapped(
        RegExp(r'`([^`]+)`'), (m) => '<code>${m.group(1)}</code>');
    t = t.replaceAllMapped(
        RegExp(r'\*\*([^*]+)\*\*'), (m) => '<strong>${m.group(1)}</strong>');
    t = t.replaceAllMapped(
        RegExp(r'(?<!\*)\*([^*]+)\*(?!\*)'), (m) => '<em>${m.group(1)}</em>');
    t = t.replaceAllMapped(RegExp(r'\[([^\]]+)\]\(([^)]+)\)'),
        (m) => '<a href="${m.group(2)}">${m.group(1)}</a>');
    return t;
  }

  static String wrapHtml(String title, String body) => '''
<!doctype html>
<meta charset="utf-8">
<title>${esc(title)}</title>
<style>
  body { font: 16px/1.6 system-ui, sans-serif; max-width: 46em; margin: 2em auto; padding: 0 1em; }
  pre { background: #f4f4f8; padding: .8em; overflow: auto; }
  code { background: #f4f4f8; padding: .1em .3em; }
  table { border-collapse: collapse; } td, th { border: 1px solid #ccc; padding: 4px 8px; }
</style>
$body''';

  /// Strip tags, keeping block structure as line breaks.
  static String htmlToText(String html) {
    var t = html
        .replaceAll(RegExp(r'<script[\s\S]*?</script>', caseSensitive: false), '')
        .replaceAll(RegExp(r'<style[\s\S]*?</style>', caseSensitive: false), '')
        .replaceAll(RegExp(r'<br\s*/?>', caseSensitive: false), '\n')
        .replaceAll(
            RegExp(r'</(p|div|h[1-6]|li|tr)>', caseSensitive: false), '\n')
        .replaceAll(RegExp(r'<[^>]+>'), '');
    t = unesc(t);
    return t
        .split('\n')
        .map((l) => l.trim())
        .join('\n')
        .replaceAll(RegExp(r'\n{3,}'), '\n\n')
        .trim();
  }

  /// Rough HTML → Markdown for the common block tags.
  static String htmlToMd(String html) {
    var t = html
        .replaceAll(RegExp(r'<script[\s\S]*?</script>', caseSensitive: false), '')
        .replaceAll(RegExp(r'<style[\s\S]*?</style>', caseSensitive: false), '');
    for (var n = 1; n <= 6; n++) {
      t = t.replaceAllMapped(
          RegExp('<h$n[^>]*>([\\s\\S]*?)</h$n>', caseSensitive: false),
          (m) => '\n${'#' * n} ${m.group(1)!.trim()}\n');
    }
    t = t
        .replaceAllMapped(
            RegExp(r'<(strong|b)[^>]*>([\s\S]*?)</\1>', caseSensitive: false),
            (m) => '**${m.group(2)}**')
        .replaceAllMapped(
            RegExp(r'<(em|i)[^>]*>([\s\S]*?)</\1>', caseSensitive: false),
            (m) => '*${m.group(2)}*')
        .replaceAllMapped(
            RegExp(r'<code[^>]*>([\s\S]*?)</code>', caseSensitive: false),
            (m) => '`${m.group(1)}`')
        .replaceAllMapped(
            RegExp(r'<a[^>]*href="([^"]*)"[^>]*>([\s\S]*?)</a>',
                caseSensitive: false),
            (m) => '[${m.group(2)}](${m.group(1)})')
        .replaceAllMapped(
            RegExp(r'<li[^>]*>([\s\S]*?)</li>', caseSensitive: false),
            (m) => '- ${m.group(1)!.trim()}\n')
        .replaceAll(RegExp(r'<br\s*/?>', caseSensitive: false), '\n')
        .replaceAll(RegExp(r'</p>', caseSensitive: false), '\n\n')
        .replaceAll(RegExp(r'<[^>]+>'), '');
    return unesc(t).replaceAll(RegExp(r'\n{3,}'), '\n\n').trim();
  }

  static String esc(String s) => s
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;');

  static String unesc(String s) => s
      .replaceAll('&nbsp;', ' ')
      .replaceAll('&lt;', '<')
      .replaceAll('&gt;', '>')
      .replaceAll('&quot;', '"')
      .replaceAll('&#39;', "'")
      .replaceAll('&amp;', '&');

  // ---------------------------------------------------------------- docx out

  /// Build a minimal but valid .docx from paragraphs.
  static List<int> buildDocx(List<String> paragraphs) {
    String para(String text) {
      // Split on newlines so a paragraph keeps its soft breaks.
      final runs = text
          .split('\n')
          .map((l) =>
              '<w:r><w:t xml:space="preserve">${esc(l)}</w:t></w:r>')
          .join('<w:r><w:br/></w:r>');
      return '<w:p>$runs</w:p>';
    }

    final document = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>${paragraphs.map(para).join()}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body>
</w:document>''';

    const contentTypes = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>''';

    const rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>''';

    final archive = Archive();
    void add(String name, String body) {
      final data = utf8.encode(body);
      archive.addFile(ArchiveFile(name, data.length, data));
    }

    add('[Content_Types].xml', contentTypes);
    add('_rels/.rels', rels);
    add('word/document.xml', document);
    final zipped = ZipEncoder().encode(archive);
    if (zipped == null) throw Exception('Could not build the .docx');
    return zipped;
  }

  // ---------------------------------------------------------------- convert

  /// Any text-ish source to any text-ish target.
  static Future<List<String>> convertText(
      FileItem f, String target, ToolCall c) async {
    c.progress(0.3, 'Reading ${f.name}');
    final src = f.ext == 'htm' ? 'html' : f.ext;
    final stem = Fs.safeStem(f.name);

    String body;
    if (src == 'docx' || src == 'docm') {
      final paras = await docxParagraphs(f.path);
      body = switch (target) {
        'html' => wrapHtml(stem, paras.map((p) => '<p>${esc(p)}</p>').join('\n')),
        'md' => paras.join('\n\n'),
        _ => paras.join('\n'),
      };
    } else {
      final text = await File(f.path).readAsString();
      body = switch ('$src>$target') {
        'md>html' => wrapHtml(stem, mdToHtml(text)),
        'txt>html' =>
          wrapHtml(stem, text.split('\n').map((l) => '<p>${esc(l)}</p>').join('\n')),
        'html>txt' => htmlToText(text),
        'html>md' => htmlToMd(text),
        _ => text,
      };
    }

    if (target == 'docx') {
      final text = src == 'html'
          ? htmlToText(await File(f.path).readAsString())
          : body;
      final out = Fs.uniq(c.outDir, '$stem.docx');
      await out.writeAsBytes(buildDocx(text.split(RegExp(r'\n\s*\n'))));
      return [out.path];
    }

    c.progress(0.8, 'Writing $stem.$target');
    final out = Fs.uniq(c.outDir, '$stem.$target');
    await out.writeAsString(body);
    return [out.path];
  }

  /// Any text-ish source to PDF, laid out on A4.
  static Future<List<String>> textToPdf(
      FileItem f, String target, ToolCall c) async {
    c.progress(0.3, 'Reading ${f.name}');
    final text = await readText(f.path);
    final blocks = text.split(RegExp(r'\n\s*\n'));
    final doc = pw.Document();
    doc.addPage(
      pw.MultiPage(
        pageFormat: PdfPageFormat.a4,
        margin: const pw.EdgeInsets.all(48),
        build: (_) => [
          for (final b in blocks)
            if (b.trim().isNotEmpty)
              pw.Padding(
                padding: const pw.EdgeInsets.only(bottom: 10),
                child: pw.Text(b.trim(),
                    style: const pw.TextStyle(fontSize: 11, lineSpacing: 2)),
              ),
        ],
      ),
    );
    c.progress(0.8, 'Writing PDF');
    final out = Fs.uniq(c.outDir, '${Fs.safeStem(f.name)}.pdf');
    await out.writeAsBytes(await doc.save());
    return [out.path];
  }
}
