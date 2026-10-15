package com.everythingconverter.everything_converter

import android.content.Context
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMetadataRetriever
import android.os.Handler
import android.os.Looper
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.audio.AudioProcessor
import androidx.media3.common.audio.ChannelMixingAudioProcessor
import androidx.media3.common.audio.ChannelMixingMatrix
import androidx.media3.common.audio.SonicAudioProcessor
import androidx.media3.common.Effect
import androidx.media3.common.util.UnstableApi
import androidx.media3.effect.Presentation
import androidx.media3.transformer.AudioEncoderSettings
import androidx.media3.transformer.Composition
import androidx.media3.transformer.DefaultEncoderFactory
import androidx.media3.transformer.EditedMediaItem
import androidx.media3.transformer.Effects
import androidx.media3.transformer.ExportException
import androidx.media3.transformer.ExportResult
import androidx.media3.transformer.ProgressHolder
import androidx.media3.transformer.Transformer
import androidx.media3.transformer.VideoEncoderSettings
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.io.File

/**
 * Re-encodes video and audio at a requested bitrate with the phone's own
 * hardware codecs (Media3 Transformer), so the app needs no FFmpeg.
 * Dart decides the numbers; this class only runs the encode and reports progress.
 */
@UnstableApi
class MediaCompressor(private val context: Context, private val channel: MethodChannel) :
    MethodChannel.MethodCallHandler {

    private val main = Handler(Looper.getMainLooper())
    private val running = mutableMapOf<Int, Transformer>()

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "probe" -> probe(call.argument<String>("path")!!, result)
            "transcode" -> transcode(call, result)
            "cancel" -> {
                running.remove(call.argument<Int>("id"))?.cancel()
                result.success(null)
            }
            else -> result.notImplemented()
        }
    }

    private fun probe(path: String, result: MethodChannel.Result) {
        val out = HashMap<String, Any?>()
        val r = MediaMetadataRetriever()
        try {
            r.setDataSource(path)
            fun num(key: Int) = r.extractMetadata(key)?.toLongOrNull()
            out["durationMs"] = num(MediaMetadataRetriever.METADATA_KEY_DURATION) ?: 0L
            out["hasVideo"] = r.extractMetadata(MediaMetadataRetriever.METADATA_KEY_HAS_VIDEO) == "yes"
            out["hasAudio"] = r.extractMetadata(MediaMetadataRetriever.METADATA_KEY_HAS_AUDIO) == "yes"
            out["width"] = num(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH) ?: 0L
            out["height"] = num(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT) ?: 0L
            out["fps"] = frameRate(path)
            result.success(out)
        } catch (e: Exception) {
            result.error("probe", "Couldn't read ${File(path).name}: ${e.message}", null)
        } finally {
            r.release()
        }
    }

    private fun frameRate(path: String): Double {
        val ex = MediaExtractor()
        return try {
            ex.setDataSource(path)
            (0 until ex.trackCount).map { ex.getTrackFormat(it) }
                .firstOrNull { it.getString(MediaFormat.KEY_MIME)?.startsWith("video/") == true }
                ?.takeIf { it.containsKey(MediaFormat.KEY_FRAME_RATE) }
                ?.getInteger(MediaFormat.KEY_FRAME_RATE)?.toDouble() ?: 30.0
        } catch (e: Exception) {
            30.0
        } finally {
            ex.release()
        }
    }

    private fun transcode(call: MethodCall, result: MethodChannel.Result) {
        val id = call.argument<Int>("id")!!
        val input = call.argument<String>("input")!!
        val output = call.argument<String>("output")!!
        val videoBitrate = call.argument<Int>("videoBitrate") ?: 0
        val audioBitrate = call.argument<Int>("audioBitrate") ?: 0
        val shortSide = call.argument<Int>("shortSide") ?: 0
        val h265 = call.argument<Boolean>("h265") ?: false
        val mono = call.argument<Boolean>("mono") ?: false
        val sampleRate = call.argument<Int>("sampleRate") ?: 0
        val audioOnly = videoBitrate <= 0
        File(output).delete()

        val encoders = DefaultEncoderFactory.Builder(context)
            .setEnableFallback(true)
        if (!audioOnly) {
            encoders.setRequestedVideoEncoderSettings(
                VideoEncoderSettings.Builder().setBitrate(videoBitrate).build())
        }
        if (audioBitrate > 0) {
            encoders.setRequestedAudioEncoderSettings(
                AudioEncoderSettings.Builder().setBitrate(audioBitrate).build())
        }

        // An audio processor is always present so the track is re-encoded at the
        // new bitrate rather than copied through untouched.
        val mixer = ChannelMixingAudioProcessor()
        for (n in 1..8) {
            mixer.putChannelMixingMatrix(
                if (mono) ChannelMixingMatrix.createForConstantGain(n, 1)
                else ChannelMixingMatrix.createForConstantGain(n, minOf(n, 2)))
        }
        val audioFx = mutableListOf<AudioProcessor>(mixer)
        if (sampleRate > 0) {
            audioFx += SonicAudioProcessor().apply { setOutputSampleRateHz(sampleRate) }
        }
        val videoFx = mutableListOf<Effect>()
        if (!audioOnly && shortSide > 0) videoFx += Presentation.createForShortSide(shortSide)

        val item = EditedMediaItem.Builder(MediaItem.fromUri(android.net.Uri.fromFile(File(input))))
            .setRemoveVideo(audioOnly)
            .setRemoveAudio(audioBitrate <= 0)
            .setEffects(Effects(audioFx, videoFx))
            .build()

        val transformer = Transformer.Builder(context)
            .setEncoderFactory(encoders.build())
            .setAudioMimeType(MimeTypes.AUDIO_AAC)
            .apply { if (!audioOnly) setVideoMimeType(if (h265) MimeTypes.VIDEO_H265 else MimeTypes.VIDEO_H264) }
            .addListener(object : Transformer.Listener {
                override fun onCompleted(composition: Composition, exportResult: ExportResult) {
                    running.remove(id)
                    result.success(null)
                }

                override fun onError(composition: Composition, exportResult: ExportResult, exportException: ExportException) {
                    val wasRunning = running.remove(id) != null
                    File(output).delete()
                    result.error("encode", if (wasRunning) exportException.message ?: "Encoding failed" else "cancelled", null)
                }
            })
            .build()
        running[id] = transformer

        try {
            transformer.start(item, output)
        } catch (e: Exception) {
            running.remove(id)
            result.error("encode", e.message ?: "Couldn't start the encoder", null)
            return
        }

        // Media3 has no progress callback; poll it and forward to Dart.
        val holder = ProgressHolder()
        main.post(object : Runnable {
            override fun run() {
                val t = running[id] ?: return
                if (t.getProgress(holder) == Transformer.PROGRESS_STATE_AVAILABLE) {
                    channel.invokeMethod("progress", mapOf("id" to id, "p" to holder.progress / 100.0))
                }
                main.postDelayed(this, 300)
            }
        })
    }
}
