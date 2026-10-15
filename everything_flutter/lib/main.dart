/// Everything Converter — Android build.
/// A fully offline convert-anything toolbox. No network code anywhere in here:
/// every engine runs on-device.
library;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'core/app_state.dart';
import 'core/theme.dart';
import 'shell.dart';
import 'widgets/toast.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await SystemChrome.setPreferredOrientations([
    DeviceOrientation.portraitUp,
    DeviceOrientation.portraitDown,
    DeviceOrientation.landscapeLeft,
    DeviceOrientation.landscapeRight,
  ]);
  // Never let start-up failure turn into a black screen: the app is still
  // usable with defaults, and the user gets told what went wrong.
  String? startupError;
  try {
    await AppState.instance.init();
  } catch (e) {
    startupError = e.toString();
  }
  runApp(const EverythingConverterApp());
  if (startupError != null) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      toast('Started with defaults — $startupError', error: true);
    });
  }
}

class EverythingConverterApp extends StatelessWidget {
  const EverythingConverterApp({super.key});

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: AppState.instance,
      builder: (context, _) {
        final skin = AppState.instance.dark ? Skin.night : Skin.day;
        return MaterialApp(
          title: 'Everything Converter',
          debugShowCheckedModeBanner: false,
          theme: buildTheme(skin),
          builder: (context, child) => ToastHost(
            key: toastKey,
            child: child ?? const SizedBox.shrink(),
          ),
          home: const Shell(),
        );
      },
    );
  }
}
