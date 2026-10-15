/// Sweeps every screen at real device widths and fails on any layout overflow
/// or build exception. The first build shipped two overflows (the taskbar and
/// the Clean up tabs) that nobody caught because no test ever rendered those
/// screens at phone size.
library;

import 'package:everything_converter/core/app_state.dart';
import 'package:everything_converter/core/models.dart';
import 'package:everything_converter/core/registry.dart';
import 'package:everything_converter/core/theme.dart';
import 'package:everything_converter/shell.dart';
import 'package:everything_converter/widgets/toast.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Small phone, common phone, large phone, tablet.
const _sizes = <String, Size>{
  'small phone 320': Size(320, 640),
  'phone 390': Size(390, 844),
  'large phone 430': Size(430, 932),
  'tablet 1024': Size(1024, 768),
};

Future<void> _pump(WidgetTester tester, Size size) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ListenableBuilder(
      listenable: AppState.instance,
      builder: (context, _) => MaterialApp(
        theme: buildTheme(AppState.instance.dark ? Skin.night : Skin.day),
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context).copyWith(disableAnimations: true),
          child: child!,
        ),
        home: ToastHost(key: toastKey, child: const Shell()),
      ),
    ),
  );
  for (var i = 0; i < 4; i++) {
    await tester.pump(const Duration(milliseconds: 120));
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await AppState.instance.initForTest();
  });

  for (final entry in _sizes.entries) {
    group(entry.key, () {
      for (final view in views) {
        testWidgets('${view[2]} lays out cleanly', (tester) async {
          AppState.instance.route(view[0]);
          await _pump(tester, entry.value);
          expect(tester.takeException(), isNull,
              reason: '${view[2]} at ${entry.value.width}px');
        });
      }

      testWidgets('both themes lay out cleanly', (tester) async {
        await _pump(tester, entry.value);
        expect(tester.takeException(), isNull);
        AppState.instance.toggleTheme();
        await _pump(tester, entry.value);
        expect(tester.takeException(), isNull);
      });

      testWidgets('the jobs panel lays out cleanly', (tester) async {
        AppState.instance.setJobsOpen(true);
        await _pump(tester, entry.value);
        expect(tester.takeException(), isNull);
      });
    });
  }

  group('tool pages lay out cleanly at 320px', () {
    for (final tool in tools) {
      testWidgets(tool.name, (tester) async {
        AppState.instance
          ..route('tools:${tool.cat}')
          ..openTool(tool);
        await _pump(tester, const Size(320, 640));
        expect(tester.takeException(), isNull, reason: tool.name);
      });
    }
  });

  group('queued files lay out cleanly', () {
    testWidgets('convert rows with a long filename', (tester) async {
      AppState.instance.route('convert');
      AppState.instance.addFiles([
        FileItem(
          path: '/tmp/a-really-quite-long-holiday-photo-name-2026.png',
          name: 'a-really-quite-long-holiday-photo-name-2026.png',
          ext: 'png',
          size: 4 * 1024 * 1024,
        ),
      ]);
      await _pump(tester, const Size(320, 640));
      expect(tester.takeException(), isNull);
      // The row should offer a target, not claim the type is unsupported.
      expect(find.textContaining('No converter'), findsNothing);
    });
  });
}
