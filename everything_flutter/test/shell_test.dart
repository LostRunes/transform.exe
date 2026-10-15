/// Widget tests for the shell. These exist because the first build shipped a
/// frozen UI: `home: const Shell()` meant AppState changes never reached the
/// tree, so navigation and the jobs panel silently did nothing. Every test here
/// drives the real widgets and asserts on what is actually on screen.
library;

import 'dart:async';

import 'package:everything_converter/core/app_state.dart';
import 'package:everything_converter/core/jobs.dart';
import 'package:everything_converter/core/theme.dart';
import 'package:everything_converter/shell.dart';
import 'package:everything_converter/views/convert_view.dart';
import 'package:everything_converter/views/scan_view.dart';
import 'package:everything_converter/views/tools_view.dart';
import 'package:everything_converter/widgets/jobs_panel.dart';
import 'package:everything_converter/widgets/toast.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Mount the shell the same way main.dart does, at a phone size.
Future<void> pumpShell(WidgetTester tester, {Size size = const Size(390, 844)}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);

  await tester.pumpWidget(
    ListenableBuilder(
      listenable: AppState.instance,
      builder: (context, _) => MaterialApp(
        theme: buildTheme(AppState.instance.dark ? Skin.night : Skin.day),
        // The sky and the mascot loop forever by design; turning them off lets
        // pumpAndSettle reach a steady frame.
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context).copyWith(disableAnimations: true),
          child: child!,
        ),
        home: ToastHost(key: toastKey, child: const Shell()),
      ),
    ),
  );
  await settle(tester);
}

/// Advance a few frames. Deliberately not pumpAndSettle: some views show an
/// indeterminate spinner, which never settles and would hang the test.
Future<void> settle(WidgetTester tester) async {
  for (var i = 0; i < 4; i++) {
    await tester.pump(const Duration(milliseconds: 120));
  }
}

/// Tap a nav entry, scrolling it into view first. The phone strip scrolls
/// horizontally and the sidebar vertically, and both are lazy, so an
/// off-screen label does not exist in the tree yet.
Future<void> tapNav(WidgetTester tester, String label) async {
  final horizontal = find.byType(NavStrip).evaluate().isNotEmpty;
  final nav = horizontal ? find.byType(NavStrip) : find.byType(Sidebar);
  final target = find.descendant(of: nav, matching: find.text(label));

  if (target.evaluate().isEmpty) {
    await tester.dragUntilVisible(
      target,
      find.descendant(of: nav, matching: find.byType(Scrollable)),
      horizontal ? const Offset(-120, 0) : const Offset(0, -120),
    );
    await settle(tester);
  }
  await tester.ensureVisible(target);
  await settle(tester);
  await tester.tap(target);
  await settle(tester);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await AppState.instance.initForTest();
    JobQueue.instance.clearFinished();
  });

  group('navigation', () {
    testWidgets('the phone nav strip is visible and switches views',
        (tester) async {
      await pumpShell(tester);
      expect(find.byType(NavStrip), findsOneWidget);
      expect(find.byType(ConvertView), findsOneWidget);

      // Tapping a tab must actually change what is rendered.
      await tapNav(tester, 'Scan → PDF');

      expect(find.byType(ScanView), findsOneWidget);
      expect(find.byType(ConvertView), findsNothing);
    });

    testWidgets('a tools tab opens that category grid', (tester) async {
      await pumpShell(tester);
      await tapNav(tester, 'PDF tools');
      expect(find.byType(ToolsView), findsOneWidget);
      expect(find.text('Merge PDFs'), findsOneWidget);
    });

    testWidgets('the wide layout shows the sidebar instead of the strip',
        (tester) async {
      await pumpShell(tester, size: const Size(1200, 900));
      expect(find.byType(Sidebar), findsOneWidget);
      expect(find.byType(NavStrip), findsNothing);

      await tapNav(tester, 'Clean up');
      expect(AppState.instance.view, 'cleanup');
    });
  });

  group('jobs panel', () {
    testWidgets('opens on the first tap and closes from the X', (tester) async {
      await pumpShell(tester);
      expect(find.byType(JobsPanel), findsNothing);

      // One tap, not five.
      await tester.tap(find.byKey(const Key('jobs-toggle')));
      await settle(tester);
      expect(find.byType(JobsPanel), findsOneWidget);

      await tester.tap(find.text('✕'));
      await settle(tester);
      expect(find.byType(JobsPanel), findsNothing);
    });

    testWidgets('the taskbar button toggles both ways', (tester) async {
      await pumpShell(tester);
      final button = find.byKey(const Key('jobs-toggle'));

      await tester.tap(button);
      await settle(tester);
      expect(find.byType(JobsPanel), findsOneWidget);

      await tester.tap(button);
      await settle(tester);
      expect(find.byType(JobsPanel), findsNothing);
    });
  });

  group('back button', () {
    /// Deliver a real Android back gesture to the framework.
    Future<void> pressBack(WidgetTester tester) async {
      await tester.binding.defaultBinaryMessenger.handlePlatformMessage(
        'flutter/navigation',
        const JSONMethodCodec().encodeMethodCall(
          const MethodCall('popRoute'),
        ),
        (_) {},
      );
      await settle(tester);
    }

    testWidgets('closes the jobs panel rather than the app', (tester) async {
      await pumpShell(tester);
      await tester.tap(find.byKey(const Key('jobs-toggle')));
      await settle(tester);
      expect(find.byType(JobsPanel), findsOneWidget);

      await pressBack(tester);
      expect(find.byType(JobsPanel), findsNothing);
    });

    testWidgets('steps back from a tool page to its grid', (tester) async {
      await pumpShell(tester);
      await tapNav(tester, 'PDF tools');
      await tester.tap(find.text('Merge PDFs'));
      await settle(tester);
      expect(AppState.instance.currentTool, isNotNull);

      await pressBack(tester);
      expect(AppState.instance.currentTool, isNull);
      expect(find.text('Merge PDFs'), findsOneWidget); // back on the grid
    });

    testWidgets('steps back from another view to Convert', (tester) async {
      await pumpShell(tester);
      await tapNav(tester, 'Clean up');
      expect(AppState.instance.view, 'cleanup');

      await pressBack(tester);
      expect(AppState.instance.view, 'convert');
      expect(find.byType(ConvertView), findsOneWidget);
    });
  });

  group('running work', () {
    testWidgets('a finished job reports itself in the panel', (tester) async {
      await pumpShell(tester);
      AppState.instance.setJobsOpen(true);
      await settle(tester);

      JobQueue.instance.submit(
        title: 'Pretend conversion',
        files: const [],
        params: const {},
        outDir: '/out',
        body: (call) async {
          call.progress(0.5, 'halfway');
          return ['/out/result.png'];
        },
      );
      await settle(tester);

      expect(find.text('Pretend conversion'), findsOneWidget);
      expect(find.text('done'), findsOneWidget);
      expect(find.text('result.png'), findsOneWidget);
      // Every finished file offers all three ways out.
      expect(find.text('Open'), findsOneWidget);
      expect(find.text('Save'), findsOneWidget);
      expect(find.text('Share'), findsOneWidget);
    });

    testWidgets('a failing job shows the reason instead of dying',
        (tester) async {
      await pumpShell(tester);
      AppState.instance.setJobsOpen(true);
      await settle(tester);

      JobQueue.instance.submit(
        title: 'Doomed conversion',
        files: const [],
        params: const {},
        outDir: '/out',
        body: (call) async => throw Exception('no converter for .xyz'),
      );
      await settle(tester);

      expect(find.text('error'), findsOneWidget);
      expect(find.textContaining('no converter for .xyz'), findsWidgets);
    });

    testWidgets('the taskbar badge counts active work', (tester) async {
      await pumpShell(tester);
      final gate = Completer<void>();
      JobQueue.instance.submit(
        title: 'Slow job',
        files: const [],
        params: const {},
        outDir: '/out',
        body: (call) async {
          await gate.future;
          return const <String>[];
        },
      );
      await settle(tester);
      expect(find.text('1'), findsOneWidget);

      gate.complete();
      await settle(tester);
      expect(find.text('0'), findsOneWidget);
    });
  });

  group('taskbar', () {
    testWidgets('there is no clock', (tester) async {
      await pumpShell(tester);
      // Nothing that looks like a time of day.
      expect(find.byWidgetPredicate((w) =>
          w is Text && w.data != null && RegExp(r'^\d{1,2}:\d{2}$').hasMatch(w.data!)),
          findsNothing);
    });
  });

  group('theme', () {
    testWidgets('the taskbar toggle repaints in the new skin', (tester) async {
      await pumpShell(tester);
      expect(AppState.instance.dark, isFalse);
      expect(find.text('☀'), findsOneWidget);

      await tester.tap(find.byKey(const Key('theme-toggle')));
      await settle(tester);

      expect(AppState.instance.dark, isTrue);
      // The glyph flipping proves the taskbar really repainted.
      expect(find.text('☾'), findsOneWidget);
    });
  });

  group('start menu', () {
    testWidgets('opens, navigates and closes', (tester) async {
      await pumpShell(tester);
      await tester.tap(find.byKey(const Key('start-button')));
      await settle(tester);
      expect(find.byType(StartMenu), findsOneWidget);

      // The menu lists every view; pick one that is not the current page.
      await tester.tap(find.descendant(
        of: find.byType(StartMenu),
        matching: find.text('Image tools'),
      ));
      await settle(tester);

      expect(find.byType(StartMenu), findsNothing);
      expect(AppState.instance.view, 'tools:Image');
    });
  });
}
