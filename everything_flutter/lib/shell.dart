/// The desktop shell: nav, top "save to" bar, the jobs window and the taskbar.
///
/// Layout follows the same breakpoint the stylesheet already used: at 960px and
/// up you get the three-column desktop (sidebar / main / jobs). Below that —
/// every phone — the sidebar is replaced by a scrollable tab strip, because a
/// nav buried in the Start menu is not discoverable on a touch screen.
///
/// Everything that reads [AppState] must be rebuilt when it changes, so this
/// file subscribes once in [_ShellState] and deliberately avoids `const` on the
/// widgets below it: a const widget is canonicalised, and Flutter skips
/// updating a subtree whose widget is identical to last frame.
library;

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:open_filex/open_filex.dart';

import 'core/app_state.dart';
import 'core/fs.dart';
import 'core/jobs.dart';
import 'core/registry.dart';
import 'core/theme.dart';
import 'views/cleanup_view.dart';
import 'views/convert_view.dart';
import 'views/editor_view.dart';
import 'views/scan_view.dart';
import 'views/tools_view.dart';
import 'widgets/jobs_panel.dart';
import 'widgets/mascot.dart';
import 'widgets/retro.dart';
import 'widgets/sky.dart';
import 'widgets/toast.dart';

/// At or above this width, show the full desktop layout.
const kWide = 960.0;

class Shell extends StatefulWidget {
  const Shell({super.key});

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  final app = AppState.instance;
  bool _startOpen = false;

  @override
  void initState() {
    super.initState();
    // Without these the whole screen is frozen: AppState changes would never
    // reach the tree, because `home: const Shell()` is skipped on rebuild.
    app.addListener(_refresh);
    JobQueue.instance.addListener(_onJobs);
  }

  @override
  void dispose() {
    app.removeListener(_refresh);
    JobQueue.instance.removeListener(_onJobs);
    super.dispose();
  }

  void _refresh() {
    if (mounted) setState(() {});
  }

  /// Nudge the buddy while work is running, like pollJobs() does on the web.
  void _onJobs() {
    if (!mounted) return;
    final running = JobQueue.instance.activeCount;
    if (running > 0) {
      app.say('working on it… $running job${running > 1 ? 's' : ''} running ⏳');
    }
    setState(() {});
  }

  /// Android back: unwind the UI one step at a time instead of quitting.
  void _back() {
    if (_startOpen) {
      setState(() => _startOpen = false);
      return;
    }
    if (app.jobsOpen) {
      app.setJobsOpen(false);
      return;
    }
    if (app.currentTool != null) {
      app.openTool(null);
      return;
    }
    if (app.view != 'convert') {
      app.route('convert');
      return;
    }
    SystemNavigator.pop();
  }

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= kWide;
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _back();
      },
      child: Scaffold(
        backgroundColor: Colors.transparent,
        resizeToAvoidBottomInset: false,
        body: Sky(
          child: SafeArea(
            child: Stack(
              children: [
                Positioned.fill(
                  bottom: 46,
                  child: wide ? _wideLayout() : _narrowLayout(),
                ),
                Positioned(
                  left: 0,
                  right: 0,
                  bottom: 0,
                  child: Taskbar(
                    startOpen: _startOpen,
                    onStart: () => setState(() => _startOpen = !_startOpen),
                  ),
                ),
                if (_startOpen)
                  Positioned.fill(
                    child: GestureDetector(
                      behavior: HitTestBehavior.opaque,
                      onTap: () => setState(() => _startOpen = false),
                      child: ColoredBox(
                        color: context.skin.sky1.withValues(alpha: 0.35),
                      ),
                    ),
                  ),
                if (_startOpen)
                  Positioned(
                    left: 10,
                    bottom: 52,
                    child: StartMenu(
                      onPick: (v) {
                        setState(() => _startOpen = false);
                        app.route(v);
                      },
                      onClose: () => setState(() => _startOpen = false),
                    ),
                  ),
                // On a phone the jobs window is a sheet over the content.
                if (!wide && app.jobsOpen) _jobsSheet(),
              ],
            ),
          ),
        ),
      ),
    );
  }

  /// The phone jobs sheet. It stops above the taskbar on purpose — covering it
  /// would hide the very button used to dismiss the sheet.
  Widget _jobsSheet() => Positioned(
        left: 0,
        right: 0,
        top: 0,
        bottom: 46,
        child: Stack(
          children: [
            Positioned.fill(
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                onTap: () => app.setJobsOpen(false),
                child: ColoredBox(
                  color: context.skin.sky1.withValues(alpha: 0.5),
                ),
              ),
            ),
            Positioned(
              left: 8,
              right: 8,
              top: 8,
              bottom: 8,
              child: JobsPanel(onClose: () => app.setJobsOpen(false)),
            ),
          ],
        ),
      );

  Widget _wideLayout() => Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SizedBox(width: 238, child: Sidebar()),
            const SizedBox(width: 16),
            Expanded(child: MainColumn(wide: true)),
            if (app.jobsOpen) ...[
              const SizedBox(width: 16),
              SizedBox(
                width: 340,
                child: JobsPanel(onClose: () => app.setJobsOpen(false)),
              ),
            ],
          ],
        ),
      );

  Widget _narrowLayout() => Padding(
        padding: const EdgeInsets.fromLTRB(10, 8, 10, 6),
        child: MainColumn(wide: false),
      );
}

// ---------------------------------------------------------------- sidebar

class Sidebar extends StatelessWidget {
  const Sidebar({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppState.instance;
    final s = context.skin;
    return RetroWindow(
      title: 'my_computer',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(10, 10, 10, 2),
            child: Column(
              children: [
                SpeechBubble(app.buddyLine),
                const Mascot(width: 84, tappable: true),
              ],
            ),
          ),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              children: [
                for (var i = 0; i < views.length; i++)
                  NavLink(
                    icon: views[i][1],
                    label: views[i][2],
                    active: app.view == views[i][0],
                    color: navColors[i % navColors.length](s),
                    onTap: () => app.route(views[i][0]),
                  ),
              ],
            ),
          ),
          const DashedDivider(),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const CapsChips(),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Container(
                      width: 8,
                      height: 8,
                      decoration:
                          BoxDecoration(color: s.ok, shape: BoxShape.circle),
                    ),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        'offline · files never leave this phone',
                        style: TextStyle(
                          fontSize: 11.5,
                          fontWeight: FontWeight.w600,
                          color: s.muted,
                        ),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// The pastel icon colours cycling down the nav, matching .i1…i7.
final navColors = <Color Function(Skin)>[
  (s) => s.lilac,
  (s) => s.sky,
  (s) => s.pink,
  (s) => s.butter,
  (s) => s.mint,
  (s) => s.sky,
  (s) => s.peach,
  (s) => s.lilac,
];

class NavLink extends StatelessWidget {
  const NavLink({
    super.key,
    required this.icon,
    required this.label,
    required this.active,
    required this.onTap,
    required this.color,
  });

  final String icon;
  final String label;
  final bool active;
  final VoidCallback onTap;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        margin: const EdgeInsets.only(bottom: 3),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
        decoration: BoxDecoration(
          color: active ? s.sel : Colors.transparent,
          border: Border.all(
              color: active ? s.ink : Colors.transparent, width: 2),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Row(
          children: [
            TileIcon(icon, color: color, size: 28, fontSize: 14),
            const SizedBox(width: 10),
            Expanded(
              child: Text(label,
                  style:
                      TextStyle(fontWeight: FontWeight.w700, color: s.text)),
            ),
          ],
        ),
      ),
    );
  }
}

/// The phone nav: a scrollable strip of tabs, always on screen.
class NavStrip extends StatelessWidget {
  const NavStrip({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppState.instance;
    final s = context.skin;
    return SizedBox(
      height: 46,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 2),
        itemCount: views.length,
        separatorBuilder: (_, _) => const SizedBox(width: 6),
        itemBuilder: (context, i) {
          final active = app.view == views[i][0];
          return GestureDetector(
            onTap: () => app.route(views[i][0]),
            behavior: HitTestBehavior.opaque,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10),
              decoration: BoxDecoration(
                color: active ? s.win : s.win2,
                border: Border.all(color: active ? s.ink : s.inkSoft, width: 2),
                borderRadius: BorderRadius.circular(10),
                boxShadow: active ? hardShadow(s.drop, 2) : null,
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TileIcon(
                    views[i][1],
                    color: navColors[i % navColors.length](s),
                    size: 24,
                    fontSize: 12,
                  ),
                  const SizedBox(width: 8),
                  Text(
                    views[i][2],
                    style: TextStyle(
                      fontWeight: FontWeight.w800,
                      fontSize: 13,
                      color: active ? s.text : s.muted,
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

/// .caps — what this build can actually do.
class CapsChips extends StatelessWidget {
  const CapsChips({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    final caps = capabilities();
    const labels = {
      'images': 'Images',
      'pdf': 'PDF',
      'docs': 'Docs',
      'sheets': 'Sheets',
      'heic': 'HEIC',
      'media': 'Video/Audio',
    };
    return Wrap(
      spacing: 4,
      runSpacing: 4,
      children: [
        for (final e in labels.entries)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 7),
            decoration: BoxDecoration(
              border: Border.all(
                color: caps[e.key] == true
                    ? s.ok.withValues(alpha: 0.45)
                    : s.inkSoft,
                width: 1.5,
              ),
              borderRadius: BorderRadius.circular(99),
            ),
            child: Text(
              '${caps[e.key] == true ? '✓' : '✕'} ${e.value}',
              style: TextStyle(
                fontSize: 10.5,
                fontWeight: FontWeight.w700,
                color: caps[e.key] == true ? s.ok : s.muted,
              ),
            ),
          ),
      ],
    );
  }
}

// ---------------------------------------------------------------- main column

class MainColumn extends StatelessWidget {
  const MainColumn({super.key, required this.wide});
  final bool wide;

  @override
  Widget build(BuildContext context) {
    final app = AppState.instance;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TopBar(wide: wide),
        if (!wide) ...[
          const SizedBox(height: 8),
          const NavStrip(),
        ],
        SizedBox(height: wide ? 16 : 8),
        Expanded(child: viewFor(app.view)),
      ],
    );
  }

  static Widget viewFor(String view) {
    final kind = view.split(':').first;
    return switch (kind) {
      'convert' => const ConvertView(),
      'scan' => const ScanView(),
      'tools' => ToolsView(category: view.split(':').last),
      'editor' => const EditorView(),
      'cleanup' => const CleanupView(),
      _ => const ConvertView(),
    };
  }
}

/// .topbar — the window title plus where output goes. Compact on a phone.
class TopBar extends StatelessWidget {
  const TopBar({super.key, required this.wide});
  final bool wide;

  @override
  Widget build(BuildContext context) {
    final app = AppState.instance;
    final s = context.skin;

    Future<void> pickDir() async {
      final dir = await FilePicker.getDirectoryPath(
          dialogTitle: 'Choose where converted files go');
      if (dir == null) return;
      // Android hands back plenty of folders it will not let us write to.
      // Better to say so now than to fail every job later.
      if (!await Fs.isWritable(dir)) {
        toast("Android won't let this app write to that folder — "
            'pick another one.', error: true);
        return;
      }
      app.setOutDir(dir);
      toast('Saving to $dir');
    }

    final folderChip = GestureDetector(
      onTap: pickDir,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
        decoration: BoxDecoration(
          color: s.win2,
          border: Border.all(color: s.inkSoft, width: 2),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Row(
          children: [
            const Text('📁', style: TextStyle(fontSize: 13)),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                // A phone has no room for a full path; show the folder name.
                wide ? app.outDir : app.outDirLabel,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                textDirection: wide ? TextDirection.rtl : TextDirection.ltr,
                style: TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 12.5,
                  color: s.text,
                ),
              ),
            ),
          ],
        ),
      ),
    );

    return RetroWindow(
      title: app.titleFor(app.view),
      shadow: wide ? 5 : 3,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        child: Row(
          children: [
            Text('save to',
                style:
                    TextStyle(fontFamily: kPixel, fontSize: 11, color: s.muted)),
            const SizedBox(width: 8),
            Expanded(child: folderChip),
            const SizedBox(width: 8),
            IconBtn(
              glyph: '↗',
              tooltip: 'Open output folder',
              onPressed: () async {
                final r = await OpenFilex.open(app.outDir);
                if (r.type != ResultType.done) {
                  toast('No file manager could open that folder', error: true);
                }
              },
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------- taskbar

class Taskbar extends StatelessWidget {
  const Taskbar({super.key, required this.startOpen, required this.onStart});
  final bool startOpen;
  final VoidCallback onStart;

  @override
  Widget build(BuildContext context) {
    final app = AppState.instance;
    final s = context.skin;
    // Below this the word labels no longer fit beside Start and the badge.
    final tight = MediaQuery.sizeOf(context).width < 380;
    return Container(
      height: 46,
      padding: const EdgeInsets.symmetric(horizontal: 8),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [s.task2, s.task],
        ),
        border: Border(top: BorderSide(color: s.ink, width: 2)),
      ),
      child: Row(
        children: [
          TaskButton(
            key: const Key('start-button'),
            on: startOpen,
            onTap: onStart,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text('♥', style: TextStyle(color: s.pink, fontSize: 16)),
                const SizedBox(width: 7),
                Text('Start',
                    style: TextStyle(
                        fontFamily: kPixel, fontSize: 12, color: s.titleInk)),
              ],
            ),
          ),
          const SizedBox(width: 8),
          ListenableBuilder(
            listenable: JobQueue.instance,
            builder: (context, _) {
              final n = JobQueue.instance.activeCount;
              return TaskButton(
                key: const Key('jobs-toggle'),
                on: app.jobsOpen,
                onTap: () => app.setJobsOpen(!app.jobsOpen),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Text('⏳', style: TextStyle(fontSize: 14)),
                    if (!tight) ...[
                      const SizedBox(width: 7),
                      Text('jobs',
                          style: TextStyle(
                              fontFamily: kPixel,
                              fontSize: 12,
                              color: s.titleInk)),
                    ],
                    const SizedBox(width: 7),
                    RetroBadge('$n', zero: n == 0),
                  ],
                ),
              );
            },
          ),
          const Spacer(),
          TaskButton(
            key: const Key('theme-toggle'),
            on: false,
            onTap: app.toggleTheme,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(app.dark ? '☾' : '☀',
                    style: const TextStyle(fontSize: 14)),
                const SizedBox(width: 7),
                Text(app.dark ? 'night' : 'day',
                    style: TextStyle(
                        fontFamily: kPixel, fontSize: 12, color: s.titleInk)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class TaskButton extends StatelessWidget {
  const TaskButton(
      {super.key, required this.child, required this.onTap, required this.on});
  final Widget child;
  final VoidCallback onTap;
  final bool on;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        height: 34,
        padding: const EdgeInsets.symmetric(horizontal: 11),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: on ? s.sel : s.win,
          border: Border.all(color: s.ink, width: 2),
          borderRadius: BorderRadius.circular(8),
          boxShadow: on ? null : hardShadow(s.drop, 2),
        ),
        child: child,
      ),
    );
  }
}

/// .start-menu — the full nav, plus the odds and ends.
class StartMenu extends StatelessWidget {
  const StartMenu({super.key, required this.onPick, required this.onClose});
  final ValueChanged<String> onPick;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final app = AppState.instance;
    return SizedBox(
      width: 270,
      child: RetroWindow(
        title: 'start',
        child: SingleChildScrollView(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(10, 10, 0, 10),
                child: Mascot(width: 54),
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.all(8),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      for (final v in views)
                        MenuItem(
                          icon: v[1],
                          label: v[2],
                          onTap: () => onPick(v[0]),
                        ),
                      const Padding(
                        padding: EdgeInsets.symmetric(vertical: 4),
                        child: DashedDivider(),
                      ),
                      MenuItem(
                        icon: '◐',
                        label: 'Day / night',
                        onTap: () {
                          app.toggleTheme();
                          onClose();
                        },
                      ),
                      MenuItem(
                        icon: '📁',
                        label: 'Open output folder',
                        onTap: () async {
                          onClose();
                          await OpenFilex.open(app.outDir);
                        },
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class MenuItem extends StatelessWidget {
  const MenuItem(
      {super.key,
      required this.icon,
      required this.label,
      required this.onTap});
  final String icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        child: Row(
          children: [
            Text(icon, style: const TextStyle(fontSize: 14)),
            const SizedBox(width: 8),
            Expanded(
              child: Text(label,
                  style:
                      TextStyle(fontWeight: FontWeight.w700, color: s.text)),
            ),
          ],
        ),
      ),
    );
  }
}
