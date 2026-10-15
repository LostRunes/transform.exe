/// Spreadsheet & structured-data engine. Everything here is pure Dart,
/// so it works with no network and no native helpers. Mirrors core/conv_data.py.
library;
import 'dart:convert';
import 'dart:io';

import 'package:csv/csv.dart';
import 'package:excel/excel.dart' as xl;
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:xml/xml.dart';

import '../core/fs.dart';
import '../core/models.dart';

/// A table is a header row plus body rows, all as strings.
class Table {
  Table(this.header, this.rows, {this.name = 'Sheet1'});

  final List<String> header;
  final List<List<String>> rows;
  final String name;

  bool get isEmpty => header.isEmpty && rows.isEmpty;
}

const tableIn = ['csv', 'tsv', 'xlsx', 'xlsm', 'xls', 'json', 'xml', 'ods'];
const dataOut = ['csv', 'tsv', 'json', 'xml', 'xlsx', 'md', 'sql', 'html'];

class DataEngine {
  // ---------------------------------------------------------------- read

  /// Read a file into one or more tables. Multi-sheet workbooks give one each.
  static Future<List<Table>> read(String path) async {
    final ext = FileItem.extOf(path);
    switch (ext) {
      case 'csv':
        return [_fromRows(_parseDelimited(await File(path).readAsString(), ','))];
      case 'tsv':
        return [_fromRows(_parseDelimited(await File(path).readAsString(), '\t'))];
      case 'json':
        return [_fromJson(await File(path).readAsString())];
      case 'xml':
        return [_fromXml(await File(path).readAsString())];
      case 'xlsx':
      case 'xlsm':
      case 'xls':
      case 'ods':
        return _fromExcel(await File(path).readAsBytes());
      default:
        throw Exception('Cannot read .$ext as a table');
    }
  }

  static List<List<String>> _parseDelimited(String text, String delim) {
    final rows = Csv(
      fieldDelimiter: delim,
      autoDetect: false,
      skipEmptyLines: true,
    ).decode(text);
    return rows
        .map((r) => r.map((c) => c?.toString() ?? '').toList())
        .where((r) => r.any((c) => c.trim().isNotEmpty))
        .toList();
  }

  static Table _fromRows(List<List<String>> rows) {
    if (rows.isEmpty) return Table([], []);
    final width = rows.fold<int>(0, (m, r) => r.length > m ? r.length : m);
    List<String> pad(List<String> r) =>
        [...r, ...List.filled(width - r.length, '')];
    return Table(pad(rows.first), rows.skip(1).map(pad).toList());
  }

  static Table _fromJson(String text) {
    final decoded = jsonDecode(text);
    final list = decoded is List
        ? decoded
        : decoded is Map && decoded.values.any((v) => v is List)
            ? decoded.values.firstWhere((v) => v is List) as List
            : [decoded];
    if (list.isEmpty) return Table([], []);
    if (list.first is Map) {
      // Union of keys, so sparse records still line up.
      final keys = <String>[];
      for (final row in list) {
        for (final k in (row as Map).keys) {
          if (!keys.contains(k.toString())) keys.add(k.toString());
        }
      }
      return Table(
        keys,
        list
            .map((row) => keys
                .map((k) => _stringify((row as Map)[k]))
                .toList())
            .toList(),
      );
    }
    return Table(['value'], list.map((v) => [_stringify(v)]).toList());
  }

  static Table _fromXml(String text) {
    final doc = XmlDocument.parse(text);
    final root = doc.rootElement;
    final records = root.childElements.toList();
    if (records.isEmpty) return Table([], []);
    final keys = <String>[];
    for (final r in records) {
      for (final c in r.childElements) {
        if (!keys.contains(c.name.local)) keys.add(c.name.local);
      }
      for (final a in r.attributes) {
        if (!keys.contains(a.name.local)) keys.add(a.name.local);
      }
    }
    final rows = records.map((r) {
      return keys.map((k) {
        final child = r.childElements.where((c) => c.name.local == k);
        if (child.isNotEmpty) return child.first.innerText;
        final attr = r.getAttribute(k);
        return attr ?? '';
      }).toList();
    }).toList();
    return Table(keys, rows);
  }

  static List<Table> _fromExcel(List<int> bytes) {
    final book = xl.Excel.decodeBytes(bytes);
    final out = <Table>[];
    for (final entry in book.tables.entries) {
      final rows = entry.value.rows
          .map((r) => r.map((c) => _stringify(c?.value)).toList())
          .where((r) => r.any((c) => c.trim().isNotEmpty))
          .toList();
      if (rows.isEmpty) continue;
      final t = _fromRows(rows);
      out.add(Table(t.header, t.rows, name: entry.key));
    }
    return out.isEmpty ? [Table([], [])] : out;
  }

  static String _stringify(Object? v) {
    if (v == null) return '';
    if (v is xl.TextCellValue) return v.value.toString();
    if (v is xl.IntCellValue) return v.value.toString();
    if (v is xl.DoubleCellValue) {
      final d = v.value;
      return d == d.roundToDouble() ? d.toInt().toString() : d.toString();
    }
    if (v is Map || v is List) return jsonEncode(v);
    return v.toString();
  }

  // ---------------------------------------------------------------- write

  static Future<List<String>> write(
      Table t, String ext, String outDir, String stem) async {
    final out = Fs.uniq(outDir, '$stem.$ext');
    switch (ext) {
      case 'csv':
      case 'tsv':
        final conv = Csv(
            fieldDelimiter: ext == 'tsv' ? '\t' : ',', lineDelimiter: '\r\n');
        await out.writeAsString(conv.encode([t.header, ...t.rows]));
      case 'json':
        final records = t.rows
            .map((r) => {
                  for (var i = 0; i < t.header.length; i++)
                    t.header[i]: i < r.length ? r[i] : ''
                })
            .toList();
        await out.writeAsString(
            const JsonEncoder.withIndent('  ').convert(records));
      case 'xml':
        final b = XmlBuilder();
        b.processing('xml', 'version="1.0" encoding="UTF-8"');
        b.element('rows', nest: () {
          for (final r in t.rows) {
            b.element('row', nest: () {
              for (var i = 0; i < t.header.length; i++) {
                b.element(_xmlName(t.header[i]),
                    nest: i < r.length ? r[i] : '');
              }
            });
          }
        });
        await out.writeAsString(
            b.buildDocument().toXmlString(pretty: true, indent: '  '));
      case 'xlsx':
        final book = xl.Excel.createExcel();
        final name = book.getDefaultSheet() ?? 'Sheet1';
        final sheet = book[name];
        sheet.appendRow(
            t.header.map((h) => xl.TextCellValue(h) as xl.CellValue?).toList());
        for (final r in t.rows) {
          sheet.appendRow(
              r.map((v) => xl.TextCellValue(v) as xl.CellValue?).toList());
        }
        final bytes = book.encode();
        if (bytes == null) throw Exception('Could not build the workbook');
        await out.writeAsBytes(bytes);
      case 'md':
        final b = StringBuffer()
          ..writeln('| ${t.header.join(' | ')} |')
          ..writeln('| ${t.header.map((_) => '---').join(' | ')} |');
        for (final r in t.rows) {
          b.writeln('| ${r.map((c) => c.replaceAll('|', r'\|')).join(' | ')} |');
        }
        await out.writeAsString(b.toString());
      case 'sql':
        final table = _sqlName(stem);
        final b = StringBuffer()
          ..writeln('CREATE TABLE "$table" (')
          ..writeln(t.header.map((h) => '  "${_sqlName(h)}" TEXT').join(',\n'))
          ..writeln(');\n');
        for (final r in t.rows) {
          final vals = r.map((v) => "'${v.replaceAll("'", "''")}'").join(', ');
          b.writeln(
              'INSERT INTO "$table" (${t.header.map((h) => '"${_sqlName(h)}"').join(', ')}) VALUES ($vals);');
        }
        await out.writeAsString(b.toString());
      case 'html':
        final b = StringBuffer()
          ..writeln('<!doctype html><meta charset="utf-8">')
          ..writeln('<title>${_esc(stem)}</title>')
          ..writeln('<table border="1" cellspacing="0" cellpadding="4">')
          ..writeln(
              '<thead><tr>${t.header.map((h) => '<th>${_esc(h)}</th>').join()}</tr></thead><tbody>');
        for (final r in t.rows) {
          b.writeln('<tr>${r.map((c) => '<td>${_esc(c)}</td>').join()}</tr>');
        }
        b.writeln('</tbody></table>');
        await out.writeAsString(b.toString());
      default:
        throw Exception('Cannot write tables as .$ext');
    }
    return [out.path];
  }

  static String _xmlName(String s) {
    final cleaned = s.replaceAll(RegExp(r'[^A-Za-z0-9_.-]'), '_');
    return cleaned.isEmpty || RegExp(r'^[^A-Za-z_]').hasMatch(cleaned)
        ? 'c_$cleaned'
        : cleaned;
  }

  static String _sqlName(String s) =>
      s.replaceAll('"', '').replaceAll(RegExp(r'\s+'), '_');

  static String _esc(String s) => s
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;');

  // ---------------------------------------------------------------- convert

  /// Convert view: table -> table. Multi-sheet books split into one file each.
  static Future<List<String>> convertTable(
      FileItem f, String target, ToolCall c) async {
    c.progress(0.3, 'Reading ${f.name}');
    final tables = await read(f.path);
    final outs = <String>[];
    final stem = Fs.safeStem(f.name);
    for (var i = 0; i < tables.length; i++) {
      if (c.isCancelled()) break;
      c.progress(0.3 + 0.6 * i / tables.length, 'Writing sheet ${i + 1}');
      final name = tables.length == 1 ? stem : '$stem ${tables[i].name}';
      outs.addAll(await write(tables[i], target, c.outDir, name));
    }
    return outs;
  }

  /// Convert view: table -> pdf, drawn as a real grid.
  static Future<List<String>> tableToPdf(
      FileItem f, String target, ToolCall c) async {
    c.progress(0.3, 'Reading ${f.name}');
    final tables = await read(f.path);
    final doc = pw.Document();
    for (final t in tables) {
      if (t.isEmpty) continue;
      doc.addPage(
        pw.MultiPage(
          pageFormat: PdfPageFormat.a4.landscape,
          margin: const pw.EdgeInsets.all(24),
          build: (_) => [
            pw.Header(level: 0, text: t.name),
            pw.TableHelper.fromTextArray(
              headers: t.header,
              data: t.rows,
              cellStyle: const pw.TextStyle(fontSize: 8),
              headerStyle:
                  pw.TextStyle(fontSize: 8, fontWeight: pw.FontWeight.bold),
              headerDecoration:
                  const pw.BoxDecoration(color: PdfColor(0.90, 0.90, 1.0)),
              cellHeight: 14,
            ),
          ],
        ),
      );
    }
    if (doc.document.pdfPageList.pages.isEmpty) {
      throw Exception('Nothing to put in the PDF — the table was empty');
    }
    c.progress(0.8, 'Writing PDF');
    final out = Fs.uniq(c.outDir, '${Fs.safeStem(f.name)}.pdf');
    await out.writeAsBytes(await doc.save());
    return [out.path];
  }

  // ---------------------------------------------------------------- tool

  /// Spreadsheets → Merge spreadsheets.
  static Future<List<String>> toolMerge(ToolCall c) async {
    final header = <String>[];
    final rows = <List<String>>[];
    final addSource = c.boolP('add_source', true);
    if (addSource) header.add('source');

    for (var i = 0; i < c.files.length; i++) {
      if (c.isCancelled()) break;
      final f = c.files[i];
      c.progress(i / c.files.length, 'Reading ${f.name}');
      for (final t in await read(f.path)) {
        if (t.isEmpty) continue;
        for (final h in t.header) {
          if (!header.contains(h)) header.add(h);
        }
        for (final r in t.rows) {
          final map = <String, String>{
            for (var k = 0; k < t.header.length; k++)
              t.header[k]: k < r.length ? r[k] : ''
          };
          if (addSource) map['source'] = f.name;
          rows.add(header.map((h) => map[h] ?? '').toList());
        }
      }
    }
    // Columns discovered late leave earlier rows short; square it off.
    for (final r in rows) {
      while (r.length < header.length) {
        r.add('');
      }
    }
    if (rows.isEmpty) throw Exception('No rows found in those files');
    c.progress(0.8, 'Writing ${rows.length} rows');
    final stem = '${Fs.safeStem(c.files.first.name)} merged';
    return write(Table(header, rows), c.strP('out_fmt', 'xlsx'), c.outDir, stem);
  }
}
