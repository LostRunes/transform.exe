/// jobs.exe — live progress, cancel, and links to the files that came out.
library;
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:open_filex/open_filex.dart';
import 'package:path/path.dart' as pp;
import 'package:share_plus/share_plus.dart';

import '../core/jobs.dart';
import '../core/models.dart';
import '../core/theme.dart';
import 'mascot.dart';
import 'pickers.dart';
import 'retro.dart';
import 'toast.dart';

class JobsPanel extends StatelessWidget {
  const JobsPanel({super.key, this.onClose});
  final VoidCallback? onClose;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return RetroWindow(
      title: 'jobs.exe',
      onClose: onClose,
      child: AnimatedBuilder(
        animation: JobQueue.instance,
        builder: (context, _) {
          final jobs = JobQueue.instance.jobs;
          return Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 10, 12, 0),
                child: Align(
                  alignment: Alignment.centerRight,
                  child: RetroButton(
                    label: 'Clear finished',
                    kind: BtnKind.ghost,
                    size: BtnSize.sm,
                    onPressed: JobQueue.instance.clearFinished,
                  ),
                ),
              ),
              Flexible(
                child: jobs.isEmpty
                    ? const MascotEmpty(
                        text: 'nothing yet~ zzz',
                        sub: 'Conversions show up here with live progress.',
                      )
                    : ListView(
                        shrinkWrap: true,
                        padding: const EdgeInsets.all(12),
                        children: [for (final j in jobs) _JobCard(job: j)],
                      ),
              ),
              if (jobs.isEmpty) SizedBox(height: 4, child: ColoredBox(color: s.win)),
            ],
          );
        },
      ),
    );
  }
}

class _JobCard extends StatelessWidget {
  const _JobCard({required this.job});
  final Job job;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    final statusColor = switch (job.status) {
      JobStatus.done => s.ok,
      JobStatus.error || JobStatus.cancelled => s.err,
      _ => s.accent,
    };
    final barColor = switch (job.status) {
      JobStatus.done => s.mint,
      JobStatus.error || JobStatus.cancelled => s.pink,
      _ => null,
    };

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: s.win2,
        border: Border.all(color: s.inkSoft, width: 2),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Text(job.title,
                    style: TextStyle(
                        fontWeight: FontWeight.w800,
                        fontSize: 13,
                        color: s.text)),
              ),
              const SizedBox(width: 8),
              StatusPill(job.statusLabel, color: statusColor),
            ],
          ),
          const SizedBox(height: 3),
          Text(job.message,
              style: TextStyle(fontSize: 12, color: s.muted)),
          const SizedBox(height: 8),
          RetroBar(value: job.progress, color: barColor),
          if (job.active) ...[
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerLeft,
              child: RetroButton(
                label: 'Cancel',
                kind: BtnKind.ghost,
                size: BtnSize.sm,
                onPressed: () => JobQueue.instance.cancel(job.id),
              ),
            ),
          ],
          if (job.outputs.isNotEmpty) ...[
            const SizedBox(height: 8),
            for (final path in job.outputs.take(30)) _OutRow(path: path),
            if (job.outputs.length > 30)
              Text('…and ${job.outputs.length - 30} more',
                  style: TextStyle(fontSize: 12, color: s.muted)),
          ],
          if (job.notes.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(job.notes.join('\n'),
                style: TextStyle(fontSize: 12, color: s.muted)),
          ],
          if (job.errors.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(job.errors.join('\n'),
                style: TextStyle(fontSize: 12, color: s.err)),
          ],
        ],
      ),
    );
  }
}

class _OutRow extends StatelessWidget {
  const _OutRow({required this.path});
  final String path;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        children: [
          Flexible(
            child: Text(
              pp.basename(path),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 12, color: s.text),
            ),
          ),
          const Spacer(),
          const SizedBox(width: 8),
          _Link(
            label: 'Open',
            onTap: () async {
              final r = await OpenFilex.open(path);
              if (r.type != ResultType.done) toast(r.message, error: true);
            },
          ),
          const SizedBox(width: 10),
          _Link(label: 'Save', onTap: () => downloadFile(path)),
          const SizedBox(width: 10),
          _Link(
            label: 'Share',
            onTap: () async {
              if (!File(path).existsSync()) {
                toast('That file is gone', error: true);
                return;
              }
              await SharePlus.instance.share(
                ShareParams(files: [XFile(path)], title: pp.basename(path)),
              );
            },
          ),
        ],
      ),
    );
  }
}

class _Link extends StatelessWidget {
  const _Link({required this.label, required this.onTap});
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final s = context.skin;
    return GestureDetector(
      onTap: onTap,
      child: Text(label,
          style: TextStyle(
              color: s.accent, fontWeight: FontWeight.w800, fontSize: 12)),
    );
  }
}
