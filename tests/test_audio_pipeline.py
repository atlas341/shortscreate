from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.processing import music, processor


class AudioPipelineTest(unittest.TestCase):
    def _process(self, mode: str, source_has_audio: bool = True) -> list[str]:
        with TemporaryDirectory(dir=processor.settings.base_dir) as temp_dir:
            root = Path(temp_dir)
            input_file = root / "source.mp4"
            input_file.touch()
            work_dir = root / "work"

            patches = [
                patch.object(processor, "get_video_size", return_value=(1920, 1080)),
                patch.object(processor, "get_duration", return_value=12.0),
                patch.object(processor, "has_audio", return_value=source_has_audio),
                patch.object(processor, "get_frame_rate", return_value="30"),
                patch.object(
                    processor,
                    "background_input_arguments",
                    return_value=(["-i", "background.mp4"], Path("background.mp4")),
                ),
                patch.object(
                    processor,
                    "top_overlay_base_filters",
                    return_value=(["[0:v]null[uniq]"], (1080, 1920)),
                ),
                patch.object(
                    processor,
                    "top_overlay_filters",
                    side_effect=lambda video_label, overlay_index, output_label, fps: [
                        f"[{overlay_index}:v]null[topvideo]",
                        f"{video_label}[topvideo]overlay{output_label}",
                    ],
                ),
                patch.object(
                    processor,
                    "pick_overlay_video",
                    return_value=Path("overlay.mp4"),
                ),
                patch.object(
                    processor,
                    "overlay_input_arguments",
                    return_value=["-i", "overlay.mp4"],
                ),
                patch.object(processor, "circle_filters", return_value=(["[0:v]null[uniq]"], (1080, 1920))),
                patch.object(processor, "crop_filters", return_value=(["[0:v]null[uniq]"], (1080, 1920))),
                patch.object(processor, "zoom_filters", return_value=(["[0:v]null[uniq]"], (1080, 1920))),
                patch.object(processor, "find_outro_image", return_value=Path("outro.png")),
                patch.object(
                    processor,
                    "outro_input_arguments",
                    return_value=["-i", "outro.png"],
                ),
                patch.object(
                    processor,
                    "outro_filters",
                    side_effect=lambda video_label, output_label, **kwargs: [
                        f"{video_label}outro{output_label}"
                    ],
                ),
                patch.object(music, "get_runtime", return_value={"music_enabled": True, "music_volume_percent": 17}),
                patch.object(music, "random_asset", return_value=Path("music.mp3")),
                patch.object(
                    processor,
                    "ensure_output",
                    return_value=work_dir / "result.mp4",
                ),
                patch.object(processor, "file_size_mb", return_value=1.0),
            ]

            with ExitStack() as stack:
                for test_patch in patches:
                    stack.enter_context(test_patch)

                run_ffmpeg = stack.enter_context(patch.object(processor, "run_ffmpeg"))
                processor.process_video(
                    input_file,
                    work_dir,
                    processor.ProcessingOptions(mode=mode, mirror=False, outro=True),
                )

            return run_ffmpeg.call_args.args[0]

    def test_configured_music_volume_is_mixed_in_every_mode(self) -> None:
        for mode in processor.MODES:
            with self.subTest(mode=mode):
                arguments = self._process(mode)
                graph = arguments[arguments.index("-filter_complex") + 1]
                music_input_position = arguments.index("music.mp3")
                music_index = arguments[:music_input_position].count("-i") - 1

                self.assertIn(f"[{music_index}:a]aresample=48000", graph)
                self.assertIn("volume=0.1700", graph)
                self.assertIn("atrim=duration=15.000", graph)
                self.assertIn("afade=t=out:st=14.000:d=1", graph)
                self.assertIn("apad=whole_dur=15.000", graph)
                self.assertIn("amix=inputs=2:duration=first", graph)
                self.assertIn("alimiter=limit=0.95:level=0[aout]", graph)
                map_positions = [index for index, value in enumerate(arguments) if value == "-map"]
                self.assertEqual(arguments[map_positions[1] + 1], "[aout]")

    def test_music_without_source_audio_is_limited_and_mapped(self) -> None:
        arguments = self._process("top_overlay", source_has_audio=False)
        graph = arguments[arguments.index("-filter_complex") + 1]

        self.assertNotIn("[0:a]", graph)
        self.assertIn("[music]alimiter=limit=0.95:level=0[aout]", graph)
        map_positions = [index for index, value in enumerate(arguments) if value == "-map"]
        self.assertEqual(arguments[map_positions[1] + 1], "[aout]")


if __name__ == "__main__":
    unittest.main()
